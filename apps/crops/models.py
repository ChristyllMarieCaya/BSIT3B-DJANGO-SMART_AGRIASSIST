from datetime import date
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.crops.growth_engine import calculate_crop_growth, get_crop_profile


class Crop(models.Model):
    """A farmer's registered crop on a specific field, tracked automatically through its growth lifecycle."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active (Growing)'
        HARVESTED = 'harvested', 'Harvested'
        LOST = 'lost', 'Crop Loss / Cancelled'
        PLANNED = 'planned', 'Planned (Not yet sown)'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='registered_crops',
        on_delete=models.CASCADE,
    )
    crop_name = models.CharField(max_length=100, help_text='e.g. Rice, Corn, Tomato, Eggplant')
    variety = models.CharField(max_length=150, blank=True, help_text='Specific crop variety or hybrid, if known')
    planting_date = models.DateField(help_text='Date when seeds were sown or seedlings transplanted')
    farm_location = models.CharField(max_length=255, blank=True, help_text='Farm site or municipality')
    field_name = models.CharField(max_length=150, blank=True, help_text='Field identifier (e.g. North Plot 1)')
    expected_duration_days = models.PositiveIntegerField(
        default=90,
        help_text='Expected days from planting to harvest',
    )
    area_sqm = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Planted area in square meters',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True, help_text='Custom field observations and agronomic notes')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tblregisteredcrop'
        ordering = ['-planting_date', 'crop_name']
        indexes = [
            models.Index(fields=['owner', 'status'], name='crop_owner_status_idx'),
            models.Index(fields=['owner', '-planting_date'], name='crop_owner_planted_idx'),
        ]

    def __str__(self):
        variety_str = f' ({self.variety})' if self.variety else ''
        field_str = f' - {self.field_name}' if self.field_name else ''
        return f'{self.crop_name}{variety_str}{field_str}'

    def save(self, *args, **kwargs):
        # Auto-fill default duration from agronomic profile if not explicitly set
        if not self.expected_duration_days or self.expected_duration_days == 90:
            profile = get_crop_profile(self.crop_name)
            self.expected_duration_days = profile.get('default_duration_days', 90)
        super().save(*args, **kwargs)

    @property
    def growth_data(self):
        """Dynamic growth calculation evaluated against today's date."""
        return calculate_crop_growth(
            crop_name=self.crop_name,
            planting_date=self.planting_date,
            custom_duration=self.expected_duration_days,
            current_date=date.today(),
        )

    @property
    def days_since_planting(self) -> int:
        return (date.today() - self.planting_date).days

    @property
    def current_stage(self):
        return self.growth_data.get('current_stage')

    @property
    def current_stage_name(self) -> str:
        stage = self.current_stage
        return stage['name'] if stage else 'Establishing'

    @property
    def overall_progress(self) -> float:
        return self.growth_data.get('overall_progress_percentage', 0.0)

    @property
    def stage_progress(self) -> float:
        return self.growth_data.get('stage_progress_percentage', 0.0)

    @property
    def estimated_harvest_date(self) -> date:
        return self.growth_data.get('estimated_harvest_date')

    @property
    def days_until_harvest(self) -> int:
        return self.growth_data.get('days_until_harvest', 0)

    @property
    def milestones(self):
        return self.growth_data.get('milestones', [])

    @property
    def recommended_activities(self):
        stage = self.current_stage
        return stage.get('activities', []) if stage else []


class CropGrowthStage(models.Model):
    """Reference growth stages for crop species, used as baseline agronomic data."""

    crop_name = models.CharField(max_length=100, db_index=True)
    stage_name = models.CharField(max_length=150)
    stage_order = models.PositiveSmallIntegerField(default=1)
    start_day = models.PositiveSmallIntegerField(default=0)
    end_day = models.PositiveSmallIntegerField(default=30)
    description = models.TextField(blank=True)
    recommended_care = models.TextField(blank=True)
    water_requirements = models.CharField(max_length=255, blank=True)
    fertilizer_guidance = models.TextField(blank=True)
    weather_vulnerabilities = models.TextField(blank=True)

    class Meta:
        db_table = 'tblcropgrowthstage'
        ordering = ['crop_name', 'stage_order']
        unique_together = ('crop_name', 'stage_order')

    def __str__(self):
        return f'{self.crop_name} - Stage {self.stage_order}: {self.stage_name}'


class ScheduledReminder(models.Model):
    """Automated and manual farming activity reminders tied to crop growth stages and farm care."""

    class ActivityType(models.TextChoices):
        SEEDLING_CARE = 'seedling_care', 'Seedling Care'
        IRRIGATION = 'irrigation', 'Irrigation Check'
        FERTILIZER = 'fertilizer', 'Fertilizer Application'
        PEST_INSPECTION = 'pest_inspection', 'Pest & Disease Inspection'
        GROWTH_MONITORING = 'growth_monitoring', 'Growth Stage Monitoring'
        HARVEST_PREP = 'harvest_prep', 'Harvest Preparation'
        GENERAL = 'general', 'General Field Activity'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        OVERDUE = 'overdue', 'Overdue'
        CANCELLED = 'cancelled', 'Cancelled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='reminders',
        on_delete=models.CASCADE,
    )
    crop = models.ForeignKey(
        Crop,
        related_name='reminders',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=255)
    activity_type = models.CharField(
        max_length=30,
        choices=ActivityType.choices,
        default=ActivityType.GENERAL,
    )
    due_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    is_automated = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tblscheduledreminder'
        ordering = ['due_date', 'status']
        indexes = [
            models.Index(fields=['user', 'status', 'due_date'], name='reminder_user_status_due_idx'),
            models.Index(fields=['crop', 'status'], name='reminder_crop_status_idx'),
        ]

    def __str__(self):
        return f'{self.title} (Due: {self.due_date})'

    @property
    def is_overdue(self) -> bool:
        return self.status == self.Status.PENDING and self.due_date < date.today()
