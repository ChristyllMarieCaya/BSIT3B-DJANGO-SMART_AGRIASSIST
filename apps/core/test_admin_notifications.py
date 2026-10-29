from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.info.models import Notification, WeatherAlert

User = get_user_model()


class AdminNotificationCenterTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='notifications-admin',
            email='notifications-admin@example.com',
            password='SecureAdminPass123!',
        )
        self.farmer = User.objects.create_user(username='notification-farmer', password='FarmerPass123!')
        self.other_farmer = User.objects.create_user(username='other-notification-farmer')
        self.unread = Notification.objects.create(
            user=self.farmer,
            title='Crop care reminder',
            message='Review the field.',
            priority=Notification.Priority.HIGH,
        )
        self.read = Notification.objects.create(
            user=self.other_farmer,
            title='Read notice',
            message='Already reviewed.',
            read=True,
        )
        self.alert = WeatherAlert.objects.create(
            user=self.farmer,
            farm_location='Cauayan, Isabela',
            alert_type='storm',
            severity=WeatherAlert.Severity.CRITICAL,
            title='Severe storm warning',
            forecast_condition='Storms expected.',
            agricultural_impact='Possible crop damage.',
            precautionary_actions='Secure equipment.',
        )

    def test_staff_only_notification_center_and_status_endpoint(self):
        response = self.client.get(reverse('admin_notifications'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

        self.client.force_login(self.farmer)
        response = self.client.get(reverse('admin_notifications_status'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('admin_notifications_status'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_notifications'], 1)
        self.assertEqual(response.json()['active_alerts'], 1)
        self.assertEqual(response.json()['critical_alerts'], 1)

    def test_notification_dismissal_requires_csrf_and_never_resolves_weather_alerts(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        response = csrf_client.post(reverse('admin_notifications'), {
            'kind': 'notification',
            'record_id': self.unread.pk,
        })
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('admin_notifications'), {
            'kind': 'weather',
            'record_id': self.alert.pk,
        })
        self.assertRedirects(response, reverse('admin_notifications'))
        self.assertNotIn(
            f'weather:{self.alert.pk}',
            response.wsgi_request.session.get('dismissed_admin_notification_ids', []),
        )
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.is_active)

    def test_center_filters_records_and_dismissal_preserves_database_state(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('admin_notifications'), {'filter': 'critical'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Severe storm warning')
        self.assertNotContains(response, 'Crop care reminder')
        self.assertNotContains(response, 'Read notice')

        response = self.client.post(reverse('admin_notifications'), {
            'kind': 'notification',
            'record_id': self.unread.pk,
            'filter': 'critical',
        })
        self.assertRedirects(response, f"{reverse('admin_notifications')}?filter=critical")
        self.assertIn(
            f'notification:{self.unread.pk}',
            response.wsgi_request.session['dismissed_admin_notification_ids'],
        )
        self.alert.refresh_from_db()
        self.unread.refresh_from_db()
        self.assertTrue(self.alert.is_active)
        self.assertFalse(self.unread.read)
        self.assertIsNone(self.unread.deleted_at)

        response = self.client.get(reverse('admin_notifications'), {'filter': 'critical'})
        self.assertContains(response, 'Severe storm warning')
        self.assertNotContains(response, 'Crop care reminder')
        self.assertEqual(WeatherAlert.objects.filter(pk=self.alert.pk, is_active=True).count(), 1)

    def test_notification_filters_include_only_matching_records(self):
        self.client.force_login(self.admin_user)

        unread = self.client.get(reverse('admin_notifications'), {'filter': 'unread'})
        self.assertContains(unread, 'Crop care reminder')
        self.assertContains(unread, 'Severe storm warning')
        self.assertNotContains(unread, 'Read notice')

        Notification.objects.create(
            user=self.other_farmer,
            title='Most recent low-priority notice',
            message='New but informational.',
            priority=Notification.Priority.LOW,
        )
        all_items = self.client.get(reverse('admin_notifications'))
        self.assertEqual(all_items.context['notifications'][0]['title'], 'Severe storm warning')

        resolved_filter = self.client.get(reverse('admin_notifications'), {'filter': 'resolved'})
        self.assertContains(resolved_filter, 'No notifications to show')

    def test_admin_changelist_filters_render_beside_search_and_still_filter(self):
        self.client.force_login(self.admin_user)
        Notification.objects.create(
            user=self.farmer,
            title='Weather alert',
            message='Review the forecast.',
            category=Notification.Category.WEATHER_ALERT,
        )

        changelist_url = reverse('admin:info_notification_changelist')
        response = self.client.get(changelist_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-changelist-toolbar')
        self.assertContains(response, 'admin-changelist-filter-select')
        self.assertContains(response, 'Filter by Category')
        self.assertContains(response, 'Filter by Priority')
        self.assertNotContains(response, 'id="changelist-filter"')
        self.assertContains(response, 'category__exact=weather_alert')
        self.assertContains(response, 'priority__exact=high')

        filtered_response = self.client.get(changelist_url, {'category__exact': 'weather_alert'})
        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(filtered_response.context['cl'].result_count, 1)

    def test_expired_and_deleted_notifications_are_not_counted_or_shown(self):
        Notification.objects.create(
            user=self.farmer,
            title='Expired notice',
            message='This is no longer current.',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        Notification.objects.create(
            user=self.farmer,
            title='Deleted notice',
            message='This was removed.',
            deleted_at=timezone.now(),
        )
        self.client.force_login(self.admin_user)

        status = self.client.get(reverse('admin_notifications_status')).json()
        self.assertEqual(status['unread_notifications'], 1)
        response = self.client.get(reverse('admin_notifications'))
        self.assertNotContains(response, 'Expired notice')
        self.assertNotContains(response, 'Deleted notice')

    @patch('apps.core.gemini.connection_status', return_value={'state': 'connected', 'message': 'Connected'})
    def test_dashboard_is_compact_and_alerts_are_data_driven(self, _connection_status):
        self.client.force_login(self.admin_user)
        self.alert.is_active = False
        self.alert.save(update_fields=['is_active'])
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active Growing Crops')
        self.assertContains(response, 'Registered Accounts')
        self.assertContains(response, 'Pending Care Tasks')
        self.assertContains(response, 'Active Weather Alerts')
        self.assertContains(response, 'Additional analytics and recent records')
        self.assertContains(response, "Path=/admin/")
        self.assertNotContains(response, 'smart_app_theme=')
        self.assertNotContains(response, 'SEVERE WEATHER WARNING')
        self.assertNotContains(response, 'admin-weather-summary')

        self.alert.is_active = True
        self.alert.save(update_fields=['is_active'])
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'admin-weather-summary')
        self.assertContains(response, 'Severe storm warning')
        self.assertEqual(response.context['active_weather_count'], 1)

        self.alert.is_active = False
        self.alert.save(update_fields=['is_active'])
        response = self.client.get(reverse('admin:index'))
        self.assertNotContains(response, 'admin-weather-summary')


class AdminUserManagementTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='users-admin',
            email='users-admin@example.com',
            password='SecureAdminPass123!',
        )
        self.farmer = User.objects.create_user(
            username='searchable-farmer',
            email='farmer@example.com',
            first_name='Maya',
            last_name='Santos',
            password='FarmerPass123!',
        )
        self.client.force_login(self.admin_user)

    def test_user_management_search_filters_summary_and_add_form(self):
        response = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cl'].list_per_page, 25)
        self.assertContains(response, 'User Management')
        self.assertContains(response, 'Total registered users')
        self.assertEqual(response.context['total_registered_users'], 2)

        response = self.client.get(reverse('admin:auth_user_changelist'), {'q': 'Maya'})
        self.assertContains(response, 'searchable-farmer')

        response = self.client.get(reverse('admin:auth_user_changelist'), {'account_role': 'farmer'})
        self.assertContains(response, 'searchable-farmer')

        response = self.client.get(reverse('admin:auth_user_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Username')

    def test_user_change_form_hides_groups_selector(self):
        response = self.client.get(reverse('admin:auth_user_change', args=[self.farmer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Available groups')
        self.assertNotContains(response, 'name="groups"')

    def test_account_status_action_requires_confirmation_and_has_no_default_password_action(self):
        from apps.core.admin import CustomUserAdmin

        self.assertNotIn('reset_password_to_temp', CustomUserAdmin.actions)
        change_list = reverse('admin:auth_user_changelist')
        data = {
            'action': 'deactivate_users',
            '_selected_action': [str(self.farmer.pk)],
            'index': '0',
            'select_across': '0',
        }
        confirmation = self.client.post(change_list, data)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'Confirm account change')
        self.farmer.refresh_from_db()
        self.assertTrue(self.farmer.is_active)

        data['confirm_action'] = '1'
        response = self.client.post(change_list, data)
        self.farmer.refresh_from_db()
        self.assertFalse(self.farmer.is_active)
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), '1 user account(s) deactivated.')
