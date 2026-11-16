from django import forms

from .models import CropCatalog


class CropCatalogAdminForm(forms.ModelForm):
    class Meta:
        model = CropCatalog
        fields = (
            'common_name',
            'scientific_name',
            'category',
            'description',
            'climate',
            'soil_requirements',
            'planting_guidance',
            'watering',
            'fertilizer',
            'pests_diseases',
            'prevention_treatment',
            'growth_stages',
            'harvesting',
            'reference_photo_url',
            'source_url',
            'reference_photo',
            'is_active',
        )
