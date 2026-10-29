"""Smart AgriAssist Administrative Dashboard and Analytics Engine.

Collects real-time telemetry from existing Django models (Users, Crops,
Diagnoses, Scheduled Reminders, Weather Alerts, Conversations, and Gemini AI)
to power the unified dark-green Admin Dashboard.
"""

from datetime import date, timedelta
from typing import Any, Dict

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Avg, Case, Count, IntegerField, Q, Sum, When
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone


def get_admin_dashboard_metrics(request) -> Dict[str, Any]:
    """Compile real-time operational farm metrics for the administrator dashboard."""
    User = get_user_model()

    # Lazy-import existing application models
    from apps.core.gemini import api_key_configured, connection_status, model_name
    from apps.core.models import Conversation, CropDiagnosis, Message
    from apps.catalog.models import CropCatalog
    from apps.crops.models import Crop, CropGrowthStage, ScheduledReminder
    from apps.info.models import Notification, UserPreference, WeatherAlert, WeatherRecord

    # --- 1. User Account Telemetry ---
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    staff_users = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).count()
    recent_users = User.objects.order_by('-date_joined')[:6]

    # --- 2. Crop & Land Area Telemetry ---
    total_crops = Crop.objects.count()
    total_catalog_crops = CropCatalog.objects.filter(is_active=True).count()
    growth_stage_references = CropGrowthStage.objects.count()
    active_crops = Crop.objects.filter(status=Crop.Status.ACTIVE).count()
    harvested_crops = Crop.objects.filter(status=Crop.Status.HARVESTED).count()
    lost_crops = Crop.objects.filter(status=Crop.Status.LOST).count()
    planned_crops = Crop.objects.filter(status=Crop.Status.PLANNED).count()

    total_area_sqm = Crop.objects.aggregate(total=Sum('area_sqm'))['total'] or 0
    active_area_sqm = Crop.objects.filter(status=Crop.Status.ACTIVE).aggregate(total=Sum('area_sqm'))['total'] or 0
    total_area_ha = round(float(total_area_sqm) / 10000.0, 2)
    active_area_ha = round(float(active_area_sqm) / 10000.0, 2)

    recent_crops = (
        Crop.objects.select_related('owner')
        .order_by('-created_at')[:8]
    )

    # --- 3. Crop Diagnoses Telemetry ---
    total_diagnoses = CropDiagnosis.objects.count()
    total_image_messages = Message.objects.exclude(image='').count()
    confirmed_diagnoses = CropDiagnosis.objects.filter(is_confirmed=True).count()
    recent_diagnoses = (
        CropDiagnosis.objects.select_related('user')
        .order_by('-created_at')[:6]
    )

    # --- 4. Scheduled Field Reminders ---
    total_reminders = ScheduledReminder.objects.count()
    pending_reminders = ScheduledReminder.objects.filter(status=ScheduledReminder.Status.PENDING).count()
    completed_reminders = ScheduledReminder.objects.filter(status=ScheduledReminder.Status.COMPLETED).count()

    upcoming_reminders = (
        ScheduledReminder.objects.select_related('user', 'crop')
        .filter(status=ScheduledReminder.Status.PENDING)
        .order_by('due_date')[:8]
    )

    # --- 5. AI Assistant & Communication Telemetry ---
    total_conversations = Conversation.objects.count()
    total_messages = Message.objects.count()
    recent_conversations = (
        Conversation.objects.select_related('owner')
        .order_by('-last_message_at')[:6]
    )

    # AI Integration status check
    try:
        ai_conn = connection_status()
        ai_connected = ai_conn.get('state') == 'connected'
        ai_state_msg = ai_conn.get('message', 'AI service ready')
    except Exception:
        ai_connected = api_key_configured()
        ai_state_msg = 'API Key Configured' if ai_connected else 'API Key Not Set'

    ai_status = {
        'connected': ai_connected,
        'state_message': ai_state_msg,
        'model_name': model_name(),
        'configured': api_key_configured(),
    }

    # --- 6. Weather & Active Advisories ---
    active_weather_queryset = WeatherAlert.objects.filter(is_active=True)
    active_weather_count = active_weather_queryset.count()
    active_critical_weather_count = active_weather_queryset.filter(severity='critical').count()
    active_weather_alerts = active_weather_queryset.annotate(
        severity_order=Case(
            When(severity='critical', then=0),
            When(severity='warning', then=1),
            When(severity='watch', then=2),
            default=3,
            output_field=IntegerField(),
        )
    ).order_by('severity_order', '-created_at')[:2]
    total_weather_records = WeatherRecord.objects.count()

    # Monitored farm municipalities / locations
    farm_locations = (
        Crop.objects.exclude(farm_location='')
        .values_list('farm_location', flat=True)
        .distinct()[:12]
    )

    # --- 7. Notifications ---
    notifications = Notification.objects.filter(deleted_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )
    unread_notifications = notifications.filter(read=False).count()
    recent_notifications = (
        notifications.select_related('user')
        .order_by('-created_at')[:6]
    )

    today = timezone.localdate()
    first_day = today - timedelta(days=13)
    start_datetime = timezone.make_aware(
        timezone.datetime.combine(first_day, timezone.datetime.min.time())
    )
    end_datetime = timezone.make_aware(
        timezone.datetime.combine(today + timedelta(days=1), timezone.datetime.min.time())
    )
    chart_labels = [
        (first_day + timedelta(days=offset)).strftime('%b %d')
        for offset in range(14)
    ]

    def daily_counts(queryset, field):
        counts = {
            entry['day']: entry['total']
            for entry in queryset.filter(
                **{f'{field}__gte': start_datetime, f'{field}__lt': end_datetime}
            ).annotate(day=TruncDate(field)).values('day').annotate(total=Count('pk'))
        }
        return [counts.get(first_day + timedelta(days=offset), 0) for offset in range(14)]

    weather_by_day = {
        entry['recorded_on']: entry
        for entry in WeatherRecord.objects.filter(
            recorded_on__gte=first_day,
            recorded_on__lte=today,
        ).values('recorded_on').annotate(
            average_temperature=Avg('temperature'),
            total_rainfall=Sum('rainfall'),
        )
    }
    recent_activity = []
    for user in recent_users:
        recent_activity.append({
            'created_at': user.date_joined,
            'title': f'Account registered: {user.username}',
            'kind': 'User account',
            'url': reverse('admin:auth_user_change', args=[user.pk]),
        })
    for crop in recent_crops:
        recent_activity.append({
            'created_at': crop.created_at,
            'title': f'Crop registered: {crop.crop_name}',
            'kind': 'Crop',
            'url': reverse('admin:crops_crop_change', args=[crop.pk]),
        })
    for diagnosis in recent_diagnoses:
        recent_activity.append({
            'created_at': diagnosis.created_at,
            'title': f'AI identification: {diagnosis.crop_name or diagnosis.possible_disease}',
            'kind': 'AI assistant',
            'url': reverse('admin:core_cropdiagnosis_change', args=[diagnosis.pk]),
        })
    recent_activity.sort(key=lambda activity: activity['created_at'], reverse=True)

    chart_data = {
        'labels': chart_labels,
        'users': daily_counts(User.objects.all(), 'date_joined'),
        'crops': daily_counts(Crop.objects.all(), 'created_at'),
        'diagnoses': daily_counts(CropDiagnosis.objects.all(), 'created_at'),
        'messages': daily_counts(Message.objects.all(), 'created_at'),
        'crop_status': {
            'labels': ['Active', 'Planned', 'Harvested', 'Lost'],
            'values': [active_crops, planned_crops, harvested_crops, lost_crops],
        },
        'weather': {
            'labels': chart_labels,
            'temperature': [
                float(weather_by_day[day]['average_temperature'])
                if day in weather_by_day and weather_by_day[day]['average_temperature'] is not None
                else None
                for day in (first_day + timedelta(days=offset) for offset in range(14))
            ],
            'rainfall': [
                float(weather_by_day[day]['total_rainfall'])
                if day in weather_by_day and weather_by_day[day]['total_rainfall'] is not None
                else None
                for day in (first_day + timedelta(days=offset) for offset in range(14))
            ],
        },
    }

    return {
        # Users
        'total_users': total_users,
        'active_users': active_users,
        'staff_users': staff_users,
        'recent_users': recent_users,

        # Crops & Land Area
        'total_crops': total_crops,
        'total_catalog_crops': total_catalog_crops,
        'growth_stage_references': growth_stage_references,
        'active_crops': active_crops,
        'harvested_crops': harvested_crops,
        'lost_crops': lost_crops,
        'planned_crops': planned_crops,
        'total_area_sqm': total_area_sqm,
        'active_area_sqm': active_area_sqm,
        'total_area_ha': total_area_ha,
        'active_area_ha': active_area_ha,
        'recent_crops': recent_crops,

        # Diagnoses
        'total_diagnoses': total_diagnoses,
        'total_image_messages': total_image_messages,
        'confirmed_diagnoses': confirmed_diagnoses,
        'recent_diagnoses': recent_diagnoses,

        # Reminders
        'total_reminders': total_reminders,
        'pending_reminders': pending_reminders,
        'completed_reminders': completed_reminders,
        'upcoming_reminders': upcoming_reminders,

        # AI & Communication
        'total_conversations': total_conversations,
        'total_messages': total_messages,
        'recent_conversations': recent_conversations,
        'ai_status': ai_status,

        # Weather & Locations
        'active_weather_alerts': active_weather_alerts,
        'active_weather_count': active_weather_count,
        'active_critical_weather_count': active_critical_weather_count,
        'total_weather_records': total_weather_records,
        'farm_locations': farm_locations,

        # Notifications
        'unread_notifications': unread_notifications,
        'recent_notifications': recent_notifications,
        'dismissed_admin_notification_ids': request.session.get('dismissed_admin_notification_ids', []),
        'recent_activity': recent_activity[:8],
        'chart_data': chart_data,
        'chart_start_date': first_day,
        'chart_end_date': today,
    }


def setup_smart_admin():
    """Enhance Django's default AdminSite with Smart AgriAssist branding and analytics."""
    admin.site.site_header = 'SMART AGRIASSIST'
    admin.site.site_title = 'Smart AgriAssist Admin'
    admin.site.index_title = 'Farm System Administration'
    admin.site.login_template = 'admin/login.html'
    admin.site.index_template = 'admin/index.html'

    # Save original index method if not already wrapped
    if not getattr(admin.site, '_smart_admin_wrapped', False):
        original_index = admin.site.index

        def smart_admin_index(request, extra_context=None):
            extra_context = extra_context or {}
            hidden_models = {
                ('auth', 'group'),
                ('core', 'conversation'),
                ('core', 'message'),
                ('info', 'cropguideline'),
            }
            app_list = admin.site.get_app_list(request)
            for app in app_list:
                app['models'] = [
                    model for model in app['models']
                    if (app['app_label'], model['object_name'].lower()) not in hidden_models
                ]
            extra_context['app_list'] = [
                app for app in app_list if app['models']
            ]
            extra_context.update(get_admin_dashboard_metrics(request))
            return original_index(request, extra_context=extra_context)

        admin.site.index = smart_admin_index
        admin.site._smart_admin_wrapped = True
