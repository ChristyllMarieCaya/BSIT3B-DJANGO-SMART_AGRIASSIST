"""Persistence helpers for conversations with the Agri AI Assistant.

Every queryset is scoped to the requesting user so that one user can never
read or modify another user's conversation.
"""

from django.utils import timezone

from apps.core.models import Conversation, Message


def create_conversation(user):
    """Create a new conversation owned by ``user``."""
    return Conversation.objects.create(owner=user)


def get_conversation(user, conversation_id):
    """Return the conversation only when it belongs to ``user``."""
    return Conversation.objects.filter(pk=conversation_id, owner=user).first()


def get_history(conversation):
    """Return the messages of ``conversation`` in chronological order."""
    return Message.objects.filter(conversation=conversation).order_by('created_at')


def add_message(conversation, sender, body, image=None,
                image_content_type='', image_size=None, client_request_id=None,
                reply_to=None):
    """Append a message to ``conversation`` and return it.

    ``image`` is an optional uploaded file; it is not stored as a crop record.
    """
    return Message.objects.create(
        conversation=conversation,
        sender=sender,
        body=body,
        image=image,
        image_content_type=image_content_type,
        image_size=image_size,
        client_request_id=client_request_id,
        reply_to=reply_to,
    )


def touch_last_message(conversation):
    """Keep the conversation's ``last_message_at`` up to date."""
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=['last_message_at'])
    return conversation


def list_conversations(user, limit=50):
    """Return the user's conversations, newest first."""
    return (
        Conversation.objects
        .filter(owner=user)
        .order_by('-started_at')[:limit]
    )
