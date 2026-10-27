from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.info.models import CropGuideline, Notification, UserPreference, VisualIdentificationLog


class NotificationSignalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='signal-farmer', password='secret1234')

    def test_crop_registration_creates_one_preference_aware_care_notification(self):
        crop = CropGuideline.objects.create(
            owner=self.user,
            crop_name='Rice',
            sow_date='2026-10-01',
            harvest_date='2027-02-01',
        )
        crop.notes = 'Updated notes'
        crop.save()

        notifications = Notification.objects.filter(
            user=self.user,
            category=Notification.Category.CROP_CARE,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn('Rice', notifications.get().title)

    def test_field_observation_creates_advisory_without_claiming_confirmation(self):
        VisualIdentificationLog.objects.create(
            owner=self.user,
            field_name='North field',
            inspected_on='2026-10-25',
            findings='Spots observed on several leaves',
        )

        notification = Notification.objects.get(user=self.user)
        self.assertEqual(notification.category, Notification.Category.PEST_DISEASE)
        self.assertIn('confirm the findings', notification.message)

    def test_disabled_category_preference_suppresses_new_event_notification(self):
        UserPreference.objects.create(
            user=self.user,
            crop_care_reminders_enabled=False,
        )
        CropGuideline.objects.create(
            owner=self.user,
            crop_name='Maize',
            sow_date='2026-10-01',
        )

        self.assertFalse(Notification.objects.filter(user=self.user).exists())
