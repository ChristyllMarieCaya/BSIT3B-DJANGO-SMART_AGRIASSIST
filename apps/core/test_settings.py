"""Automated tests for user preferences, farm profile, AI and weather settings."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.info.models import Notification, UserPreference


class SettingsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testfarmer',
            password='Password123!',
            email='farmer@example.com',
            first_name='Juan',
            last_name='Dela Cruz',
        )
        self.client = Client()

    def test_settings_page_requires_login(self):
        resp = self.client.get(reverse('settings'))
        self.assertEqual(resp.status_code, 302)

    def test_settings_page_renders_for_logged_in_user(self):
        self.client.login(username='testfarmer', password='Password123!')
        resp = self.client.get(reverse('settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'settings.html')
        self.assertIn('pref', resp.context)

    def test_settings_save_updates_farm_and_gps_profile(self):
        self.client.login(username='testfarmer', password='Password123!')
        data = {
            'farm_name': 'Green Horizons Farm',
            'farm_location': 'Muñoz, Nueva Ecija',
            'latitude': '15.7139',
            'longitude': '120.9061',
            'preferred_language': 'en',
            'timezone': 'Asia/Manila',
            'measurement_units': 'metric',
            'temperature_unit': 'celsius',
        }
        resp = self.client.post(reverse('settings_save'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.farm_name, 'Green Horizons Farm')
        self.assertEqual(pref.farm_location, 'Muñoz, Nueva Ecija')
        self.assertAlmostEqual(float(pref.latitude), 15.7139, places=3)
        self.assertAlmostEqual(float(pref.longitude), 120.9061, places=3)

    def test_settings_save_updates_ai_and_weather_thresholds(self):
        self.client.login(username='testfarmer', password='Password123!')
        data = {
            'ai_response_language': 'fil',
            'ai_response_detail': 'detailed',
            'enable_conversation_history': 'on',
            'weather_monitoring_enabled': 'on',
            'weather_alerts_enabled': 'on',
            'weather_alert_min_severity': 'warning',
            'weather_update_frequency_hours': '3',
            'rain_alert_threshold_mm': '35.5',
            'wind_alert_threshold_kmh': '55.0',
            'temp_high_threshold_c': '37.0',
            'temp_low_threshold_c': '16.0',
            'channel_in_app': 'on',
            'channel_browser': 'on',
            'channel_email': 'on',
            'channel_sms': 'false',
            'quiet_hours_enabled': 'on',
            'quiet_hours_start': '21:00',
            'quiet_hours_end': '05:00',
            'auto_crop_reminders_enabled': 'on',
            'reminder_frequency': 'daily',
            'notify_growth_stages': 'on',
            'notify_fertilizer_irrigation': 'on',
            'notify_pest_inspection': 'on',
            'notify_harvest_estimation': 'on',
            'application_notices_enabled': 'on',
        }
        resp = self.client.post(reverse('settings_save'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.ai_response_language, 'fil')
        self.assertEqual(pref.ai_response_detail, 'detailed')
        self.assertTrue(pref.enable_conversation_history)
        self.assertTrue(pref.weather_monitoring_enabled)
        self.assertEqual(pref.weather_alert_min_severity, 'warning')
        self.assertEqual(pref.weather_update_frequency_hours, 3)
        self.assertEqual(pref.rain_alert_threshold_mm, 35.5)
        self.assertEqual(pref.wind_alert_threshold_kmh, 55.0)
        self.assertEqual(pref.temp_high_threshold_c, 37.0)
        self.assertEqual(pref.temp_low_threshold_c, 16.0)
        self.assertTrue(pref.channel_in_app)
        self.assertTrue(pref.channel_browser)
        self.assertTrue(pref.channel_email)
        self.assertFalse(pref.channel_sms)
        self.assertTrue(pref.quiet_hours_enabled)
        self.assertEqual(pref.quiet_hours_start, '21:00')
        self.assertEqual(pref.quiet_hours_end, '05:00')
        self.assertTrue(pref.auto_crop_reminders_enabled)

        # Check notice generated
        notice = Notification.objects.filter(user=self.user, title='Settings updated').first()
        self.assertIsNotNone(notice)

    def test_settings_save_updates_user_profile(self):
        self.client.login(username='testfarmer', password='Password123!')
        data = {
            'first_name': 'Maria',
            'last_name': 'Santos',
            'email': 'maria.santos@example.com',
        }
        resp = self.client.post(reverse('settings_save'), data)
        self.assertEqual(resp.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Maria')
        self.assertEqual(self.user.last_name, 'Santos')
        self.assertEqual(self.user.email, 'maria.santos@example.com')
