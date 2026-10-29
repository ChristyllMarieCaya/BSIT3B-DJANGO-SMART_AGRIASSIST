from datetime import date
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.models import Conversation, CropDiagnosis, Message
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import UserPreference, WeatherAlert

User = get_user_model()


class AdminPortfolioAndIntegrationTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='super-admin',
            email='admin@example.com',
            password='AdminPassword123!',
        )
        self.farmer = User.objects.create_user(
            username='farmer-john',
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            password='FarmerPassword123!',
        )
        self.pref = UserPreference.objects.create(
            user=self.farmer,
            farm_name='Green Acres Valley',
            farm_location='Benguet Highland',
            latitude=16.4023,
            longitude=120.5960,
            weather_monitoring_enabled=True,
        )
        self.crop = Crop.objects.create(
            owner=self.farmer,
            crop_name='Highland Tomato',
            variety='Diamante Max',
            planting_date=date.today(),
            farm_location='Benguet Highland',
            field_name='North Ridge Plot 2',
            area_sqm=5000,
            status=Crop.Status.ACTIVE,
        )
        self.reminder = ScheduledReminder.objects.create(
            user=self.farmer,
            crop=self.crop,
            title='Inspect Tomato Trellises',
            activity_type=ScheduledReminder.ActivityType.PEST_INSPECTION,
            due_date=date.today(),
            status=ScheduledReminder.Status.PENDING,
        )
        self.diagnosis = CropDiagnosis.objects.create(
            user=self.farmer,
            crop_name='Highland Tomato',
            observed_symptoms='Browning margins on lower leaves',
            possible_disease='Early Blight (Alternaria solani)',
            confidence_level='High',
            confidence_score=0.88,
            treatment_recommendations='Apply certified copper fungicide and remove affected foliage.',
            is_confirmed=True,
        )
        self.client.force_login(self.admin_user)

    def test_portfolio_requires_staff(self):
        unauthed_client = Client()
        url = reverse('admin_user_portfolio', args=[self.farmer.pk])
        resp = unauthed_client.get(url)
        self.assertEqual(resp.status_code, 302)

        regular_client = Client()
        regular_client.force_login(self.farmer)
        resp2 = regular_client.get(url)
        # Non-staff user should be redirected to login
        self.assertEqual(resp2.status_code, 302)

    def test_portfolio_renders_with_real_aggregated_data(self):
        url = reverse('admin_user_portfolio', args=[self.farmer.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Context asserts
        self.assertEqual(resp.context['target_user'], self.farmer)
        self.assertEqual(resp.context['total_crops_count'], 1)
        self.assertEqual(resp.context['active_crops_count'], 1)
        self.assertEqual(resp.context['total_reminders_count'], 1)
        self.assertEqual(resp.context['pending_reminders_count'], 1)
        self.assertEqual(resp.context['total_diagnoses_count'], 1)
        self.assertEqual(resp.context['confirmed_diagnoses_count'], 1)
        self.assertEqual(resp.context['farm_name'], 'Green Acres Valley')
        self.assertEqual(resp.context['farm_location'], 'Benguet Highland')

        # Content asserts
        self.assertContains(resp, 'Highland Tomato')
        self.assertContains(resp, 'Diamante Max')
        self.assertContains(resp, 'Inspect Tomato Trellises')
        self.assertContains(resp, 'Early Blight')
        self.assertContains(resp, 'Green Acres Valley')
        self.assertContains(resp, 'Benguet Highland')
        self.assertRegex(resp.content.decode(), r'EN\s*&bull;\s*Metric\s*\(Celsius\)')
        self.assertNotContains(resp, '{{ preference.measurement_units')
        self.assertNotContains(resp, '{{ target_user.date_joined')
        self.assertNotContains(resp, '{{ target_user.last_login')
        self.assertContains(resp, 'Last active Never')

        # Timeline asserts
        timeline = resp.context['timeline_events']
        self.assertTrue(len(timeline) >= 3)
        timeline_titles = [ev['title'] for ev in timeline]
        self.assertTrue(any('Highland Tomato' in t for t in timeline_titles))
        self.assertTrue(any('Inspect Tomato Trellises' in t for t in timeline_titles))

    def test_portfolio_404_for_nonexistent_user(self):
        url = reverse('admin_user_portfolio', args=[999999])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_portfolio_toggle_account_status(self):
        url = reverse('admin_user_portfolio', args=[self.farmer.pk])
        self.assertTrue(self.farmer.is_active)

        # Deactivate
        resp = self.client.post(url, {'action': 'toggle_status'})
        self.assertEqual(resp.status_code, 302)
        self.farmer.refresh_from_db()
        self.assertFalse(self.farmer.is_active)

        # Reactivate
        resp2 = self.client.post(url, {'action': 'toggle_status'})
        self.assertEqual(resp2.status_code, 302)
        self.farmer.refresh_from_db()
        self.assertTrue(self.farmer.is_active)

    def test_portfolio_cannot_deactivate_self(self):
        url = reverse('admin_user_portfolio', args=[self.admin_user.pk])
        resp = self.client.post(url, {'action': 'toggle_status'})
        self.assertEqual(resp.status_code, 302)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)

    def test_ai_assistant_configuration_page(self):
        self.diagnosis.observed_symptoms = 'Yellowing leaves and small lesions'
        self.diagnosis.save(update_fields=['observed_symptoms'])
        url = reverse('admin_ai_assistant')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'AI Assistant Configuration')
        self.assertContains(resp, 'admin-diagnosis-record')
        self.assertContains(resp, 'Early Blight (Alternaria solani)')
        self.assertContains(resp, 'Yellowing leaves and small lesions')
        self.assertContains(resp, 'Confirmed')
        self.assertIn('active_model', resp.context)
        self.assertIn('total_diagnoses', resp.context)
        self.assertIn('recent_diagnoses', resp.context)

    def test_user_management_changelist_links_to_portfolio(self):
        resp = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertEqual(resp.status_code, 200)
        portfolio_url = reverse('admin_user_portfolio', args=[self.farmer.pk])
        self.assertContains(resp, portfolio_url)
        self.assertContains(resp, 'Portfolio')
