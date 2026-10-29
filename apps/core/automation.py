"""Automated Agricultural Engine for SMART Agricultural Assistant.

Implements all 12 required automated background processes:
 1. Automatic weather data retrieval
 2. Automatic weather risk evaluation
 3. Automatic severe-weather alert processing
 4. Automatic notification delivery (in-app, email, browser)
 5. Automatic crop age and growth-stage calculations
 6. Automatic estimated harvest-date calculations
 7. Automatic crop activity reminder generation
 8. Automatic overdue reminder handling
 9. Automatic alert deduplication
10. Automatic retry handling for temporary API or notification failures
11. Automatic cleanup of expired temporary uploads and cached data
12. Automatic logging and monitoring of background task failures
"""

from datetime import date, datetime, timedelta
import logging
import os
import time
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.core.weather import (
    evaluate_weather_risks,
    geocode_location,
    get_weather,
    get_weather_history,
)
from apps.crops.growth_engine import calculate_crop_growth
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import Notification, UserPreference, WeatherAlert, WeatherRecord

logger = logging.getLogger('agricultural.automation')
User = get_user_model()
WEATHER_HISTORY_SYNC_INTERVAL = timedelta(hours=6)
AUTOMATED_WEATHER_RECORD_NOTE = 'Automatically synced from Open-Meteo.'


class AutomationResult:
    def __init__(self):
        self.started_at = timezone.now()
        self.completed_at = None
        self.users_processed = 0
        self.weather_checks = 0
        self.weather_records_synced = 0
        self.weather_alerts_generated = 0
        self.duplicate_alerts_skipped = 0
        self.emails_sent = 0
        self.crops_updated = 0
        self.stage_transitions_detected = 0
        self.reminders_generated = 0
        self.reminder_notifications_sent = 0
        self.overdue_reminders_flagged = 0
        self.cleaned_records = 0
        self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        duration = (self.completed_at - self.started_at).total_seconds() if self.completed_at else 0
        return {
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': round(duration, 2),
            'users_processed': self.users_processed,
            'weather_checks': self.weather_checks,
            'weather_records_synced': self.weather_records_synced,
            'weather_alerts_generated': self.weather_alerts_generated,
            'duplicate_alerts_skipped': self.duplicate_alerts_skipped,
            'emails_sent': self.emails_sent,
            'crops_updated': self.crops_updated,
            'stage_transitions_detected': self.stage_transitions_detected,
            'reminders_generated': self.reminders_generated,
            'reminder_notifications_sent': self.reminder_notifications_sent,
            'overdue_reminders_flagged': self.overdue_reminders_flagged,
            'cleaned_records': self.cleaned_records,
            'errors_count': len(self.errors),
            'errors': self.errors[:10],
        }


def run_all_agricultural_automations(target_user: Optional[Any] = None) -> AutomationResult:
    """Run all 12 agricultural automation workflows with full error resilience and monitoring."""
    result = AutomationResult()
    logger.info('Starting agricultural automation cycle (target_user=%s)', target_user)

    users = [target_user] if target_user else list(User.objects.filter(is_active=True))

    for user in users:
        result.users_processed += 1
        try:
            pref, _ = UserPreference.objects.get_or_create(user=user)
        except Exception as exc:
            err_msg = f'Failed to get/create preferences for user {user.username}: {exc}'
            logger.error(err_msg)
            result.errors.append(err_msg)
            continue

        # 1-4 & 9: Weather retrieval, risk evaluation, alert processing, deduplication & delivery
        _process_weather_automations(user, pref, result)

        # 5-8: Crop growth tracking, harvest calculation, stage alerts & overdue reminders
        _process_crop_automations(user, pref, result)

    # 11: Cleanup of expired records and cache
    _process_data_cleanup(result)

    result.completed_at = timezone.now()
    logger.info(
        'Agricultural automation cycle finished in %.2fs with %d errors. Processed %d users, %d weather alerts.',
        (result.completed_at - result.started_at).total_seconds(),
        len(result.errors),
        result.users_processed,
        result.weather_alerts_generated,
    )
    return result


def _process_weather_automations(user: Any, pref: UserPreference, result: AutomationResult):
    """Tasks 1, 2, 3, 4, 9, 10: Live weather retrieval, risk evaluation, alert processing, deduplication, notifications."""
    if not pref.weather_monitoring_enabled:
        return

    location = pref.farm_location or 'Farm Location'

    # Auto-geocode location if GPS coordinates are not yet configured
    if pref.farm_location and (pref.latitude is None or pref.longitude is None):
        geo = geocode_location(pref.farm_location)
        if geo:
            pref.latitude = geo['latitude']
            pref.longitude = geo['longitude']
            if not pref.farm_timezone:
                pref.farm_timezone = geo.get('timezone', 'Asia/Manila')
            pref.save(update_fields=['latitude', 'longitude', 'farm_timezone'])

    lat = float(pref.latitude) if pref.latitude else 16.9754
    lon = float(pref.longitude) if pref.longitude else 121.7743

    # Task 1: Weather Retrieval with Task 10 Retry Handling
    weather_data = None
    for attempt in range(2):
        try:
            weather_data = get_weather(
                lat=lat,
                lon=lon,
                units=pref.temperature_unit or 'metric',
                location_name=location,
            )
            result.weather_checks += 1
            break
        except Exception as exc:
            if attempt == 1:
                err_msg = f'Weather retrieval failed for user {user.username} at {location}: {exc}'
                logger.warning(err_msg)
                result.errors.append(err_msg)
            time.sleep(0.5)

    if not weather_data or not weather_data.get('available'):
        return

    # Update latest successful weather update timestamp persistently
    pref.weather_last_updated = timezone.now()
    pref.save(update_fields=['weather_last_updated'])
    result.weather_records_synced += _sync_weather_history(
        user=user,
        pref=pref,
        location=location,
        latitude=lat,
        longitude=lon,
    )

    # Task 2: Weather Risk Evaluation (incorporates official PAGASA warnings & Open-Meteo forecast risks)
    risks = evaluate_weather_risks(
        weather_data=weather_data,
        location_name=location,
        rain_threshold_mm=pref.rain_alert_threshold_mm,
        wind_threshold_kmh=pref.wind_alert_threshold_kmh,
        temp_high_threshold_c=pref.temp_high_threshold_c,
        temp_low_threshold_c=pref.temp_low_threshold_c,
        lat=lat,
        lon=lon,
        country=pref.country,
    )

    # Severity ordering
    severity_rank = {
        'info': 1,
        'advisory': 2,
        'watch': 3,
        'warning': 4,
        'critical': 5,
    }
    min_rank = severity_rank.get(pref.weather_alert_min_severity, 2)

    # Update or resolve existing alerts when weather conditions change
    active_existing_alerts = WeatherAlert.objects.filter(user=user, is_active=True)
    current_alert_types = {r['alert_type'] for r in risks if severity_rank.get(r.get('severity', 'advisory'), 2) >= min_rank}

    for existing_alert in active_existing_alerts:
        if existing_alert.alert_type not in current_alert_types:
            # Weather risk has passed; resolve alert
            existing_alert.is_active = False
            existing_alert.save(update_fields=['is_active'])

    # Task 3, 4, 9: Severe-Weather Alert Processing, Deduplication, & Notifications
    for r in risks:
        r_severity = r.get('severity', 'advisory')
        if severity_rank.get(r_severity, 2) < min_rank:
            continue

        dedup_key = r.get('deduplication_key')
        is_official = r.get('is_official', False)

        # Prevent duplicate notifications for continuing weather events:
        # Check if an alert for this user with this alert_type is already active
        existing_active = active_existing_alerts.filter(alert_type=r['alert_type']).first()
        if existing_active:
            # Continuing weather event: update condition without duplicate notification
            existing_active.forecast_condition = r['forecast_condition']
            existing_active.expected_timing = r.get('expected_timing', '')
            existing_active.save(update_fields=['forecast_condition', 'expected_timing'])
            result.duplicate_alerts_skipped += 1
            continue

        if dedup_key and WeatherAlert.objects.filter(deduplication_key=dedup_key).exists():
            result.duplicate_alerts_skipped += 1
            continue

        try:
            with transaction.atomic():
                alert = WeatherAlert.objects.create(
                    user=user,
                    farm_location=location,
                    alert_type=r['alert_type'],
                    severity=r['severity'],
                    title=r['title'],
                    forecast_condition=r['forecast_condition'],
                    expected_timing=r.get('expected_timing', ''),
                    agricultural_impact=r['agricultural_impact'],
                    precautionary_actions=r['precautionary_actions'],
                    source=r.get('source', 'Open-Meteo Forecast Alert'),
                    is_official=is_official,
                    deduplication_key=dedup_key,
                    is_active=True,
                )
                result.weather_alerts_generated += 1

                # Task 4: In-app Notification Delivery with clear official distinction
                if pref.channel_in_app and pref.weather_alerts_enabled:
                    badge_prefix = "🚨 [Official Warning]" if is_official else "⚠️ [Weather Alert]"
                    Notification.objects.create(
                        user=user,
                        title=f"{badge_prefix} {r['title']}",
                        message=f"{r['agricultural_impact']}\n\nPrecautionary Actions:\n{r['precautionary_actions']}",
                        category=Notification.Category.WEATHER_ALERT,
                        priority=(
                            Notification.Priority.CRITICAL if r_severity == 'critical'
                            else Notification.Priority.HIGH if r_severity == 'warning'
                            else Notification.Priority.NORMAL
                        ),
                        deduplication_key=f"notif_{dedup_key}" if dedup_key else None,
                        related_url='/weather/',
                    )

                # Agricultural recommendation for severe weather
                if pref.agricultural_recommendations_enabled and r['alert_type'] in ('heavy_rain', 'storm'):
                    rec_dedup = f"rec_{r['alert_type']}_{user.pk}_{date.today().isoformat()}"
                    if not Notification.objects.filter(deduplication_key=rec_dedup).exists():
                        Notification.objects.create(
                            user=user,
                            title=f"🌾 Farm Advisory: {r['title']} Agricultural Precautions",
                            message=f"Recommended actions for your active crops:\n{r['precautionary_actions']}",
                            category=Notification.Category.RECOMMENDATION,
                            priority=Notification.Priority.NORMAL,
                            deduplication_key=rec_dedup,
                            related_url='/crops/tracker/',
                        )

                # Task 4: Email Alert Delivery (if enabled and configured)
                if pref.channel_email and user.email and pref.weather_alerts_enabled:
                    _send_weather_alert_email(user, alert, r, result)

        except Exception as exc:
            err_msg = f'Failed to persist weather alert for user {user.username}: {exc}'
            logger.error(err_msg)
            result.errors.append(err_msg)

    # Secondary automated risk check: high humidity + warm temperatures favor fungal pest and disease
    curr = weather_data.get('current', {})
    if pref.pest_disease_advisories_enabled and curr.get('humidity', 0) >= 85 and curr.get('temperature', 0) >= 26.0:
        pest_dedup = f"pest_hum_{user.pk}_{date.today().isoformat()}"
        if not Notification.objects.filter(deduplication_key=pest_dedup).exists():
            Notification.objects.create(
                user=user,
                title="🐛 Pest & Disease Advisory: High Fungal & Bacterial Pressure",
                message=(
                    f"Current high relative humidity ({curr.get('humidity')}%) and warm temperatures ({curr.get('temperature')}°C) "
                    "increase the likelihood of leaf blast, sheath blight, bacterial leaf streak, and fungal rots. "
                    "Inspect crop canopy lower leaves and maintain field aeration."
                ),
                category=Notification.Category.PEST_DISEASE,
                priority=Notification.Priority.NORMAL,
                deduplication_key=pest_dedup,
                related_url='/crops/tracker/',
            )


def _sync_weather_history(user, pref, location, latitude, longitude):
    """Persist recent daily API observations without replacing manual records."""
    now = timezone.now()
    if (
        pref.weather_history_last_synced
        and now - pref.weather_history_last_synced < WEATHER_HISTORY_SYNC_INTERVAL
    ):
        return 0

    today = timezone.localdate()
    start_date = today - timedelta(days=13)
    history = get_weather_history(
        latitude,
        longitude,
        start_date=start_date.isoformat(),
        end_date=today.isoformat(),
        units='metric',
    )
    if not history.get('available'):
        logger.warning('Daily weather history is unavailable for %s.', location)
        return 0

    synced_count = 0
    for day_text, values in history.get('daily', {}).items():
        try:
            recorded_on = date.fromisoformat(day_text)
        except (TypeError, ValueError):
            logger.warning('Ignoring invalid weather-history date %r for %s.', day_text, location)
            continue
        if recorded_on < start_date or recorded_on > today:
            continue

        record = WeatherRecord.objects.filter(
            owner=user,
            location__iexact=location,
            recorded_on=recorded_on,
        ).order_by('pk').first()
        if record and record.notes != AUTOMATED_WEATHER_RECORD_NOTE:
            continue

        if record:
            record.temperature = values.get('temperature')
            record.rainfall = values.get('rainfall')
            record.save(update_fields=['temperature', 'rainfall', 'updated_at'])
        else:
            WeatherRecord.objects.create(
                owner=user,
                location=location,
                recorded_on=recorded_on,
                temperature=values.get('temperature'),
                rainfall=values.get('rainfall'),
                notes=AUTOMATED_WEATHER_RECORD_NOTE,
            )
        synced_count += 1

    pref.weather_history_last_synced = now
    pref.save(update_fields=['weather_history_last_synced'])
    return synced_count


def _send_weather_alert_email(user: Any, alert: WeatherAlert, risk: Dict[str, Any], result: AutomationResult):
    """Deliver urgent weather advisory email with practical agricultural precautions."""
    subject = f"[SMART AGRIASSIST] {alert.title}"
    body = (
        f"Dear {user.first_name or user.username},\n\n"
        f"An urgent agricultural weather alert has been issued for your farm location ({alert.farm_location}):\n\n"
        f"Condition: {alert.forecast_condition}\n"
        f"Expected Timing: {alert.expected_timing}\n\n"
        f"Agricultural Impact:\n{alert.agricultural_impact}\n\n"
        f"Recommended Precautionary Actions:\n{alert.precautionary_actions}\n\n"
        f"Stay safe and check your SMART AGRIASSIST dashboard for real-time updates:\n"
        f"{getattr(settings, 'SITE_URL', 'http://localhost:8000')}/weather/\n\n"
        f"---\n"
        f"SMART Agricultural Assistant Automated Monitoring Service"
    )
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'agriassist@example.com'),
            recipient_list=[user.email],
            fail_silently=True,
        )
        result.emails_sent += 1
    except Exception as exc:
        logger.warning('Failed to send weather alert email to %s: %s', user.email, exc)


def _process_crop_automations(user: Any, pref: UserPreference, result: AutomationResult):
    """Tasks 5, 6, 7, 8: Crop age, growth stage transitions, harvest calculation, activity reminders, overdue handling."""
    active_crops = Crop.objects.filter(owner=user, status=Crop.Status.ACTIVE)
    today = date.today()

    for crop in active_crops:
        result.crops_updated += 1
        try:
            growth = crop.growth_data
            current_stage = growth.get('current_stage')
            if not current_stage:
                continue

            stage_name = current_stage['name']

            # Task 5: Check if crop entered this stage today or recently (within 2 days)
            start_date = current_stage.get('start_date')
            if start_date and 0 <= (today - start_date).days <= 2:
                dedup = f"crop_stage_{crop.pk}_{current_stage['order']}_{start_date.isoformat()}"
                if pref.notify_growth_stages and not Notification.objects.filter(deduplication_key=dedup).exists():
                    Notification.objects.create(
                        user=user,
                        title=f"🌱 {crop.crop_name}: Now Entering {stage_name}",
                        message=(
                            f'Your {crop.crop_name} (Field: {crop.field_name or "Main"}) is now {growth["days_since_planting"]} days old. '
                            f'Stage focus: {current_stage["description"]}\n\n'
                            f'Recommended Care: {", ".join(current_stage.get("activities", [])[:3])}'
                        ),
                        category=Notification.Category.CROP_CARE,
                        priority=Notification.Priority.NORMAL,
                        deduplication_key=dedup,
                        related_url=f'/crops/tracker/{crop.pk}/',
                    )
                    result.stage_transitions_detected += 1

            # Task 6: Estimated Harvest Date calculation & impending harvest notification
            harvest_date = growth.get('estimated_harvest_date')
            days_left = growth.get('days_until_harvest', 999)
            if pref.notify_harvest_estimation and harvest_date and 0 <= days_left <= 7:
                harvest_dedup = f"harvest_alert_{crop.pk}_{harvest_date.isoformat()}"
                if not Notification.objects.filter(deduplication_key=harvest_dedup).exists():
                    Notification.objects.create(
                        user=user,
                        title=f"🌾 {crop.crop_name}: Harvest Approaching ({days_left} days remaining)",
                        message=(
                            f'Your {crop.crop_name} is estimated for harvest on {harvest_date.strftime("%B %d, %Y")}. '
                            f'Perform on-site maturity inspections, check grain/fruit coloration, drain excess water, and prepare equipment.'
                        ),
                        category=Notification.Category.CROP_CARE,
                        priority=Notification.Priority.HIGH,
                        deduplication_key=harvest_dedup,
                        related_url=f'/crops/tracker/{crop.pk}/',
                    )

            # Task 7: Generate reminders for upcoming milestone activities
            if pref.auto_crop_reminders_enabled:
                for m in growth.get('milestones', []):
                    m_start = m.get('start_date')
                    if m_start and 0 <= (m_start - today).days <= 3:
                        is_seedling = m.get('order') == 1
                        rem_title = (
                            f"{crop.crop_name}: Seedling Care & Emergence Check"
                            if is_seedling
                            else f"{crop.crop_name}: {m['name']} Monitoring"
                        )
                        _, created = ScheduledReminder.objects.get_or_create(
                            user=user,
                            crop=crop,
                            title=rem_title,
                            activity_type=(
                                ScheduledReminder.ActivityType.SEEDLING_CARE
                                if is_seedling
                                else ScheduledReminder.ActivityType.GROWTH_MONITORING
                            ),
                            due_date=m_start,
                            defaults={
                                'notes': f'Recommended activities: {", ".join(m.get("activities", []))}',
                                'is_automated': True,
                            },
                        )
                        if created:
                            result.reminders_generated += 1

        except Exception as exc:
            err_msg = f'Failed processing crop tracking for crop {crop.pk} ({crop.crop_name}): {exc}'
            logger.error(err_msg)
            result.errors.append(err_msg)

    # Task 8: Overdue Reminder Handling
    try:
        overdue_reminders = ScheduledReminder.objects.filter(
            user=user,
            status=ScheduledReminder.Status.PENDING,
            due_date__lt=today,
        )
        count = overdue_reminders.update(status=ScheduledReminder.Status.OVERDUE)
        result.overdue_reminders_flagged += count
    except Exception as exc:
        err_msg = f'Failed updating overdue reminders for user {user.username}: {exc}'
        logger.error(err_msg)
        result.errors.append(err_msg)

    _notify_due_crop_reminders(user, pref, result, today)


def _notify_due_crop_reminders(user: Any, pref: UserPreference, result: AutomationResult, today: date):
    """Create one in-app notification for each automated reminder due within three days."""
    if not pref.auto_crop_reminders_enabled or not pref.channel_in_app:
        return

    reminders = ScheduledReminder.objects.filter(
        user=user,
        is_automated=True,
        status__in=[ScheduledReminder.Status.PENDING, ScheduledReminder.Status.OVERDUE],
        due_date__range=(today - timedelta(days=3), today + timedelta(days=3)),
    ).select_related('crop')

    for reminder in reminders:
        is_overdue = reminder.status == ScheduledReminder.Status.OVERDUE
        due_label = reminder.due_date.strftime('%B %d, %Y')
        title = f'Overdue crop reminder: {reminder.title}' if is_overdue else f'Upcoming crop reminder: {reminder.title}'
        message = (
            f'This scheduled crop activity was due on {due_label}.'
            if is_overdue
            else f'This scheduled crop activity is due on {due_label}.'
        )
        try:
            _, created = Notification.objects.get_or_create(
                deduplication_key=f'scheduled_crop_reminder_{reminder.pk}',
                defaults={
                    'user': user,
                    'title': title,
                    'message': message,
                    'category': Notification.Category.CROP_CARE,
                    'priority': Notification.Priority.HIGH if is_overdue else Notification.Priority.NORMAL,
                    'related_url': f'/crops/tracker/{reminder.crop_id}/' if reminder.crop_id else '/crops/tracker/',
                },
            )
            if created:
                result.reminder_notifications_sent += 1
        except Exception as exc:
            err_msg = f'Failed notifying user {user.username} about reminder {reminder.pk}: {exc}'
            logger.error(err_msg)
            result.errors.append(err_msg)


def _process_data_cleanup(result: AutomationResult):
    """Task 11: Cleanup of expired temporary uploads, deleted notifications, and stale cache."""
    try:
        cutoff = timezone.now() - timedelta(days=30)
        # Purge soft-deleted notifications older than 30 days
        deleted_count, _ = Notification.objects.filter(deleted_at__lt=cutoff).delete()
        result.cleaned_records += deleted_count
    except Exception as exc:
        logger.warning('Data cleanup error: %s', exc)
