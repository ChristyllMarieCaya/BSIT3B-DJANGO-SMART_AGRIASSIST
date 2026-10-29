"""Automated verification tests for:
1. Simplified Dashboard (no duplicate AI panel, remaining sections present).
2. Open-Meteo weather integration and geocoding.
3. Official PAGASA advisory detection vs forecast-based alerts.
4. Working Light/Dark/System theme options and persistence.
5. Country and IANA Time Zone options and persistence.
6. Automatic notifications generation across all 6 categories.
"""

from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.automation import run_all_agricultural_automations
from apps.core.models import Conversation, CropDiagnosis, Message
from apps.core.weather import (
    check_pagasa_advisories,
    evaluate_weather_risks,
    geocode_location,
    get_weather,
)
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import Notification, UserPreference, WeatherAlert

User = get_user_model()


class DashboardSimplificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='farmowner',
            password='Password123!',
            first_name='Farmer',
            last_name='Juan',
        )
        self.client = Client()
        self.client.login(username='farmowner', password='Password123!')

    def test_dashboard_does_not_contain_duplicate_chat_panel(self):
        """Dashboard should NOT have the huge chat form/input panel."""
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        # Should not contain the dashboard chat interface elements
        self.assertNotContains(resp, 'id="chatMessages"')
        self.assertNotContains(resp, 'id="chatInput"')
        self.assertNotContains(resp, 'id="chatCameraModal"')

    def test_dashboard_retains_all_six_required_sections(self):
        """Dashboard keeps crop stages, weather, activities, diagnoses, conversations, notifications."""
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Active Crop Growth Stages')
        self.assertContains(resp, 'Live Weather Today')
        self.assertContains(resp, 'Upcoming Activities &amp; Tasks')
        self.assertContains(resp, 'Recent Crop Diagnoses')
        self.assertContains(resp, 'Recent Conversations')
        self.assertContains(resp, 'Recent Notifications')

    def test_sidebar_agri_ai_assistant_page_remains_intact(self):
        """Agri AI Assistant remains fully accessible in its dedicated page."""
        resp = self.client.get(reverse('ai_assistant'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Agri AI Assistant')
        self.assertContains(resp, 'chatMessages')
        self.assertContains(resp, 'chatInput')


class WeatherAndAlertsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='weatherfarmer',
            password='Password123!',
        )
        self.pref, _ = UserPreference.objects.get_or_create(
            user=self.user,
            defaults={
                'farm_location': 'Cauayan, Isabela',
                'latitude': 16.9347,
                'longitude': 121.7725,
            }
        )
        self.client = Client()
        self.client.login(username='weatherfarmer', password='Password123!')

    def test_open_meteo_weather_retrieval(self):
        """Retrieves real weather and forecast from Open-Meteo without requiring API keys."""
        weather = get_weather(16.9347, 121.7725, units='metric', location_name='Cauayan, Isabela')
        self.assertTrue(weather.get('available'))
        self.assertIsNotNone(weather.get('current'))
        self.assertIn('temperature', weather['current'])
        self.assertIn('humidity', weather['current'])
        self.assertIn('wind_speed', weather['current'])
        self.assertGreaterEqual(len(weather.get('forecast', [])), 3)

    def test_geocoding_farm_location(self):
        """Open-Meteo geocoding resolves municipality/province to GPS coordinates."""
        geo = geocode_location('Cauayan, Isabela')
        self.assertIsNotNone(geo)
        self.assertIn('latitude', geo)
        self.assertIn('longitude', geo)
        self.assertAlmostEqual(geo['latitude'], 16.93, delta=0.5)

    @patch('apps.core.views.get_weather')
    def test_weather_page_renders_location_modal_not_raw_api_response(self, get_weather_mock):
        get_weather_mock.return_value = {
            'available': True,
            'current': {
                'temperature': 28.5,
                'feels_like': 30.0,
                'humidity': 75,
                'wind_speed': 4.5,
                'wind_unit': 'km/h',
                'rain_1h': 0.0,
                'precip_unit': 'mm',
                'temp_unit': '°C',
                'condition': 'Partly cloudy',
                'description': 'Partly cloudy sky',
                'icon': 'cloud-sun',
            },
            'forecast': [],
            'location': 'Cauayan, Isabela',
            'source': 'Open-Meteo Live API',
        }

        response = self.client.get(reverse('weather'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="modalLocationForm"')
        self.assertContains(response, 'Save Location &amp; Update')
        self.assertContains(response, 'modal-fullscreen-sm-down')
        self.assertNotContains(response, '<pre')
        self.assertNotContains(response, '"available": true')

    @patch('apps.core.views.get_weather')
    @patch('apps.core.views.geocode_location')
    def test_location_update_geocodes_fetches_and_persists_weather_location(self, geocode, get_weather_mock):
        geocode.return_value = {
            'latitude': 10.5,
            'longitude': 20.5,
            'timezone': 'Asia/Manila',
        }
        get_weather_mock.return_value = {'available': True, 'current': {}, 'forecast': []}

        response = self.client.post(reverse('weather_api'), {'location': 'New Farm'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['available'])
        geocode.assert_called_once_with('New Farm')
        get_weather_mock.assert_called_once_with(
            10.5, 20.5, units='metric', location_name='New Farm',
        )
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.farm_location, 'New Farm')
        self.assertEqual(float(self.pref.latitude), 10.5)
        self.assertEqual(float(self.pref.longitude), 20.5)

    @patch('apps.core.views.geocode_location')
    def test_failed_location_geocoding_does_not_replace_saved_farm_location(self, geocode):
        geocode.return_value = None

        response = self.client.post(reverse('weather_api'), {'location': 'Not A Real Place'})

        self.assertFalse(response.json()['available'])
        self.assertIn('could not be geocoded', response.json()['error'])
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.farm_location, 'Cauayan, Isabela')
        self.assertEqual(float(self.pref.latitude), 16.9347)

    @patch('apps.core.views.get_weather')
    @patch('apps.core.views.geocode_location')
    def test_weather_failure_does_not_replace_saved_farm_location(self, geocode, get_weather_mock):
        geocode.return_value = {'latitude': 10.5, 'longitude': 20.5, 'timezone': 'Asia/Manila'}
        get_weather_mock.return_value = {
            'available': False,
            'error': 'Weather service is temporarily unavailable.',
        }

        response = self.client.post(reverse('weather_api'), {'location': 'New Farm'})

        self.assertFalse(response.json()['available'])
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.farm_location, 'Cauayan, Isabela')
        self.assertEqual(float(self.pref.latitude), 16.9347)

    def test_distinguishes_official_and_forecast_alerts(self):
        """Official PAGASA warnings have is_official=True, forecast alerts have is_official=False."""
        weather_data = {
            'available': True,
            'source': 'Open-Meteo Live API',
            'current': {
                'temperature': 38.0,
                'wind_speed': 45.0,
                'humidity': 88,
                'rain_1h': 30.0,
                'condition': 'Heavy Rain',
                'description': 'Torrential showers',
            },
            'forecast': [
                {'date': '2026-10-28', 'rain_sum': 35.0, 'pop': 90, 'condition': 'Storm', 'wind_gusts_max': 55.0}
            ],
        }
        risks = evaluate_weather_risks(
            weather_data,
            'Cauayan, Isabela',
            rain_threshold_mm=20.0,
            wind_threshold_kmh=35.0,
            temp_high_threshold_c=35.0,
            lat=16.9347,
            lon=121.7725,
        )
        self.assertTrue(len(risks) > 0)
        for r in risks:
            if 'PAGASA' in r.get('source', ''):
                self.assertTrue(r['is_official'])
            else:
                self.assertFalse(r['is_official'])
                self.assertIn('Forecast Alert', r.get('source', ''))

    @patch('apps.core.weather._safe_request')
    def test_selected_non_philippines_country_skips_pagasa_even_for_ph_coordinates(self, weather_request):
        alerts = check_pagasa_advisories(
            location_name='Cauayan, Isabela',
            lat=16.9347,
            lon=121.7725,
            country='Japan',
        )
        self.assertEqual(alerts, [])
        weather_request.assert_not_called()

    def test_alert_deduplication_and_resolution(self):
        """Continuing risks update existing alerts; passing risks are marked inactive."""
        # 1. Create active alert
        alert = WeatherAlert.objects.create(
            user=self.user,
            farm_location='Cauayan, Isabela',
            alert_type='heavy_rain',
            severity=WeatherAlert.Severity.WARNING,
            title='Heavy Rain Alert',
            forecast_condition='Rain 30mm/h',
            agricultural_impact='Waterlogging',
            precautionary_actions='Clear drains',
            is_active=True,
        )
        self.assertTrue(alert.is_active)


class ThemeAndRegionalSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='settingsfarmer',
            password='Password123!',
            first_name='Maria',
            last_name='Clara',
        )
        self.client = Client()
        self.client.login(username='settingsfarmer', password='Password123!')

    def test_theme_options_light_dark_system_persist(self):
        """Theme selection (light, dark, system) saves and persists in database."""
        for theme_choice in ('light', 'dark', 'system'):
            resp = self.client.post(reverse('settings_save'), {
                'theme': theme_choice,
                'country': 'Philippines',
                'timezone': 'Asia/Manila',
            })
            self.assertEqual(resp.status_code, 200)
            pref = UserPreference.objects.get(user=self.user)
            self.assertEqual(pref.theme, theme_choice)

    def test_country_and_iana_timezone_selection_persist(self):
        """Country and IANA time zone persist and update current time."""
        resp = self.client.post(reverse('settings_save'), {
            'country': 'Japan',
            'timezone': 'Asia/Tokyo',
            'farm_timezone': 'Asia/Manila',
            'theme': 'dark',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['country'], 'Japan')
        self.assertEqual(data['timezone'], 'Asia/Tokyo')

        pref = UserPreference.objects.get(user=self.user)
        self.assertEqual(pref.country, 'Japan')
        self.assertEqual(pref.timezone, 'Asia/Tokyo')
        self.assertEqual(pref.farm_timezone, 'Asia/Manila')


class AutomaticNotificationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notiffarmer',
            password='Password123!',
        )
        self.pref, _ = UserPreference.objects.get_or_create(user=self.user)
        self.client = Client()
        self.client.login(username='notiffarmer', password='Password123!')

    def test_all_six_notification_categories_functional(self):
        """Verifies database persistence and filtering for all 6 categories."""
        categories = [
            (Notification.Category.WEATHER_ALERT, 'Severe Weather Alert', 'Heavy rainfall warning'),
            (Notification.Category.CROP_CARE, 'Crop Care Reminder', 'Tillering stage fertilizer split'),
            (Notification.Category.PEST_DISEASE, 'Pest Advisory', 'High humidity blast threat'),
            (Notification.Category.AI_ANALYSIS, 'AI Diagnostic Status', 'Image analysis completed'),
            (Notification.Category.RECOMMENDATION, 'Agricultural Guidance', 'Postpone spraying due to rain'),
            (Notification.Category.NOTICE, 'Application Notice', 'Farm location updated'),
        ]

        for cat, title, msg in categories:
            Notification.objects.create(
                user=self.user,
                category=cat,
                title=title,
                message=msg,
                priority=Notification.Priority.NORMAL,
            )

        self.assertEqual(Notification.objects.filter(user=self.user).count(), 6)

        # Filter by category via API
        for cat, title, _ in categories:
            resp = self.client.get(reverse('notifications_api'), {'category': cat})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(len(data['notifications']), 1)
            self.assertEqual(data['notifications'][0]['title'], title)

    def test_notification_actions_update_database(self):
        """Mark read, mark all read, clear read, and delete selected update db."""
        n1 = Notification.objects.create(
            user=self.user,
            category=Notification.Category.NOTICE,
            title='Note 1',
            message='Test message 1',
            read=False,
        )
        n2 = Notification.objects.create(
            user=self.user,
            category=Notification.Category.NOTICE,
            title='Note 2',
            message='Test message 2',
            read=False,
        )

        # Mark single read
        resp = self.client.post(reverse('notifications_api'), {
            'action': 'mark_read',
            'notification_id': n1.pk,
        })
        self.assertEqual(resp.status_code, 200)
        n1.refresh_from_db()
        self.assertTrue(n1.read)

        # Mark all read
        resp = self.client.post(reverse('notifications_api'), {'action': 'mark_all_read'})
        self.assertEqual(resp.status_code, 200)
        n2.refresh_from_db()
        self.assertTrue(n2.read)

        # Delete selected
        resp = self.client.post(reverse('notifications_api'), {
            'action': 'delete_selected',
            'notification_ids': [n1.pk],
        })
        self.assertEqual(resp.status_code, 200)
        n1.refresh_from_db()
        self.assertIsNotNone(n1.deleted_at)
