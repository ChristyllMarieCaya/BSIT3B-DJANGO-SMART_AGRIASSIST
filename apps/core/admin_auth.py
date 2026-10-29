"""Dedicated administrative authentication, role resolution, and portal routing services."""

from typing import Optional
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

User = get_user_model()

ADMIN_PORTAL_URL = '/admin/'
DEFAULT_USER_DASHBOARD_URL = 'dashboard'


def is_admin_user(user) -> bool:
    """Check if the provided user has administrative / staff privileges."""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_staff or user.is_superuser)


def get_admin_portal_url() -> str:
    """Return the base URL for the Django administration portal."""
    return getattr(settings, 'ADMIN_URL', ADMIN_PORTAL_URL)


def resolve_post_login_redirect(user, request: HttpRequest, next_url: Optional[str] = None) -> str:
    """Determine the destination URL after a successful login based on role and next parameter.

    Rules:
    1. If a valid, safe ?next= URL is provided, redirect to that URL.
    2. If the user is staff or superuser (admin), redirect to Django Admin portal (/admin/).
    3. If the user is a standard farm user, redirect to their user dashboard (/home/).
    """
    # 1. Check for valid ?next= parameter
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    # 2. Check for administrative role
    if is_admin_user(user):
        return get_admin_portal_url()

    # 3. Default to farm dashboard
    return DEFAULT_USER_DASHBOARD_URL


def get_login_context(request: HttpRequest) -> dict:
    """Provide administrative portal context variables to login templates."""
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    return {
        'admin_portal_url': get_admin_portal_url(),
        'next': next_url,
        'has_admin_redirect': bool(next_url and next_url.startswith(get_admin_portal_url())),
    }

