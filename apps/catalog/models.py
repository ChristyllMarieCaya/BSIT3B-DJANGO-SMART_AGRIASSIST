"""Read-only agricultural crop catalog.

Entries are reference data: farmers can browse and search them but cannot
create, edit, or delete official catalog records.
"""

from django.db import models


class CropCatalog(models.Model):
    """A single crop entry in the read-only agricultural catalog."""

    class Category(models.TextChoices):
        CEREALS = 'cereals', 'Rice and cereals'
        ROOT_TUBERS = 'root_tubers', 'Root crops and tubers'
        VEGETABLES = 'vegetables', 'Vegetables'
        FRUITS = 'fruits', 'Fruits'
        LEGUMES = 'legumes', 'Legumes and pulses'
        COMMERCIAL = 'commercial', 'Commercial and industrial crops'
        HERBS_SPICES = 'herbs_spices', 'Herbs and spices'
        FORAGE = 'forage', 'Forage crops'

    common_name = models.CharField(max_length=100, unique=True, db_index=True)
    scientific_name = models.CharField(max_length=150, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    description = models.TextField(blank=True)
    climate = models.TextField(blank=True, help_text='Suitable climate and growing conditions.')
    soil_requirements = models.TextField(blank=True, help_text='Soil type and preparation guidance.')
    planting_guidance = models.TextField(blank=True, help_text='Planting and propagation guidance.')
    watering = models.TextField(blank=True, help_text='Watering recommendations.')
    fertilizer = models.TextField(blank=True, help_text='Fertilizer recommendations.')
    pests_diseases = models.TextField(blank=True, help_text='Common pests and diseases.')
    prevention_treatment = models.TextField(blank=True, help_text='Prevention and treatment guidance.')
    growth_stages = models.TextField(blank=True, help_text='Key growth stages.')
    harvesting = models.TextField(blank=True, help_text='Harvesting and post-harvest recommendations.')
    reference_photo_url = models.URLField(null=True, blank=True, help_text='Reference photo URL (external source).')
    source_url = models.URLField(null=True, blank=True, help_text='Credible source for this crop information.')
    is_active = models.BooleanField(default=True, help_text='Whether this crop is visible in the catalog.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tblcropcatalog'
        ordering = ['category', 'common_name']
        indexes = [
            models.Index(fields=['category', 'is_active'], name='cropcatalog_category_idx'),
            models.Index(fields=['common_name'], name='cropcatalog_name_idx'),
        ]

    def __str__(self):
        return self.common_name
