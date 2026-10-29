import json
import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Conversation
from apps.crops.models import Crop
from apps.info.models import UserPreference, WeatherAlert, WeatherRecord

User = get_user_model()


class AdminPortalTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='portaladmin',
            email='admin@example.com',
            password='SecureAdminPass123!',
            is_staff=True,
            is_superuser=True,
        )
        self.farmer = User.objects.create_user(username='portal-farmer', password='FarmerPass123!')

    def test_staff_only_portal_routes_reject_regular_users(self):
        self.client.force_login(self.farmer)

        for route_name in ('admin_weather', 'admin_settings'):
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/admin/login/', response.url)

    @patch('apps.core.admin_portal.get_weather')
    @patch('apps.core.admin_portal.geocode_location')
    def test_weather_page_combines_live_data_history_alerts_and_filters(
        self,
        geocode_location,
        get_weather,
    ):
        today = timezone.localdate()
        WeatherRecord.objects.create(
            owner=self.farmer,
            location='Cauayan, Isabela',
            recorded_on=today,
            temperature=28.5,
            rainfall=4.2,
            humidity=75,
            wind_speed=5.0,
        )
        alert = WeatherAlert.objects.create(
            user=self.farmer,
            farm_location='Cauayan, Isabela',
            alert_type='heavy_rain',
            title='Heavy rain risk',
            forecast_condition='Heavy rain expected.',
            agricultural_impact='Possible field flooding.',
            precautionary_actions='Check drainage.',
        )
        geocode_location.return_value = {
            'latitude': 16.9,
            'longitude': 121.7,
            'timezone': 'Asia/Manila',
        }
        get_weather.return_value = {
            'available': True,
            'current': {
                'temperature': 29,
                'temp_unit': '°C',
                'humidity': 70,
                'wind_speed': 5,
                'wind_unit': 'km/h',
                'condition': 'Partly cloudy',
            },
            'forecast': [{
                'date': today.isoformat(),
                'temperature_min': 24,
                'temperature_max': 30,
                'condition': 'Partly cloudy',
                'rain_sum': 2.0,
                'precip_unit': 'mm',
            }],
            'source': 'Open-Meteo Live API',
        }
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('admin_weather'), {
            'location': 'Cauayan, Isabela',
            'start_date': today.isoformat(),
            'end_date': today.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Weather &amp; Alerts')
        self.assertContains(response, 'Partly cloudy')
        self.assertContains(response, 'Heavy rain risk')
        self.assertContains(response, 'Historical observations')
        self.assertEqual(response.context['weather_record_count'], 1)
        history = response.context['history_chart']
        self.assertEqual(history['temperature'], [28.5])
        self.assertEqual(history['rainfall'], [4.2])
        self.assertEqual(WeatherAlert.objects.get(pk=alert.pk).is_active, True)

    @patch('apps.core.admin_portal.get_weather')
    def test_weather_page_reports_unavailable_live_data_without_fabrication(self, get_weather):
        UserPreference.objects.create(
            user=self.farmer,
            farm_location='Cauayan, Isabela',
            latitude=16.9,
            longitude=121.7,
        )
        get_weather.return_value = {
            'available': False,
            'error': 'Weather service is temporarily unavailable.',
        }
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('admin_weather'), {'location': 'Cauayan, Isabela'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Live weather unavailable.')
        self.assertContains(response, 'Weather service is temporarily unavailable.')
        self.assertFalse(response.context['weather']['available'])

    @patch('apps.core.admin_portal.get_weather_history')
    @patch('apps.core.admin_portal.get_weather')
    @patch('apps.core.admin_portal.geocode_location')
    def test_saving_weather_observation_updates_both_history_charts(
        self,
        geocode_location,
        get_weather,
        get_weather_history,
    ):
        today = timezone.localdate()
        record = WeatherRecord.objects.create(
            owner=self.farmer,
            location='Cauayan, Isabela',
            recorded_on=today,
            temperature=25.0,
            rainfall=1.0,
        )
        geocode_location.return_value = {
            'latitude': 16.9,
            'longitude': 121.7,
            'timezone': 'Asia/Manila',
        }
        get_weather.return_value = {
            'available': True,
            'current': {
                'temperature': 29,
                'temp_unit': '°C',
                'humidity': 70,
                'wind_speed': 5,
                'wind_unit': 'km/h',
                'condition': 'Partly cloudy',
            },
            'forecast': [],
            'source': 'Open-Meteo Live API',
        }
        self.client.force_login(self.admin_user)

        response = self.client.post(reverse('admin_weather'), {
            'action': 'update_weather_record',
            'record_id': str(record.pk),
            'location': record.location,
            'start_date': today.isoformat(),
            'end_date': today.isoformat(),
            f'weather-{record.pk}-temperature': '31.25',
            f'weather-{record.pk}-rainfall': '8.50',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The charts have been updated.')
        record.refresh_from_db()
        self.assertEqual(float(record.temperature), 31.25)
        self.assertEqual(float(record.rainfall), 8.5)
        self.assertEqual(record.notes, 'Manually edited in Admin Weather & Alerts.')
        self.assertEqual(response.context['history_chart']['temperature'], [31.25])
        self.assertEqual(response.context['history_chart']['rainfall'], [8.5])
        get_weather_history.assert_not_called()

    def test_admin_settings_persist_profile_preferences_and_password(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('admin_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Change password')
        self.assertContains(response, 'Admin appearance')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertNotIn('theme', response.context['preferences_form'].fields)

        response = self.client.post(reverse('admin_settings'), {
            'action': 'profile',
            'first_name': 'Admin',
            'last_name': 'Farmer',
            'email': 'updated-admin@example.com',
            'country': 'Philippines',
            'preferred_language': 'en',
            'timezone': 'Asia/Manila',
            'channel_in_app': 'on',
            'channel_email': 'on',
        })
        self.assertRedirects(response, reverse('admin_settings'))
        self.admin_user.refresh_from_db()
        preference = UserPreference.objects.get(user=self.admin_user)
        self.assertEqual(self.admin_user.first_name, 'Admin')
        self.assertEqual(self.admin_user.email, 'updated-admin@example.com')
        self.assertEqual(preference.theme, 'light')
        self.assertTrue(preference.channel_in_app)
        self.assertTrue(preference.channel_email)
        self.assertFalse(preference.channel_sms)

        response = self.client.post(reverse('admin_settings'), {
            'action': 'theme',
            'theme': 'dark',
        })
        self.assertRedirects(response, reverse('admin_settings'))
        self.assertEqual(response.cookies['smart_admin_theme'].value, 'dark')
        self.assertEqual(response.cookies['smart_admin_theme']['path'], '/admin/')
        preference.refresh_from_db()
        self.assertEqual(preference.theme, 'light')

        response = self.client.post(reverse('admin_settings'), {
            'action': 'password',
            'password-old_password': 'incorrect-password',
            'password-new_password1': 'NewSecureAdminPass456!',
            'password-new_password2': 'NewSecureAdminPass456!',
        })
        self.assertEqual(response.status_code, 200)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.check_password('SecureAdminPass123!'))

        response = self.client.post(reverse('admin_settings'), {
            'action': 'password',
            'password-old_password': 'SecureAdminPass123!',
            'password-new_password1': 'NewSecureAdminPass456!',
            'password-new_password2': 'NewSecureAdminPass456!',
        })
        self.assertRedirects(response, reverse('admin_settings'))
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.check_password('NewSecureAdminPass456!'))
        self.assertEqual(self.client.get(reverse('admin_settings')).status_code, 200)

    def test_admin_settings_enforces_csrf_and_email_validation(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        response = csrf_client.post(reverse('admin_settings'), {
            'action': 'profile',
            'first_name': 'Should not save',
        })
        self.assertEqual(response.status_code, 403)

        User.objects.create_user(username='other-email', email='taken@example.com')
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('admin_settings'), {
            'action': 'profile',
            'first_name': 'Should not save',
            'last_name': '',
            'email': 'taken@example.com',
            'theme': 'light',
            'country': 'Philippines',
            'preferred_language': 'en',
            'timezone': 'Asia/Manila',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('already associated', str(response.context['profile_form'].errors))
        self.admin_user.refresh_from_db()
        self.assertEqual(self.admin_user.first_name, '')

    def test_dashboard_simplifies_navigation_without_deleting_records(self):
        Conversation.objects.create(owner=self.farmer)
        today = timezone.localdate()
        WeatherRecord.objects.create(
            owner=self.farmer,
            location='Cauayan, Isabela',
            recorded_on=today,
            temperature=28.5,
            rainfall=4.2,
            notes='Automatically synced from Open-Meteo.',
        )
        Crop.objects.create(
            owner=self.farmer,
            crop_name='Rice',
            planting_date=timezone.localdate() - timedelta(days=10),
            farm_location='Cauayan, Isabela',
        )
        self.client.force_login(self.admin_user)

        with patch('apps.core.gemini.connection_status', return_value={
            'state': 'connected',
            'message': 'Connected',
        }):
            response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Dashboard')
        self.assertContains(response, 'class="container-fluid p-0 admin-dashboard"')
        self.assertContains(response, 'Crop catalog')
        self.assertContains(response, 'Recent system activity')
        self.assertContains(response, 'adminDashboardChartData')
        chart_payload = re.search(
            r'<script id="adminDashboardChartData" type="application/json">(.*?)</script>',
            response.content.decode(),
        )
        self.assertIsNotNone(chart_payload)
        chart_data = json.loads(chart_payload.group(1))
        self.assertIn('users', chart_data)
        self.assertIn('weather', chart_data)
        today_index = chart_data['weather']['labels'].index(today.strftime('%b %d'))
        self.assertEqual(chart_data['weather']['temperature'][today_index], 28.5)
        self.assertEqual(chart_data['weather']['rainfall'][today_index], 4.2)
        self.assertContains(response, reverse('admin_weather'))
        self.assertContains(response, reverse('admin_settings'))
        html = response.content.decode()
        self.assertLess(html.index('/admin/css/base.css'), html.index('/static/css/admin-theme.css'))
        self.assertNotContains(response, 'Groups &amp; Permissions')
        self.assertNotContains(response, 'Crop Guidelines &amp; Settings')
        self.assertNotContains(response, reverse('admin:core_conversation_changelist'))
        self.assertNotContains(response, reverse('admin:core_message_changelist'))
        self.assertEqual(Conversation.objects.filter(owner=self.farmer).count(), 1)
        self.assertEqual(Crop.objects.filter(owner=self.farmer).count(), 1)
