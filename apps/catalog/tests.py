from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.admin import CropCatalogAdmin
from apps.catalog.models import CropCatalog
from apps.crops.models import Crop


class CropCatalogAdminActionsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = TemporaryDirectory()
        cls._override_media = override_settings(MEDIA_ROOT=cls.media_dir.name)
        cls._override_media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override_media.disable()
        cls.media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            username='catalog-admin',
            password='test-password',
            is_staff=True,
        )
        permissions = Permission.objects.filter(
            content_type__app_label='catalog',
            codename__in=('view_cropcatalog', 'change_cropcatalog', 'delete_cropcatalog'),
        )
        self.admin_user.user_permissions.add(*permissions)
        self.client.force_login(self.admin_user)
        self.crop = CropCatalog.objects.create(
            common_name='Test maize',
            scientific_name='Zea mays',
            category=CropCatalog.Category.CEREALS,
            description='Original description',
        )

    @staticmethod
    def image_upload(name='maize.png'):
        image_bytes = BytesIO()
        Image.new('RGB', (2, 2), color='green').save(image_bytes, format='PNG')
        return SimpleUploadedFile(name, image_bytes.getvalue(), content_type='image/png')

    def test_changelist_places_actions_after_active_column(self):
        response = self.client.get(reverse('admin:catalog_cropcatalog_changelist'))
        self.assertEqual(response.status_code, 200)

        columns = list(CropCatalogAdmin.list_display)
        self.assertLess(columns.index('is_active'), columns.index('display_actions'))
        self.assertContains(response, 'data-crop-edit-url=')
        self.assertContains(response, 'data-crop-delete-url=')

    def test_edit_endpoint_saves_crop_details_and_uploaded_photo(self):
        response = self.client.post(
            reverse('admin:catalog_cropcatalog_edit_crop', args=(self.crop.pk,)),
            {
                'common_name': 'Updated maize',
                'scientific_name': 'Zea mays updated',
                'category': CropCatalog.Category.VEGETABLES,
                'description': 'Updated description',
                'climate': 'Warm climate',
                'soil_requirements': 'Well drained',
                'planting_guidance': 'Plant in rows',
                'watering': 'Water regularly',
                'fertilizer': 'Apply compost',
                'pests_diseases': 'Watch for borers',
                'prevention_treatment': 'Rotate crops',
                'growth_stages': 'Emergence, growth, maturity',
                'harvesting': 'Harvest when mature',
                'reference_photo_url': '',
                'source_url': '',
                'is_active': 'on',
                'reference_photo': self.image_upload(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.crop.refresh_from_db()
        self.assertEqual(self.crop.common_name, 'Updated maize')
        self.assertEqual(self.crop.description, 'Updated description')
        self.assertEqual(self.crop.climate, 'Warm climate')
        self.assertTrue(self.crop.reference_photo.name.startswith('crop_catalog/'))
        self.assertEqual(self.crop.photo_url, self.crop.reference_photo.url)

    def test_invalid_edit_returns_form_errors_without_changing_crop(self):
        response = self.client.post(
            reverse('admin:catalog_cropcatalog_edit_crop', args=(self.crop.pk,)),
            {'common_name': '', 'category': 'invalid'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('form_html', response.json())
        self.crop.refresh_from_db()
        self.assertEqual(self.crop.common_name, 'Test maize')

    def test_delete_preserves_farmer_crop_records(self):
        farmer = get_user_model().objects.create_user(
            username='catalog-farmer',
            password='test-password',
        )
        farmer_crop = Crop.objects.create(
            owner=farmer,
            crop_name=self.crop.common_name,
            planting_date=date(2025, 1, 1),
        )

        response = self.client.post(
            reverse('admin:catalog_cropcatalog_delete_crop', args=(self.crop.pk,)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CropCatalog.objects.filter(pk=self.crop.pk).exists())
        self.assertTrue(Crop.objects.filter(pk=farmer_crop.pk).exists())

    def test_farmer_catalog_displays_uploaded_photo_in_list_and_quick_facts(self):
        self.crop.reference_photo.save('maize.png', self.image_upload(), save=True)

        list_response = self.client.get(reverse('catalog:catalog_list'))
        detail_response = self.client.get(reverse('catalog:catalog_detail', args=(self.crop.pk,)))

        self.assertContains(list_response, self.crop.reference_photo.url)
        self.assertContains(detail_response, self.crop.reference_photo.url)
        self.assertNotContains(detail_response, 'No reference photo available')
