from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from apps.info.models import Notification


class HomeViewTests(TestCase):
    def test_home_renders_for_authenticated_user(self):
        user = get_user_model().objects.create_user(username='admin', password='secret1234')

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

    def test_home_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)


class NotificationManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='farmer', password='secret1234')
        self.other_user = user_model.objects.create_user(username='other', password='secret1234')
        self.unread = Notification.objects.create(
            user=self.user,
            title='Rain alert',
            message='Heavy rainfall is forecast.',
            category=Notification.Category.WEATHER_ALERT,
        )
        self.read = Notification.objects.create(
            user=self.user,
            title='Settings updated',
            message='Preferences saved.',
            category=Notification.Category.NOTICE,
            read=True,
        )
        self.other_notification = Notification.objects.create(
            user=self.other_user,
            title='Private alert',
            message='Another farmer notification.',
        )
        self.api_url = reverse('notifications_api')
        self.client.force_login(self.user)

    def test_list_filters_by_status_and_category(self):
        response = self.client.get(self.api_url, {'status': 'unread', 'category': 'weather_alert'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.json()['notifications']], [self.unread.pk])
        self.assertEqual(response.json()['unread_count'], 1)

    def test_count_only_endpoint_is_user_scoped_and_tracks_read_state(self):
        response = self.client.get(self.api_url, {'count_only': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'unread_count': 1})

        self.client.post(self.api_url, {
            'action': 'mark_read',
            'notification_id': self.unread.pk,
        })
        response = self.client.get(self.api_url, {'count_only': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'unread_count': 0})

    def test_notifications_page_renders_user_badge_count(self):
        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['unread_count'], 1)
        self.assertContains(response, 'data-notification-unread')
        self.assertContains(response, '1 unread notifications')

    def test_sidebar_badge_hides_at_zero_and_caps_large_counts(self):
        self.unread.read = True
        self.unread.save(update_fields=['read'])
        response = self.client.get(reverse('notifications'))

        self.assertContains(response, 'class="badge bg-danger ms-2 d-none"')

        Notification.objects.bulk_create([
            Notification(
                user=self.user,
                title=f'Alert {index}',
                message='Farm update.',
            )
            for index in range(100)
        ])
        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.context['unread_count'], 100)
        self.assertContains(response, '99+')

    def test_mark_read_is_idempotent_and_sets_read_timestamp(self):
        for _ in range(2):
            response = self.client.post(self.api_url, {
                'action': 'mark_read',
                'notification_id': self.unread.pk,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['unread_count'], 0)

        self.unread.refresh_from_db()
        self.assertTrue(self.unread.read)
        self.assertIsNotNone(self.unread.read_at)

    def test_notification_actions_cannot_access_another_user_record(self):
        response = self.client.post(self.api_url, {
            'action': 'delete',
            'notification_id': self.other_notification.pk,
        })

        self.assertEqual(response.status_code, 404)
        self.other_notification.refresh_from_db()
        self.assertIsNone(self.other_notification.deleted_at)

    def test_delete_soft_deletes_and_excludes_notification_from_list(self):
        response = self.client.post(self.api_url, {
            'action': 'delete',
            'notification_id': self.unread.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 0)
        self.unread.refresh_from_db()
        self.assertIsNotNone(self.unread.deleted_at)
        listed = self.client.get(self.api_url).json()['notifications']
        self.assertNotIn(self.unread.pk, [item['id'] for item in listed])

    def test_search_and_priority_filters_can_be_combined(self):
        self.unread.priority = Notification.Priority.HIGH
        self.unread.save(update_fields=['priority'])

        response = self.client.get(self.api_url, {
            'search': 'rainfall',
            'priority': 'high',
            'status': 'unread',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.json()['notifications']], [self.unread.pk])

    def test_bulk_actions_only_change_the_authenticated_users_notifications(self):
        response = self.client.post(self.api_url, {'action': 'mark_all_read'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 0)
        self.unread.refresh_from_db()
        self.other_notification.refresh_from_db()
        self.assertTrue(self.unread.read)
        self.assertFalse(self.other_notification.read)

        self.client.post(self.api_url, {'action': 'delete_read'})
        self.read.refresh_from_db()
        self.other_notification.refresh_from_db()
        self.assertIsNotNone(self.read.deleted_at)
        self.assertIsNone(self.other_notification.deleted_at)
