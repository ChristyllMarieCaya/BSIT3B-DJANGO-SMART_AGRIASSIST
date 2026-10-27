from django.contrib import admin
from apps.crops.models import Crop, CropGrowthStage, ScheduledReminder


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ('crop_name', 'variety', 'owner', 'field_name', 'planting_date', 'status', 'created_at')
    list_filter = ('status', 'crop_name', 'created_at')
    search_fields = ('crop_name', 'variety', 'field_name', 'owner__username')


@admin.register(CropGrowthStage)
class CropGrowthStageAdmin(admin.ModelAdmin):
    list_display = ('crop_name', 'stage_order', 'stage_name', 'start_day', 'end_day')
    list_filter = ('crop_name',)
    ordering = ('crop_name', 'stage_order')


@admin.register(ScheduledReminder)
class ScheduledReminderAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'crop', 'activity_type', 'due_date', 'status', 'is_automated')
    list_filter = ('status', 'activity_type', 'is_automated')
    search_fields = ('title', 'user__username', 'crop__crop_name')
