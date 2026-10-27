"""Tests for the Gemini-powered Agri AI Assistant endpoints.

The Gemini API itself is never called from these tests: the success path is
exercised by patching :func:`apps.core.views.generate_reply`, and the missing
credential path is exercised by running without ``GEMINI_API_KEY`` set.
"""

import os
import json
import httpx
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.core import gemini
from apps.core import views as core_views
from apps.core.gemini import GeminiUnavailableError, RateLimitError
from apps.core.models import Conversation, Message

User = get_user_model()


def _delete_env(name):
    os.environ.pop(name, None)


def _direct_chat_request(user, data):
    request = RequestFactory().post(reverse('chat'), data)
    request.user = user
    return core_views._chat_view(request)


@override_settings(DEBUG=False)
class ChatViewTests(TestCase):
    """Endpoint behaviour when the Gemini API is not configured."""

    def setUp(self):
        _delete_env('GEMINI_API_KEY')
        _delete_env('GEMINI_MODEL')

    def test_chat_without_credentials_returns_error(self):
        user = User.objects.create_user(
            username='farmer',
            first_name='Seed',
            last_name='Farmer',
            email='farmer@example.com',
            password='secret1234',
        )
        response = _direct_chat_request(user, {'message': 'How do I improve my soil?'})

        self.assertEqual(response.status_code, 503)
        self.assertIn('GEMINI_API_KEY', json.loads(response.content)['error'])

    def test_chat_without_credentials_persists_no_messages(self):
        user = User.objects.create_user(
            username='farmer-a',
            first_name='Seed',
            last_name='Farmer',
            email='farmer-a@example.com',
            password='secret1234',
        )
        _direct_chat_request(user, {'message': 'Hello!'})

        self.assertEqual(Message.objects.filter(sender=user).count(), 0)

        self.assertEqual(Message.objects.filter(sender=user).count(), 0)


class AuthenticatedChatViewTests(TestCase):
    """Authenticated behaviour of the chat endpoint."""

    def setUp(self):
        _delete_env('GEMINI_API_KEY')
        self.user = User.objects.create_user(
            username='farmer-b',
            first_name='Seed',
            last_name='Farmer',
            email='farmer-b@example.com',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def test_chat_stores_conversation_and_reply(self):
        reply = 'Advice stored and returned.'
        original = core_views.generate_reply
        core_views.generate_reply = lambda owner, message, history, image_file=None: reply
        try:
            response = self.client.post(reverse('chat'), {'message': 'Tell me about my maize'})
        finally:
            core_views.generate_reply = original

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['reply'], reply)
        self.assertTrue(payload['conversation_id'])

        conversation = Conversation.objects.get(pk=payload['conversation_id'])
        self.assertEqual(conversation.owner, self.user)
        messages = list(conversation.messages.all())
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, self.user)
        self.assertEqual(messages[0].body, 'Tell me about my maize')
        self.assertIsNone(messages[1].sender)
        self.assertEqual(messages[1].body, reply)

    def test_follow_up_questions_continue_the_same_conversation(self):
        reply = 'A follow-up answer.'
        original = core_views.generate_reply
        core_views.generate_reply = lambda owner, message, history, image_file=None: reply
        try:
            first = self.client.post(reverse('chat'), {'message': 'What should I plant first?'})
            conversation_id = first.json()['conversation_id']

            second = self.client.post(
                reverse('chat'),
                {'message': 'And when should I harvest?', 'conversation_id': conversation_id},
            )
        finally:
            core_views.generate_reply = original

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['conversation_id'], conversation_id)
        conversation = Conversation.objects.get(pk=conversation_id)
        # Two turns were stored: the first request and this follow-up.
        self.assertEqual(conversation.message_count, 4)

    def test_replaying_request_id_returns_saved_reply_without_duplicate_messages(self):
        request_id = 'e6b6b31e-5702-4f20-88f2-cc5390ecf900'
        with patch.object(core_views, 'generate_reply', return_value='Saved response') as generate:
            first = self.client.post(reverse('chat'), {
                'message': 'Hello',
                'request_id': request_id,
            })
            replay = self.client.post(reverse('chat'), {
                'message': 'Hello',
                'request_id': request_id,
            })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()['reply'], 'Saved response')
        self.assertEqual(replay.json()['conversation_id'], first.json()['conversation_id'])
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(Message.objects.filter(conversation_id=first.json()['conversation_id']).count(), 2)

    def test_invalid_request_id_is_rejected(self):
        response = self.client.post(reverse('chat'), {
            'message': 'Hello',
            'request_id': 'not-a-uuid',
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Conversation.objects.filter(owner=self.user).count(), 0)

    def test_rate_limited_chat_returns_429_without_creating_conversation(self):
        with patch.object(
            core_views,
            'check_rate_limit',
            side_effect=RateLimitError('Too many requests.'),
        ):
            response = self.client.post(reverse('chat'), {'message': 'Hello'})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(Conversation.objects.filter(owner=self.user).count(), 0)

    def test_chat_endpoint_rejects_get_requests(self):
        response = self.client.get(reverse('chat'))

        self.assertEqual(response.status_code, 405)


class ConversationHistoryTests(TestCase):
    """Per-user ownership of conversation history."""

    def setUp(self):
        _delete_env('GEMINI_API_KEY')
        self.user = User.objects.create_user(
            username='farmer-c',
            first_name='Seed',
            last_name='Farmer',
            email='farmer-c@example.com',
            password='secret1234',
        )
        self.other_user = User.objects.create_user(
            username='neighbour',
            first_name='Other',
            last_name='Neighbour',
            email='neighbour@example.com',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def test_conversation_is_scoped_to_its_owner(self):
        conversation = Conversation.objects.create(owner=self.other_user)
        Message.objects.create(
            conversation=conversation,
            sender=self.other_user,
            body='Only the owner should see this.',
        )

        list_response = self.client.get(reverse('chat_conversations'))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()['conversations'], [])

        messages_response = self.client.get(
            reverse('chat_messages', args=[conversation.pk]),
        )
        self.assertEqual(messages_response.status_code, 404)

        messages_response = self.client.post(
            reverse('chat'),
            {'message': 'Hello!', 'conversation_id': conversation.pk},
        )
        self.assertEqual(messages_response.status_code, 404)


@override_settings(DEBUG=False)
class GeminiRequestFailureTests(TestCase):
    """Failures of the external API are reported, never simulated."""

    def setUp(self):
        _delete_env('GEMINI_API_KEY')
        self.user = User.objects.create_user(
            username='farmer-d',
            first_name='Seed',
            last_name='Farmer',
            email='farmer-d@example.com',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def test_rate_limit_rejects_excessive_requests(self):
        from apps.core import gemini

        gemini._recent_request_times.clear()
        gemini.RATE_LIMIT_MAX_REQUESTS = 2
        try:
            gemini.check_rate_limit(self.user)
            gemini.check_rate_limit(self.user)
            with self.assertRaises(gemini.RateLimitError):
                gemini.check_rate_limit(self.user)
        finally:
            gemini._recent_request_times.clear()
            gemini.RATE_LIMIT_MAX_REQUESTS = 20

    def test_generate_reply_error_is_returned_to_the_user(self):
        from apps.core.gemini import GeminiRequestError

        def failing_generate_reply(owner, message, history, image_file=None):
            raise GeminiRequestError('The AI provider is unavailable.')

        original = core_views.generate_reply
        core_views.generate_reply = failing_generate_reply
        try:
            response = _direct_chat_request(self.user, {'message': 'Tell me about rainfall.'})
        finally:
            core_views.generate_reply = original

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)['error'], 'The AI provider is unavailable.')

    def test_timeout_failure_is_sanitized_and_does_not_store_messages(self):
        original = core_views.generate_reply
        core_views.generate_reply = lambda *args, **kwargs: (_ for _ in ()).throw(
            GeminiUnavailableError(
                'Sorry, the AI assistant is temporarily unable to connect. Please check your connection and try again.'
            )
        )
        try:
            response = _direct_chat_request(self.user, {'message': 'Hello'})
        finally:
            core_views.generate_reply = original

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)['code'], 'temporarily_unavailable')
        self.assertEqual(
            json.loads(response.content)['error'],
            'Sorry, the AI assistant is temporarily unable to connect. Please check your connection and try again.',
        )
        self.assertFalse(Conversation.objects.filter(owner=self.user).exists())


class GeminiTransportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='transport-test',
            password='secret1234',
        )
        self.client.force_login(self.user)

    def tearDown(self):
        gemini._connection_status = None
        gemini._connection_status_checked_at = 0
        gemini._connection_status_model = None

    def test_sdk_client_uses_seconds_for_connect_and_read_timeouts(self):
        with patch.dict(os.environ, {
            'GEMINI_API_KEY': 'test-only-key',
            'GEMINI_TIMEOUT_SECONDS': '27',
            'GEMINI_CONNECT_TIMEOUT_SECONDS': '6',
        }):
            with patch.object(gemini, '_client', None), patch.object(
                gemini, '_client_key_fingerprint', None
            ), patch.object(gemini.genai, 'Client') as client_factory:
                gemini.get_client()

        options = client_factory.call_args.kwargs['http_options']
        self.assertIsNone(options.timeout)
        self.assertEqual(options.client_args['timeout'].connect, 6)
        self.assertEqual(options.client_args['timeout'].read, 27)
        self.assertEqual(options.retry_options.attempts, 1)

    def test_transient_connect_timeout_is_retried_once(self):
        response = type('Response', (), {'text': 'OK'})()
        client = type('Client', (), {})()
        client.models = type('Models', (), {
            'generate_content': Mock(
                side_effect=[httpx.ConnectTimeout('temporary'), response]
            )
        })()
        with patch.object(gemini, 'max_retries', return_value=1), patch.object(
            gemini.time, 'sleep'
        ) as sleep:
            actual = gemini._generate_with_retries(client, 'hello', None)

        self.assertIs(actual, response)
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once()

    def test_connection_status_checks_selected_model(self):
        models = Mock()
        client = Mock(models=models)
        with patch.dict(os.environ, {
            'GEMINI_API_KEY': 'test-only-key',
            'GEMINI_MODEL': 'gemini-test-model',
        }), patch.object(gemini, 'get_client', return_value=client):
            status = gemini.connection_status(force=True)

        self.assertEqual(status['state'], 'connected')
        models.get.assert_called_once_with(model='gemini-test-model')

    def test_invalid_api_credentials_are_not_retried(self):
        from google.genai.errors import APIError

        client = type('Client', (), {})()
        client.models = type('Models', (), {
            'generate_content': Mock(
                side_effect=APIError(401, {'error': {'message': 'Unauthorized'}})
            )
        })()
        with patch.object(gemini, 'max_retries', return_value=3), patch.object(
            gemini.time, 'sleep'
        ) as sleep:
            with self.assertRaises(gemini.GeminiAuthenticationError):
                gemini._generate_with_retries(client, 'hello', None)

        self.assertEqual(client.models.generate_content.call_count, 1)
        sleep.assert_not_called()

    def test_invalid_api_key_400_is_classified_as_authentication_error(self):
        from google.genai.errors import APIError

        client = type('Client', (), {})()
        client.models = type('Models', (), {
            'generate_content': Mock(
                side_effect=APIError(
                    400,
                    {'error': {
                        'message': 'API key not valid. Please pass a valid API key.',
                        'status': 'INVALID_ARGUMENT',
                    }},
                )
            )
        })()
        with patch.object(gemini, 'max_retries', return_value=2), patch.object(
            gemini.time, 'sleep'
        ) as sleep:
            with self.assertRaises(gemini.GeminiAuthenticationError):
                gemini._generate_with_retries(client, 'hello', None)

        self.assertEqual(client.models.generate_content.call_count, 1)
        sleep.assert_not_called()

    def test_rate_limit_response_is_retried(self):
        from google.genai.errors import APIError

        response = type('Response', (), {'text': 'OK'})()
        client = type('Client', (), {})()
        client.models = type('Models', (), {
            'generate_content': Mock(side_effect=[
                APIError(429, {'error': {'message': 'Slow down', 'status': 'RESOURCE_EXHAUSTED'}}),
                response,
            ])
        })()
        with patch.object(gemini, 'max_retries', return_value=1), patch.object(
            gemini.time, 'sleep'
        ) as sleep:
            actual = gemini._generate_with_retries(client, 'hello', None)

        self.assertIs(actual, response)
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once()

    def test_status_endpoint_reports_real_status_without_exposing_credentials(self):
        with patch.object(
            core_views,
            'connection_status',
            return_value={'state': 'temporarily_unavailable', 'message': 'Try again.'},
        ):
            request = RequestFactory().get(reverse('gemini_status'))
            request.user = self.user
            response = core_views.gemini_status(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)['state'], 'temporarily_unavailable')
        self.assertNotIn('key', response.content.decode().lower())
