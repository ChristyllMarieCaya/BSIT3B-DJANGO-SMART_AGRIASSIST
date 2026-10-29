"""Reusable and modular admin actions for the crops application."""

import csv
from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.crops.views import _generate_crop_reminders


@admin.action(description=_('📊 Export selected crops to CSV report'))
def export_crops_csv(modeladmin, request, queryset):
    """Export selected crop records and calculated agronomic metrics to a CSV file."""
    response = HttpResponse(content_type='text/csv')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    response['Content-Disposition'] = f'attachment; filename="smartagri_crops_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Crop ID',
        'Crop Name',
        'Variety',
        'Owner / Farmer',
        'Farm Location',
        'Field Identifier',
        'Planted Area (sqm)',
        'Planted Area (ha)',
        'Planting Date',
        'Status',
        'Current Growth Stage',
        'Growth Progress (%)',
        'Estimated Harvest Date',
        'Days Until Harvest',
        'Notes',
    ])

    for crop in queryset:
        sqm = float(crop.area_sqm or 0)
        ha = round(sqm / 10000.0, 3)
        progress = round(float(crop.overall_progress), 1) if crop.overall_progress else 0.0
        harvest_date = crop.estimated_harvest_date.strftime('%Y-%m-%d') if crop.estimated_harvest_date else ''

        writer.writerow([
            crop.pk,
            crop.crop_name,
            crop.variety,
            crop.owner.username,
            crop.farm_location,
            crop.field_name,
            sqm,
            ha,
            crop.planting_date,
            crop.get_status_display(),
            crop.current_stage_name,
            progress,
            harvest_date,
            crop.days_until_harvest,
            crop.notes.replace('\n', ' ').strip() if crop.notes else '',
        ])

    modeladmin.message_user(
        request,
        f'Exported {queryset.count()} crop record(s) to CSV.',
        messages.SUCCESS,
    )
    return response


@admin.action(description=_('⚡ Generate / Refresh Stage Reminders'))
def generate_stage_reminders(modeladmin, request, queryset):
    """Bulk generate or refresh growth milestone reminders for selected crops."""
    count = 0
    for crop in queryset:
        _generate_crop_reminders(crop)
        count += 1
    modeladmin.message_user(
        request,
        f'Generated/refreshed milestone activity reminders for {count} crop(s).',
        messages.SUCCESS,
    )


@admin.action(description=_('Mark selected crops as Harvested'))
def mark_as_harvested(modeladmin, request, queryset):
    from apps.crops.models import Crop
    updated = queryset.update(status=Crop.Status.HARVESTED)
    modeladmin.message_user(request, f'{updated} crop(s) marked as Harvested.', messages.SUCCESS)


@admin.action(description=_('Mark selected crops as Lost / Cancelled'))
def mark_as_lost(modeladmin, request, queryset):
    from apps.crops.models import Crop
    updated = queryset.update(status=Crop.Status.LOST)
    modeladmin.message_user(request, f'{updated} crop(s) marked as Lost / Cancelled.', messages.WARNING)


@admin.action(description=_('Mark selected crops as Active'))
def mark_as_active(modeladmin, request, queryset):
    from apps.crops.models import Crop
    updated = queryset.update(status=Crop.Status.ACTIVE)
    modeladmin.message_user(request, f'{updated} crop(s) marked as Active.', messages.SUCCESS)


@admin.action(description=_('✅ Mark selected reminders as Completed'))
def mark_reminders_completed(modeladmin, request, queryset):
    from apps.crops.models import ScheduledReminder
    updated = queryset.update(
        status=ScheduledReminder.Status.COMPLETED,
        completed_at=timezone.now(),
    )
    modeladmin.message_user(request, f'{updated} reminder(s) marked as Completed.', messages.SUCCESS)


@admin.action(description=_('Mark selected reminders as Cancelled'))
def mark_reminders_cancelled(modeladmin, request, queryset):
    from apps.crops.models import ScheduledReminder
    updated = queryset.update(status=ScheduledReminder.Status.CANCELLED)
    modeladmin.message_user(request, f'{updated} reminder(s) marked as Cancelled.', messages.WARNING)
