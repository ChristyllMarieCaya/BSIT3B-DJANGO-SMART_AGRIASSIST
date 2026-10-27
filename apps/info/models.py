"""Defines farm-owned crop plans, scouting logs, weather measurements,
user preferences, notifications, and automated weather alerts."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class UserPreference(models.Model):
    """Persistent per-user settings for farm profile, weather, notifications, AI, and appearance."""

    class TemperatureUnit(models.TextChoices):
        CELSIUS = 'celsius', 'Celsius'
        FAHRENHEIT = 'fahrenheit', 'Fahrenheit'

    class Theme(models.TextChoices):
        LIGHT = 'light', 'Light'
        DARK = 'dark', 'Dark'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name='preference',
        on_delete=models.CASCADE,
    )
    # Farm Profile
    farm_name = models.CharField(max_length=255, blank=True)
    farm_location = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # General Preferences
    preferred_language = models.CharField(max_length=10, default='en')
    timezone = models.CharField(max_length=50, default='Asia/Manila')
    measurement_units = models.CharField(max_length=10, default='metric')
    temperature_unit = models.CharField(
        max_length=10, choices=TemperatureUnit.choices, default=TemperatureUnit.CELSIUS
    )
    forecast_days = models.PositiveSmallIntegerField(default=5)

    # AI Assistant Preferences
    ai_response_language = models.CharField(max_length=10, default='en')
    ai_response_style = models.CharField(max_length=20, default='practical')
    ai_response_detail = models.CharField(max_length=20, default='balanced')
    enable_conversation_history = models.BooleanField(default=True)

    # Weather Preferences & Automated Alerts
    weather_alerts_enabled = models.BooleanField(default=True)
    weather_monitoring_enabled = models.BooleanField(default=True)
    weather_update_frequency_hours = models.PositiveSmallIntegerField(default=3)
    weather_alert_min_severity = models.CharField(max_length=20, default='advisory')
    rain_alert_threshold_mm = models.FloatField(default=25.0)
    wind_alert_threshold_kmh = models.FloatField(default=40.0)
    temp_high_threshold_c = models.FloatField(default=35.0)
    temp_low_threshold_c = models.FloatField(default=15.0)

    # Notification Channels & Quiet Hours
    channel_in_app = models.BooleanField(default=True)
    channel_browser = models.BooleanField(default=True)
    channel_email = models.BooleanField(default=True)
    channel_sms = models.BooleanField(default=False)
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.CharField(max_length=5, default='22:00')
    quiet_hours_end = models.CharField(max_length=5, default='06:00')

    # Crop Reminders Preferences
    auto_crop_reminders_enabled = models.BooleanField(default=True)
    reminder_frequency = models.CharField(max_length=20, default='daily')
    notify_growth_stages = models.BooleanField(default=True)
    notify_fertilizer_irrigation = models.BooleanField(default=True)
    notify_pest_inspection = models.BooleanField(default=True)
    notify_harvest_estimation = models.BooleanField(default=True)

    # Legacy Category Toggles
    crop_care_reminders_enabled = models.BooleanField(default=True)
    pest_disease_advisories_enabled = models.BooleanField(default=True)
    ai_analysis_notifications_enabled = models.BooleanField(default=True)
    agricultural_recommendations_enabled = models.BooleanField(default=True)
    application_notices_enabled = models.BooleanField(default=True)

    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tbluserpreference'

    def __str__(self):
        return f'Preferences for {self.user.username}'


class WeatherAlert(models.Model):
    """An active or historical severe weather threat evaluated for a farm location."""

    class Severity(models.TextChoices):
        INFO = 'info', 'Information'
        ADVISORY = 'advisory', 'Advisory'
        WATCH = 'watch', 'Watch'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical Warning'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='weather_alerts',
        on_delete=models.CASCADE,
    )
    farm_location = models.CharField(max_length=255)
    alert_type = models.CharField(
        max_length=50,
        help_text='heavy_rain, flooding, storm, strong_winds, extreme_heat, drought, cold_spell',
    )
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.ADVISORY)
    title = models.CharField(max_length=255)
    forecast_condition = models.CharField(max_length=255)
    expected_timing = models.CharField(max_length=255, blank=True)
    agricultural_impact = models.TextField()
    precautionary_actions = models.TextField()
    source = models.CharField(max_length=150, default='OpenWeatherMap / Official Agro-Met')
    deduplication_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tblweatheralert'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active', '-created_at'], name='weatheralert_user_act_idx'),
        ]

    def __str__(self):
        return f'[{self.get_severity_display()}] {self.title} - {self.farm_location}'


class Notification(models.Model):
    """A user-specific notification with read/unread state and optional link target."""

    class Category(models.TextChoices):
        WEATHER_ALERT = 'weather_alert', 'Weather alert'
        CROP_CARE = 'crop_care', 'Crop care reminder'
        PEST_DISEASE = 'pest_disease', 'Pest and disease advisory'
        AI_ANALYSIS = 'ai_analysis', 'AI analysis status'
        RECOMMENDATION = 'recommendation', 'Agricultural recommendation'
        NOTICE = 'notice', 'Application notice'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='notifications',
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.NOTICE)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    related_url = models.CharField(max_length=500, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=100, blank=True)
    source_id = models.CharField(max_length=100, blank=True)
    deduplication_key = models.CharField(max_length=255, null=True, blank=True, unique=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'tblnotification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'read', '-created_at'], name='notification_user_read_idx'),
            models.Index(fields=['user', 'category', '-created_at'], name='notification_user_category_idx'),
            models.Index(fields=['user', 'deleted_at', '-created_at'], name='notification_user_deleted_idx'),
        ]

    def __str__(self):
        return f'{self.title} — {self.user.username}'


class CropGuideline(models.Model):
    """A recommended crop plan for a season, kept per farm owner."""

    class CropType(models.TextChoices):
        MAIZE = 'maize', 'Maize'
        WHEAT = 'wheat', 'Wheat'
        RICE = 'rice', 'Rice'
        VEGETABLE = 'vegetable', 'Vegetable'
        FRUIT = 'fruit', 'Fruit'
        OTHER = 'other', 'Other'

    crop_type = models.CharField(max_length=20, choices=CropType.choices, default=CropType.OTHER)
    crop_name = models.CharField(max_length=255)
    variety = models.CharField(max_length=255, blank=True)
    sow_date = models.DateField()
    harvest_date = models.DateField(null=True, blank=True)
    area_planted = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    notes = models.TextField(blank=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='crop_guidelines',
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tblcropguideline'
        ordering = ['crop_name']
        indexes = [
            models.Index(fields=['owner', 'crop_type'], name='cropguideline_owner_idx'),
        ]

    def __str__(self):
        return f'{self.crop_name} ({self.get_crop_type_display()})'


class VisualIdentificationLog(models.Model):
    """Field observations recorded while scouting, with visual identification notes."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='visual_identifications',
        on_delete=models.CASCADE,
    )
    field_name = models.CharField(max_length=255)
    inspected_on = models.DateField()
    findings = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tblvisualidentification'
        ordering = ['-inspected_on']
        indexes = [
            models.Index(fields=['owner', 'inspected_on'], name='visidlog_owner_inspected_idx'),
        ]

    def __str__(self):
        return f'{self.field_name} on {self.inspected_on}'


class WeatherRecord(models.Model):
    """Daily weather measurements taken at a location for one farm owner."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='weather_records',
        on_delete=models.CASCADE,
    )
    location = models.CharField(max_length=255)
    recorded_on = models.DateField()
    temperature = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Temperature in degrees Celsius.',
    )
    rainfall = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Rainfall in millimeters.',
    )
    humidity = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Relative humidity in percent.')
    wind_speed = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text='Wind speed in kilometers per hour.',
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tblweatherrecord'
        ordering = ['-recorded_on']
        indexes = [
            models.Index(fields=['owner', 'recorded_on'], name='weatherrecord_owner_idx'),
        ]

    def __str__(self):
        return f'{self.location} - {self.recorded_on}'
