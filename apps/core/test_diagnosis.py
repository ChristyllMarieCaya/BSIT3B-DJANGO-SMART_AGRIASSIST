from io import BytesIO
from unittest.mock import patch
from PIL import Image

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Conversation, CropDiagnosis, Message
from apps.info.models import Notification

User = get_user_model()


def create_test_image():
    file = BytesIO()
    img = Image.new('RGB', (100, 100), color='green')
    img.save(file, 'JPEG')
    file.seek(0)
    return SimpleUploadedFile('test_leaf.jpg', file.read(), content_type='image/jpeg')


class CropDiagnosisIntegrationTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='diag-farmer1', password='password123')
        self.user2 = User.objects.create_user(username='diag-farmer2', password='password123')

    @patch('apps.core.views.generate_reply')
    def test_image_chat_records_crop_diagnosis(self, mock_generate_reply):
        mock_generate_reply.return_value = (
            "Crop Identification: Rice (Oryza sativa)\n"
            "Visible Symptoms: Elongated grayish-green lesions with dark brown borders on leaf blades.\n"
            "Possible Disease: Rice Blast (Magnaporthe oryzae)\n"
            "Confidence Assessment: High confidence based on typical diamond-shaped spindle lesions.\n"
            "Management & Treatment: Avoid excessive nitrogen fertilizer. Apply balanced potassium.\n"
            "Preventive Measures: Plant resistant varieties and maintain proper hill spacing.\n"
            "Local Expert Advice: Consult municipal agricultural technician to inspect field severity."
        )

        self.client.force_login(self.user1)
        image = create_test_image()

        response = self.client.post(
            reverse('chat'),
            {
                'message': 'What is wrong with my rice leaves?',
                'image': image,
            },
        )
        self.assertEqual(response.status_code, 200)

        # Verify CropDiagnosis record created
        diagnoses = CropDiagnosis.objects.filter(user=self.user1)
        self.assertEqual(diagnoses.count(), 1)

        diag = diagnoses.first()
        self.assertIn('Rice', diag.crop_name)
        self.assertIn('Rice Blast', diag.possible_disease)
        self.assertEqual(diag.confidence_level, 'High')
        self.assertFalse(diag.is_confirmed)
        self.assertTrue(bool(diag.image))

    def test_diagnoses_list_and_detail_views(self):
        diag = CropDiagnosis.objects.create(
            user=self.user1,
            crop_name='Tomato',
            possible_disease='Early Blight',
            confidence_level='Moderate',
            observed_symptoms='Concentric rings on lower leaves',
            treatment_recommendations='Remove infected lower leaves and mulch soil surface.',
        )

        self.client.force_login(self.user1)
        # List view
        res = self.client.get(reverse('diagnoses_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Early Blight')
        self.assertContains(res, 'Tomato')

        # Detail view
        detail_res = self.client.get(reverse('diagnosis_detail', kwargs={'pk': diag.pk}))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, 'Concentric rings')

    def test_diagnosis_access_isolation(self):
        diag = CropDiagnosis.objects.create(
            user=self.user1,
            crop_name='Corn',
            possible_disease='Fall Armyworm Damage',
        )

        self.client.force_login(self.user2)
        response = self.client.get(reverse('diagnosis_detail', kwargs={'pk': diag.pk}))
        self.assertEqual(response.status_code, 404)

    def test_owner_can_delete_diagnosis_without_deleting_shared_upload(self):
        conversation = Conversation.objects.create(owner=self.user1)
        message = Message.objects.create(
            conversation=conversation,
            sender=self.user1,
            image='chat_images/original-upload.jpg',
        )
        diagnosis = CropDiagnosis.objects.create(
            user=self.user1,
            conversation=conversation,
            message=message,
            image=message.image.name,
            crop_name='Tomato',
            possible_disease='Early Blight',
        )
        notification = Notification.objects.create(
            user=self.user1,
            title='AI analysis complete',
            message='Review diagnosis',
            related_url=f'/diagnoses/{diagnosis.pk}/',
        )

        self.client.force_login(self.user1)
        response = self.client.post(reverse('diagnosis_delete', args=[diagnosis.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertFalse(CropDiagnosis.objects.filter(pk=diagnosis.pk).exists())
        self.assertEqual(Message.objects.get(pk=message.pk).image.name, 'chat_images/original-upload.jpg')
        self.assertFalse(Notification.objects.filter(pk=notification.pk).exists())

        refreshed = self.client.get(reverse('diagnoses_list'))
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotContains(refreshed, 'Early Blight')

    def test_user_cannot_delete_another_users_diagnosis(self):
        diagnosis = CropDiagnosis.objects.create(
            user=self.user1,
            image='diagnoses/private.jpg',
            possible_disease='Private Diagnosis',
        )

        self.client.force_login(self.user2)
        response = self.client.post(reverse('diagnosis_delete', args=[diagnosis.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(CropDiagnosis.objects.filter(pk=diagnosis.pk).exists())

    def test_bulk_delete_removes_only_selected_owned_diagnoses(self):
        selected = CropDiagnosis.objects.create(
            user=self.user1,
            image='diagnoses/selected.jpg',
            possible_disease='Selected Diagnosis',
        )
        retained = CropDiagnosis.objects.create(
            user=self.user1,
            image='diagnoses/retained.jpg',
            possible_disease='Retained Diagnosis',
        )
        other_user = CropDiagnosis.objects.create(
            user=self.user2,
            image='diagnoses/other.jpg',
            possible_disease='Other User Diagnosis',
        )

        self.client.force_login(self.user1)
        response = self.client.post(
            reverse('diagnoses_delete'),
            {'diagnosis_ids': [selected.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted_ids'], [selected.pk])
        self.assertFalse(CropDiagnosis.objects.filter(pk=selected.pk).exists())
        self.assertTrue(CropDiagnosis.objects.filter(pk=retained.pk).exists())
        self.assertTrue(CropDiagnosis.objects.filter(pk=other_user.pk).exists())
