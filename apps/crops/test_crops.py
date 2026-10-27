from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.crops.growth_engine import calculate_crop_growth, get_crop_profile
from apps.crops.models import Crop, CropGrowthStage, ScheduledReminder

User = get_user_model()


class CropGrowthCalculationTests(TestCase):
    def test_crop_stage_calculation_for_rice(self):
        planting_date = date.today() - timedelta(days=35)
        growth = calculate_crop_growth('Rice', planting_date, custom_duration=115)

        self.assertEqual(growth['days_since_planting'], 35)
        self.assertEqual(growth['total_duration_days'], 115)
        self.assertIsNotNone(growth['current_stage'])
        self.assertEqual(growth['current_stage']['name'], 'Tillering & Vegetative Growth')
        self.assertEqual(growth['days_until_harvest'], 115 - 35)
        self.assertTrue(0 < growth['overall_progress_percentage'] < 100)
        self.assertTrue(len(growth['milestones']) >= 4)

    def test_crop_stage_calculation_for_tomato(self):
        planting_date = date.today() - timedelta(days=50)
        growth = calculate_crop_growth('Tomato', planting_date, custom_duration=95)

        self.assertEqual(growth['days_since_planting'], 50)
        self.assertEqual(growth['current_stage']['name'], 'Flowering & Fruit Setting')
        self.assertEqual(growth['days_until_harvest'], 45)

    def test_crop_harvest_readiness_calculation(self):
        planting_date = date.today() - timedelta(days=120)
        growth = calculate_crop_growth('Rice', planting_date, custom_duration=115)

        self.assertEqual(growth['days_since_planting'], 120)
        self.assertEqual(growth['days_until_harvest'], 0)
        self.assertEqual(growth['overall_progress_percentage'], 100.0)


class CropModelAndIsolationTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='farmer1', password='password123')
        self.user2 = User.objects.create_user(username='farmer2', password='password123')

        self.crop1 = Crop.objects.create(
            owner=self.user1,
            crop_name='Rice',
            variety='NSIC Rc 222',
            planting_date=date.today() - timedelta(days=20),
            field_name='North Paddy',
            expected_duration_days=115,
        )

    def test_crop_properties(self):
        self.assertEqual(self.crop1.days_since_planting, 20)
        self.assertEqual(self.crop1.current_stage_name, 'Germination & Seedling')
        self.assertEqual(self.crop1.days_until_harvest, 95)
        self.assertEqual(self.crop1.estimated_harvest_date, date.today() - timedelta(days=20) + timedelta(days=115))

    def test_user_cannot_access_other_users_crop(self):
        self.client.force_login(self.user2)
        response = self.client.get(reverse('crops:crop_detail', kwargs={'pk': self.crop1.pk}))
        self.assertEqual(response.status_code, 404)

    def test_crop_registration_view_generates_reminders(self):
        self.client.force_login(self.user1)
        response = self.client.post(reverse('crops:crop_add'), {
            'crop_name': 'Tomato',
            'variety': 'Diamante Max',
            'planting_date': date.today().isoformat(),
            'field_name': 'Greenhouse 1',
            'expected_duration_days': '95',
            'area_sqm': '500',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        new_crop = Crop.objects.get(owner=self.user1, crop_name='Tomato')
        self.assertEqual(new_crop.expected_duration_days, 95)

        reminders = ScheduledReminder.objects.filter(crop=new_crop)
        self.assertTrue(reminders.exists())
        self.assertTrue(reminders.filter(activity_type=ScheduledReminder.ActivityType.SEEDLING_CARE).exists())
        self.assertTrue(reminders.filter(activity_type=ScheduledReminder.ActivityType.HARVEST_PREP).exists())

    def test_toggle_reminder_status(self):
        reminder = ScheduledReminder.objects.create(
            user=self.user1,
            crop=self.crop1,
            title='Check irrigation water depth',
            due_date=date.today(),
            status=ScheduledReminder.Status.PENDING,
        )

        self.client.force_login(self.user1)
        response = self.client.post(reverse('crops:toggle_reminder', kwargs={'pk': reminder.pk}))
        self.assertEqual(response.status_code, 302)

        reminder.refresh_from_db()
        self.assertEqual(reminder.status, ScheduledReminder.Status.COMPLETED)
        self.assertIsNotNone(reminder.completed_at)

    def test_stage_preview_api(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse('crops:stage_preview_api'), {
            'crop_name': 'Corn (Maize)',
            'planting_date': '2026-10-01',
            'duration': '105',
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['crop_name'], 'Corn (Maize)')
        self.assertEqual(data['total_duration_days'], 105)
        self.assertTrue(len(data['milestones']) >= 4)
