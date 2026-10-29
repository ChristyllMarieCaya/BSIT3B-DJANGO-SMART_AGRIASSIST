"""User Timezone Middleware.

Ensures that dates, timestamps, and model created/updated fields rendered in
templates and views automatically respect the user's configured IANA timezone
with full support for daylight saving time (DST) transitions.
"""

import zoneinfo
from django.utils import timezone


class UserTimezoneMiddleware:
    """Activates the user's saved IANA timezone for all timestamp formatting and template rendering."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                pref = getattr(request.user, 'preference', None)
                if pref and pref.timezone:
                    tz = zoneinfo.ZoneInfo(pref.timezone)
                    timezone.activate(tz)
                else:
                    timezone.deactivate()
            except Exception:
                timezone.deactivate()
        else:
            timezone.deactivate()

        return self.get_response(request)
