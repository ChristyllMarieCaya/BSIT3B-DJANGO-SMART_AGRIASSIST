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
