
"""Template context processors for SMART AGRIASSIST."""

from apps.info.models import Notification


def unread_notifications(request):
    """Add unread notification count to every template context."""
    if request.user.is_authenticated:
        return {
            'unread_count': Notification.objects.filter(
                user=request.user,
                read=False,
                deleted_at__isnull=True,
            ).count(),
        }
    return {'unread_count': 0}


def admin_sidebar_counts(request):
    """Provide real counts for the admin sidebar when a staff member views the admin portal."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return {}
    if not request.path.startswith('/admin'):
        return {}
    try:
        from apps.crops.models import Crop, ScheduledReminder
        from apps.info.models import WeatherAlert
        return {
            'total_crops': Crop.objects.count(),
            'pending_reminders': ScheduledReminder.objects.filter(status='pending').count(),
            'active_weather_count': WeatherAlert.objects.filter(is_active=True).count(),
        }
    except Exception:
        return {}
