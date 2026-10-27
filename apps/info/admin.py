from django.contrib import admin
from .models import (
    CropGuideline,
    Notification,
    UserPreference,
    VisualIdentificationLog,
    WeatherAlert,
    WeatherRecord,
)


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'farm_name', 'farm_location', 'preferred_language', 'weather_monitoring_enabled')
    search_fields = ('user__username', 'farm_name', 'farm_location')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'category', 'priority', 'read', 'created_at')
    list_filter = ('category', 'priority', 'read', 'created_at')
    search_fields = ('title', 'message', 'user__username')


@admin.register(WeatherAlert)
class WeatherAlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'farm_location', 'severity', 'is_active', 'created_at')
    list_filter = ('severity', 'is_active', 'alert_type', 'created_at')
    search_fields = ('title', 'farm_location', 'user__username')


@admin.register(CropGuideline)
class CropGuidelineAdmin(admin.ModelAdmin):
    list_display = ('crop_type', 'crop_name', 'owner', 'sow_date', 'harvest_date')
    list_filter = ('crop_type', 'sow_date')
    search_fields = ('crop_name', 'variety', 'notes')


@admin.register(VisualIdentificationLog)
class VisualIdentificationLogAdmin(admin.ModelAdmin):
    list_display = ('field_name', 'inspected_on', 'owner')
    list_filter = ('inspected_on',)
    search_fields = ('field_name', 'findings')


@admin.register(WeatherRecord)
class WeatherRecordAdmin(admin.ModelAdmin):
    list_display = (
        'location',
        'recorded_on',
        'temperature',
        'rainfall',
        'humidity',
        'wind_speed',
        'owner',
    )
    list_filter = ('recorded_on', 'location')
    search_fields = ('location', 'notes')
