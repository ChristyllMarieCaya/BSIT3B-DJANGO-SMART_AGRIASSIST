from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from apps.core.automation import run_all_agricultural_automations
from apps.core.weather import evaluate_weather_risks
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import Notification, UserPreference, WeatherAlert

User = get_user_model()


class WeatherRiskThresholdTests(TestCase):
    def test_heavy_rainfall_risk_detection(self):
        weather_data = {
            'available': True,
            'source': 'Mock Weather',
            'current': {
                'temperature': 28.0,
                'wind_speed': 15.0,
                'humidity': 85,
                'rain_1h': 35.0,
                'condition': 'Rain',
                'description': 'Heavy downpour',
            },
            'forecast': [],
        }
        alerts = evaluate_weather_risks(weather_data, 'North Farm', rain_threshold_mm=25.0)
        self.assertTrue(any(a['alert_type'] == 'heavy_rain' for a in alerts))
        heavy = next(a for a in alerts if a['alert_type'] == 'heavy_rain')
        self.assertIn('drainage', heavy['precautionary_actions'].lower())

    def test_strong_winds_risk_detection(self):
        weather_data = {
            'available': True,
            'source': 'Mock Weather',
            'current': {
                'temperature': 27.0,
                'wind_speed': 55.0,
                'humidity': 70,
                'rain_1h': 0.0,
                'condition': 'Windy',
                'description': 'High wind gusts',
            },
            'forecast': [],
        }
        alerts = evaluate_weather_risks(weather_data, 'North Farm', wind_threshold_kmh=40.0)
        self.assertTrue(any(a['alert_type'] == 'strong_winds' for a in alerts))

    def test_extreme_heat_risk_detection(self):
        weather_data = {
            'available': True,
            'source': 'Mock Weather',
            'current': {
                'temperature': 37.5,
                'wind_speed': 10.0,
                'humidity': 60,
                'rain_1h': 0.0,
                'condition': 'Clear',
                'description': 'Blistering sunshine',
            },
            'forecast': [],
        }
        alerts = evaluate_weather_risks(weather_data, 'Valley Farm', temp_high_threshold_c=35.0)
        self.assertTrue(any(a['alert_type'] == 'extreme_heat' for a in alerts))
        heat = next(a for a in alerts if a['alert_type'] == 'extreme_heat')
        self.assertIn('irrigation', heat['precautionary_actions'].lower())


class AgriculturalAutomationCycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='auto-farmer',
            email='farmer@example.com',
            password='password123',
        )
        self.pref, _ = UserPreference.objects.get_or_create(
            user=self.user,
            farm_name='Test Plot',
            farm_location='Cauayan, Isabela',
            weather_monitoring_enabled=True,
            weather_alerts_enabled=True,
            auto_crop_reminders_enabled=True,
            channel_in_app=True,
            channel_email=True,
            rain_alert_threshold_mm=20.0,
        )

        self.crop = Crop.objects.create(
            owner=self.user,
            crop_name='Rice',
            planting_date=date.today() - timedelta(days=21),
            expected_duration_days=115,
        )

        # Pending overdue reminder
        self.past_reminder = ScheduledReminder.objects.create(
            user=self.user,
            crop=self.crop,
            title='Check nursery bed',
            due_date=date.today() - timedelta(days=2),
            status=ScheduledReminder.Status.PENDING,
        )

    @patch('apps.core.automation.get_weather')
    def test_automation_cycle_creates_alerts_and_updates_reminders(self, mock_weather):
        mock_weather.return_value = {
            'available': True,
            'source': 'Mock OpenWeather',
            'current': {
                'temperature': 30.0,
                'wind_speed': 12.0,
                'humidity': 88,
                'rain_1h': 28.0,  # exceeds 20.0 mm threshold
                'condition': 'Rain',
                'description': 'Heavy monsoon downpour',
            },
            'forecast': [],
        }

        result = run_all_agricultural_automations(target_user=self.user)
        self.assertEqual(result.users_processed, 1)
        self.assertTrue(result.weather_alerts_generated >= 1)
        self.assertTrue(result.overdue_reminders_flagged >= 1)

        # Check alert saved in DB
        self.assertTrue(WeatherAlert.objects.filter(user=self.user).exists())

        # Check in-app notification delivered
        self.assertTrue(
            Notification.objects.filter(
                user=self.user,
                category=Notification.Category.WEATHER_ALERT,
            ).exists()
        )

        # Check email sent
        self.assertTrue(len(mail.outbox) >= 1)
        self.assertIn('Heavy Rain', mail.outbox[0].subject)

        # Check overdue reminder was flagged
        self.past_reminder.refresh_from_db()
        self.assertEqual(self.past_reminder.status, ScheduledReminder.Status.OVERDUE)

    @patch('apps.core.automation.get_weather')
    def test_duplicate_alert_prevention(self, mock_weather):
        mock_weather.return_value = {
            'available': True,
            'source': 'Mock OpenWeather',
            'current': {
                'temperature': 30.0,
                'wind_speed': 12.0,
                'humidity': 88,
                'rain_1h': 30.0,
                'condition': 'Rain',
                'description': 'Continuous rain',
            },
            'forecast': [],
        }

        # First run creates alert
        res1 = run_all_agricultural_automations(target_user=self.user)
        initial_alerts_count = WeatherAlert.objects.filter(user=self.user).count()

        # Second run should skip duplicate
        res2 = run_all_agricultural_automations(target_user=self.user)
        self.assertEqual(res2.weather_alerts_generated, 0)
        self.assertTrue(res2.duplicate_alerts_skipped >= 1)
        self.assertEqual(WeatherAlert.objects.filter(user=self.user).count(), initial_alerts_count)

    def test_management_command_execution(self):
        out = StringIO()
        call_command('run_agricultural_automations', '--once', stdout=out)
        output = out.getvalue()
        self.assertIn('SMART Agricultural Automation Engine initialized', output)
        self.assertIn('Completed in', output)
