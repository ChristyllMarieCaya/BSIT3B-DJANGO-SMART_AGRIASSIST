"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.core.admin_portal import (
    admin_notifications_status_view,
    admin_notifications_view,
    admin_settings_view,
    admin_weather_view,
    admin_user_portfolio_view,
    admin_ai_assistant_view,
)

urlpatterns = [
    path('admin/notifications/', admin_notifications_view, name='admin_notifications'),
    path('admin/notifications/status/', admin_notifications_status_view, name='admin_notifications_status'),
    path('admin/weather/', admin_weather_view, name='admin_weather'),
    path('admin/settings/', admin_settings_view, name='admin_settings'),
    path('admin/users/<int:user_id>/', admin_user_portfolio_view, name='admin_user_portfolio'),
    path('admin/ai-assistant/', admin_ai_assistant_view, name='admin_ai_assistant'),
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
    path('info/', include('apps.info.urls')),
    path('catalog/', include('apps.catalog.urls')),
    path('crops/', include('apps.crops.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)