"""Staff-only weather and account settings pages for the administration portal."""

import logging
from datetime import date, timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.db.models import Avg, Q, Sum
from django.http import JsonResponse
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode, url_has_allowed_host_and_scheme

from apps.crops.models import Crop, ScheduledReminder
from apps.core.models import Conversation, Message, CropDiagnosis
from apps.core.weather import geocode_location, get_weather, get_weather_history
from apps.info.models import Notification, UserPreference, WeatherAlert, WeatherRecord

logger = logging.getLogger(__name__)
User = get_user_model()
NOTIFICATION_FILTERS = {'all', 'unread', 'critical', 'resolved'}
NOTIFICATION_SEVERITY_ORDER = {
    'critical': 0,
    'high': 1,
    'warning': 1,
    'watch': 2,
    'advisory': 3,
    'normal': 4,
    'info': 5,
    'low': 6,
}
NOTIFICATION_SEVERITY_LABELS = {
    'critical': 'Critical',
    'high': 'Warning',
    'normal': 'Informational',
    'low': 'Informational',
}


def _admin_notification_queryset():
    return Notification.objects.filter(deleted_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )


def admin_notifications_page(request):
    """Provide staff a read-only notification center with session-only dismissals."""
    if request.method == 'POST':
        kind = request.POST.get('kind', '')
        try:
            record_id = int(request.POST.get('record_id', ''))
        except (TypeError, ValueError):
            messages.error(request, 'That notification could not be dismissed.')
            return redirect('admin_notifications')

        if kind != 'notification':
            messages.error(request, 'Active weather alerts remain listed until their source records are resolved.')
            return redirect('admin_notifications')
        exists = _admin_notification_queryset().filter(pk=record_id).exists()
        if not exists:
            messages.error(request, 'That notification is no longer available.')
            return redirect('admin_notifications')

        dismissed = set(request.session.get('dismissed_admin_notification_ids', []))
        dismissed.add(f'{kind}:{record_id}')
        request.session['dismissed_admin_notification_ids'] = sorted(dismissed)
        messages.success(request, 'Notification dismissed for this session. Its underlying record was not changed.')
        filter_name = request.POST.get('filter', 'all')
        destination = reverse('admin_notifications')
        if filter_name in NOTIFICATION_FILTERS:
            destination = f'{destination}?{urlencode({"filter": filter_name})}'
        return redirect(destination)
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)

    filter_name = request.GET.get('filter', 'all')
    if filter_name not in NOTIFICATION_FILTERS:
        filter_name = 'all'
    dismissed = set(request.session.get('dismissed_admin_notification_ids', []))
    notifications = list(_admin_notification_queryset().select_related('user').order_by('-created_at'))
    alerts = list(WeatherAlert.objects.select_related('user').order_by('-created_at'))
    entries = []

    for notification in notifications:
        if filter_name == 'unread' and notification.read:
            continue
        if filter_name == 'critical' and notification.priority != Notification.Priority.CRITICAL:
            continue
        if filter_name == 'resolved':
            continue
        notification_url = notification.related_url
        if not notification_url or not url_has_allowed_host_and_scheme(
            notification_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            notification_url = reverse('admin_notifications')
        location = notification.metadata.get('location', '') if isinstance(notification.metadata, dict) else ''
        entries.append({
            'key': f'notification:{notification.pk}',
            'kind': 'notification',
            'record_id': notification.pk,
            'title': notification.title,
            'description': notification.message,
            'severity': NOTIFICATION_SEVERITY_LABELS.get(
                notification.priority,
                notification.get_priority_display(),
            ),
            'severity_key': notification.priority,
            'location': location,
            'username': notification.user.username,
            'created_at': notification.created_at,
            'is_read': notification.read,
            'is_active': True,
            'url': notification_url,
        })

    for alert in alerts:
        if filter_name == 'unread' and not alert.is_active:
            continue
        if filter_name == 'critical' and alert.severity != WeatherAlert.Severity.CRITICAL:
            continue
        if filter_name == 'resolved' and alert.is_active:
            continue
        entries.append({
            'key': f'weather:{alert.pk}',
            'kind': 'weather',
            'record_id': alert.pk,
            'title': alert.title,
            'description': alert.agricultural_impact or alert.forecast_condition,
            'severity': alert.get_severity_display(),
            'severity_key': alert.severity,
            'location': alert.farm_location,
            'username': alert.user.username,
            'created_at': alert.created_at,
            'is_read': not alert.is_active,
            'is_active': alert.is_active,
            'url': f"{reverse('admin_weather')}?{urlencode({'location': alert.farm_location})}",
        })

    entries.sort(key=lambda entry: entry['created_at'], reverse=True)
    entries.sort(key=lambda entry: NOTIFICATION_SEVERITY_ORDER.get(entry['severity_key'], 7))
    visible_entries = [entry for entry in entries if entry['key'] not in dismissed]
    page_obj = Paginator(visible_entries, 25).get_page(request.GET.get('page'))
    unread_count = _admin_notification_queryset().filter(read=False).count()
    active_alerts = WeatherAlert.objects.filter(is_active=True)
    return render(request, 'admin/notifications.html', {
        'notifications': page_obj,
        'filter_name': filter_name,
        'filter_choices': (
            ('all', 'All'),
            ('unread', 'Unread'),
            ('critical', 'Critical'),
            ('resolved', 'Resolved'),
        ),
        'unread_notification_count': unread_count,
        'active_weather_count': active_alerts.count(),
        'critical_weather_count': active_alerts.filter(severity=WeatherAlert.Severity.CRITICAL).count(),
    })


def admin_notifications_status(request):
    """Return minimal real-time Admin notification counts for the shared Admin shell."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)
    now = timezone.now()
    notifications = Notification.objects.filter(deleted_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    alerts = WeatherAlert.objects.filter(is_active=True)
    return JsonResponse({
        'unread_notifications': notifications.filter(read=False).count(),
        'active_alerts': alerts.count(),
        'critical_alerts': alerts.filter(severity=WeatherAlert.Severity.CRITICAL).count(),
        'latest_notification_id': notifications.order_by('-created_at').values_list('pk', flat=True).first(),
        'latest_alert_id': alerts.order_by('-created_at').values_list('pk', flat=True).first(),
        'latest_notification_title': notifications.order_by('-created_at').values_list('title', flat=True).first(),
        'latest_alert_title': alerts.order_by('-created_at').values_list('title', flat=True).first(),
    })


class AdminProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This email address is already associated with another account.')
        return email


class AdminPreferencesForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = (
            'country',
            'preferred_language',
            'timezone',
            'channel_in_app',
            'channel_browser',
            'channel_email',
            'channel_sms',
        )
        widgets = {
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'preferred_language': forms.TextInput(attrs={'class': 'form-control'}),
            'timezone': forms.TextInput(attrs={'class': 'form-control'}),
            'channel_in_app': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'channel_browser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'channel_email': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'channel_sms': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AdminThemeForm(forms.Form):
    theme = forms.ChoiceField(
        choices=(('light', 'Light'), ('dark', 'Dark')),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class WeatherRecordChartForm(forms.ModelForm):
    class Meta:
        model = WeatherRecord
        fields = ('temperature', 'rainfall')
        widgets = {
            'temperature': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'inputmode': 'decimal',
            }),
            'rainfall': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'inputmode': 'decimal',
            }),
        }


def admin_weather_page(request):
    """Show live Open-Meteo data, farm weather history, and active alerts to staff."""
    location_values = set(
        WeatherRecord.objects.exclude(location='').values_list('location', flat=True)
    )
    location_values.update(
        Crop.objects.exclude(farm_location='').values_list('farm_location', flat=True)
    )
    location_values.update(
        UserPreference.objects.exclude(farm_location='').values_list('farm_location', flat=True)
    )
    locations = sorted(location_values, key=str.casefold)

    today = timezone.localdate()
    default_start = today - timedelta(days=29)
    filters = request.POST if request.method == 'POST' else request.GET
    location = filters.get('location', '').strip()[:255]
    if not location and locations:
        location = locations[0]

    start_date = default_start
    end_date = today
    date_error = ''
    try:
        if filters.get('start_date'):
            start_date = date.fromisoformat(filters['start_date'])
        if filters.get('end_date'):
            end_date = date.fromisoformat(filters['end_date'])
        if end_date < start_date:
            raise ValueError('End date must be on or after the start date.')
        if (end_date - start_date).days > 365:
            raise ValueError('Choose a date range of 366 days or fewer.')
    except ValueError as exc:
        date_error = str(exc)
        start_date = default_start
        end_date = today

    if request.method == 'POST':
        redirect_url = reverse('admin_weather')
        redirect_query = urlencode({
            'location': location,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        })
        if request.POST.get('action') != 'update_weather_record':
            messages.error(request, 'That weather record could not be updated.')
            return redirect(f'{redirect_url}?{redirect_query}')
        if not request.user.has_perm('info.change_weatherrecord'):
            messages.error(request, 'You do not have permission to change weather records.')
            return redirect(f'{redirect_url}?{redirect_query}')
        try:
            record_id = int(request.POST.get('record_id', ''))
        except (TypeError, ValueError):
            messages.error(request, 'Choose a valid weather record to update.')
            return redirect(f'{redirect_url}?{redirect_query}')

        record = get_object_or_404(
            WeatherRecord,
            pk=record_id,
            location__iexact=location,
            recorded_on__gte=start_date,
            recorded_on__lte=end_date,
        )
        form = WeatherRecordChartForm(
            request.POST,
            instance=record,
            prefix=f'weather-{record.pk}',
        )
        if form.is_valid():
            record = form.save(commit=False)
            record.notes = 'Manually edited in Admin Weather & Alerts.'
            record.save()
            messages.success(
                request,
                f'Weather observations for {record.recorded_on:%b %d, %Y} were saved. The charts have been updated.',
            )
        else:
            messages.error(request, f'Weather record was not saved: {form.errors.as_text()}')
        return redirect(f'{redirect_url}?{redirect_query}')

    records = WeatherRecord.objects.none()
    alerts = WeatherAlert.objects.none()
    weather_data = None
    weather_error = ''
    live_updated_at = None
    weather_record_count = 0
    chart = {'labels': [], 'temperature': [], 'rainfall': []}
    if location:
        records = WeatherRecord.objects.filter(
            location__iexact=location,
            recorded_on__gte=start_date,
            recorded_on__lte=end_date,
        )
        weather_record_count = records.count()
        daily = {
            entry['recorded_on']: entry
            for entry in records.values('recorded_on').annotate(
                temperature=Avg('temperature'),
                rainfall=Sum('rainfall'),
            )
        }
        chart_days = [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        ]
        chart = {
            'labels': [day.strftime('%b %d') for day in chart_days],
            'temperature': [
                float(daily[day]['temperature'])
                if day in daily and daily[day]['temperature'] is not None
                else None
                for day in chart_days
            ],
            'rainfall': [
                float(daily[day]['rainfall'])
                if day in daily and daily[day]['rainfall'] is not None
                else None
                for day in chart_days
            ],
        }
        records = records.select_related('owner').order_by('-recorded_on')[:50]
        weather_record_rows = [
            {
                'record': record,
                'form': WeatherRecordChartForm(
                    instance=record,
                    prefix=f'weather-{record.pk}',
                ),
            }
            for record in records
        ]
        alerts = WeatherAlert.objects.filter(
            is_active=True,
            farm_location__iexact=location,
        ).select_related('user').order_by('-created_at')[:50]

        coordinates = UserPreference.objects.filter(
            farm_location__iexact=location,
            latitude__isnull=False,
            longitude__isnull=False,
        ).values_list('latitude', 'longitude').first()
        try:
            if coordinates:
                latitude, longitude = map(float, coordinates)
            else:
                geocoded = geocode_location(location)
                if not geocoded:
                    weather_error = f'Could not locate "{location}" using Open-Meteo geocoding.'
                    geocoded = None
                if geocoded:
                    latitude = geocoded['latitude']
                    longitude = geocoded['longitude']
            if not weather_error:
                weather_data = get_weather(
                    latitude,
                    longitude,
                    units='metric',
                    location_name=location,
                )
                if not weather_data.get('available'):
                    weather_error = weather_data.get('error') or 'Live weather is currently unavailable.'
                else:
                    live_updated_at = timezone.now()

                # Use API history only where no saved observation exists for that metric.
                has_missing_history = any(
                    value is None for value in chart['temperature'] + chart['rainfall']
                )
                if has_missing_history:
                    history_result = get_weather_history(
                        latitude,
                        longitude,
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        units='metric',
                    )
                    if history_result.get('available'):
                        hist_daily = history_result.get('daily', {})
                        for idx, day in enumerate(chart_days):
                            day_key = day.isoformat()
                            if day_key not in hist_daily:
                                continue
                            if chart['temperature'][idx] is None:
                                chart['temperature'][idx] = hist_daily[day_key]['temperature']
                            if chart['rainfall'][idx] is None:
                                chart['rainfall'][idx] = hist_daily[day_key]['rainfall']
        except Exception:
            logger.exception('Unable to load Admin weather for location %s.', location)
            weather_error = 'Live weather could not be loaded. Please try again later.'

    return render(request, 'admin/weather.html', {
        'locations': locations,
        'selected_location': location,
        'start_date': start_date,
        'end_date': end_date,
        'date_error': date_error,
        'weather': weather_data,
        'weather_error': weather_error,
        'live_updated_at': live_updated_at,
        'weather_records': records,
        'weather_record_rows': weather_record_rows if location else [],
        'weather_record_count': weather_record_count,
        'weather_alerts': alerts,
        'history_chart': chart,
        'weather_source': 'Open-Meteo',
        'can_add_weather_record': request.user.has_perm('info.add_weatherrecord'),
        'can_change_weather_record': request.user.has_perm('info.change_weatherrecord'),
        'weather_records_url': reverse('admin:info_weatherrecord_changelist'),
        'weather_record_add_url': reverse('admin:info_weatherrecord_add'),
        'weather_alerts_url': reverse('admin:info_weatheralert_changelist'),
    })


def admin_settings_page(request):
    """Let staff manage their own account, preferences, and password securely."""
    preference, _created = UserPreference.objects.get_or_create(user=request.user)
    profile_form = AdminProfileForm(instance=request.user)
    preferences_form = AdminPreferencesForm(instance=preference)
    saved_theme = request.COOKIES.get('smart_admin_theme', 'light')
    if saved_theme not in {'light', 'dark'}:
        saved_theme = 'light'
    theme_form = AdminThemeForm(initial={'theme': saved_theme})
    password_form = PasswordChangeForm(user=request.user, prefix='password')
    for field in password_form.fields.values():
        field.widget.attrs['class'] = 'form-control'

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'profile':
            profile_form = AdminProfileForm(request.POST, instance=request.user)
            preferences_form = AdminPreferencesForm(request.POST, instance=preference)
            if profile_form.is_valid() and preferences_form.is_valid():
                profile_form.save()
                preferences_form.save()
                messages.success(request, 'Your account settings have been saved.')
                return redirect('admin_settings')
        elif action == 'theme':
            theme_form = AdminThemeForm(request.POST)
            if theme_form.is_valid():
                response = redirect('admin_settings')
                response.set_cookie(
                    'smart_admin_theme',
                    theme_form.cleaned_data['theme'],
                    max_age=31536000,
                    path='/admin/',
                    secure=request.is_secure(),
                    httponly=False,
                    samesite='Lax',
                )
                messages.success(request, 'Your Admin appearance preference has been saved.')
                return response
        elif action == 'password':
            password_form = PasswordChangeForm(
                user=request.user,
                data=request.POST,
                prefix='password',
            )
            for field in password_form.fields.values():
                field.widget.attrs['class'] = 'form-control'
            if password_form.is_valid():
                updated_user = password_form.save()
                update_session_auth_hash(request, updated_user)
                messages.success(request, 'Your password has been changed.')
                return redirect('admin_settings')
        else:
            messages.error(request, 'Choose a valid settings action.')

    return render(request, 'admin/settings.html', {
        'profile_form': profile_form,
        'preferences_form': preferences_form,
        'theme_form': theme_form,
        'password_form': password_form,
    })


admin_weather_view = admin.site.admin_view(admin_weather_page)
admin_settings_view = admin.site.admin_view(admin_settings_page)
admin_notifications_view = admin.site.admin_view(admin_notifications_page)
admin_notifications_status_view = admin.site.admin_view(admin_notifications_status)


def admin_user_portfolio_page(request, user_id):
    """Staff-only Farmer Portfolio view unifying user accounts, registered crops,
    growth progress, scheduled reminders, AI diagnoses, and activity timeline."""
    target_user = get_object_or_404(User, pk=user_id)

    # Handle authorized account status toggle
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle_status':
            if target_user == request.user:
                messages.error(request, 'You cannot modify your own administrative account status.')
            else:
                target_user.is_active = not target_user.is_active
                target_user.save(update_fields=['is_active'])
                new_status = 'activated' if target_user.is_active else 'deactivated'
                messages.success(request, f'Account @{target_user.username} successfully {new_status}.')
            return redirect('admin_user_portfolio', user_id=target_user.pk)
        messages.error(request, 'Unsupported administrative action.')
        return redirect('admin_user_portfolio', user_id=target_user.pk)

    # Fetch verified related data
    preference = UserPreference.objects.filter(user=target_user).first()
    crops = list(target_user.registered_crops.all().order_by('-planting_date'))
    reminders = list(target_user.reminders.all().select_related('crop').order_by('due_date'))
    diagnoses = list(target_user.crop_diagnoses.all().order_by('-created_at'))
    conversations = list(target_user.conversations.all().order_by('-started_at')[:8])
    weather_alerts = list(WeatherAlert.objects.filter(user=target_user, is_active=True).order_by('-created_at')[:6])

    # Aggregated metrics (using actual database counts & sums)
    total_crops_count = len(crops)
    active_crops_count = sum(1 for c in crops if c.status == Crop.Status.ACTIVE)
    harvested_crops_count = sum(1 for c in crops if c.status == Crop.Status.HARVESTED)
    total_area_sqm = sum(float(c.area_sqm or 0) for c in crops)
    total_area_ha = round(total_area_sqm / 10000.0, 2)

    total_reminders_count = len(reminders)
    pending_reminders_count = sum(1 for r in reminders if r.status == ScheduledReminder.Status.PENDING)
    completed_reminders_count = sum(1 for r in reminders if r.status == ScheduledReminder.Status.COMPLETED)
    overdue_reminders_count = sum(1 for r in reminders if r.is_overdue)

    total_diagnoses_count = len(diagnoses)
    confirmed_diagnoses_count = sum(1 for d in diagnoses if d.is_confirmed)
    unconfirmed_diagnoses_count = total_diagnoses_count - confirmed_diagnoses_count

    total_conversations_count = target_user.conversations.count()
    total_messages_count = Message.objects.filter(sender=target_user).count()

    # Farm and land identification
    farm_name = preference.farm_name if (preference and preference.farm_name) else ''
    farm_location = preference.farm_location if (preference and preference.farm_location) else ''
    if not farm_location and crops:
        farm_location = next((c.farm_location for c in crops if c.farm_location), '')
    if not farm_name and crops:
        field_or_crop = crops[0].field_name or crops[0].crop_name
        farm_name = f"{target_user.first_name or target_user.username}'s Plot ({field_or_crop})"
    elif not farm_name:
        farm_name = f"{target_user.first_name or target_user.username}'s Farm"

    coordinates = None
    if preference and preference.latitude and preference.longitude:
        coordinates = f"{preference.latitude}, {preference.longitude}"

    weather_monitoring = preference.weather_monitoring_enabled if preference else True

    # Real chronological activity timeline
    events = []
    if target_user.date_joined:
        events.append({
            'type': 'user',
            'badge': 'Account Created',
            'icon': 'fa-solid fa-user-plus',
            'color': 'success',
            'title': 'Account registered on Smart AgriAssist',
            'details': f'Initial role: {"Administrator" if target_user.is_staff else "Farmer"}',
            'timestamp': target_user.date_joined,
            'url': None,
        })
    if target_user.last_login:
        events.append({
            'type': 'login',
            'badge': 'User Login',
            'icon': 'fa-solid fa-arrow-right-to-bracket',
            'color': 'info',
            'title': 'User session authenticated',
            'details': f'Recorded at {target_user.last_login:%Y-%m-%d %H:%M}',
            'timestamp': target_user.last_login,
            'url': None,
        })
    for crop in crops:
        events.append({
            'type': 'crop',
            'badge': 'Crop Registered',
            'icon': 'fa-solid fa-wheat-awn',
            'color': 'success',
            'title': f'Planted {crop.crop_name} ({crop.variety or "Standard"})',
            'details': f'Field: {crop.field_name or "Plot 1"} • Area: {crop.area_sqm} m²',
            'timestamp': crop.created_at,
            'url': reverse('admin:crops_crop_change', args=[crop.pk]),
        })
    for rem in reminders:
        events.append({
            'type': 'reminder',
            'badge': 'Reminder Scheduled',
            'icon': 'fa-regular fa-clock',
            'color': 'warning',
            'title': rem.title,
            'details': f'Due on {rem.due_date:%Y-%m-%d} • {rem.get_activity_type_display()}',
            'timestamp': rem.created_at,
            'url': reverse('admin:crops_scheduledreminder_change', args=[rem.pk]),
        })
        if rem.completed_at:
            events.append({
                'type': 'reminder_done',
                'badge': 'Reminder Completed',
                'icon': 'fa-solid fa-circle-check',
                'color': 'success',
                'title': f'Completed: {rem.title}',
                'details': f'Activity fulfilled on schedule',
                'timestamp': rem.completed_at,
                'url': reverse('admin:crops_scheduledreminder_change', args=[rem.pk]),
            })
    for diag in diagnoses:
        events.append({
            'type': 'diagnosis',
            'badge': 'AI Diagnosis',
            'icon': 'fa-solid fa-stethoscope',
            'color': 'primary',
            'title': f'AI Diagnosis: {diag.possible_disease}',
            'details': f'Crop: {diag.crop_name or "Field sample"} • Confidence: {diag.confidence_level}',
            'timestamp': diag.created_at,
            'url': reverse('admin:core_cropdiagnosis_change', args=[diag.pk]),
        })
    events.sort(key=lambda e: e['timestamp'], reverse=True)
    timeline_events = events[:25]

    context = {
        'target_user': target_user,
        'preference': preference,
        'farm_name': farm_name,
        'farm_location': farm_location,
        'coordinates': coordinates,
        'weather_monitoring': weather_monitoring,
        'crops': crops,
        'total_crops_count': total_crops_count,
        'active_crops_count': active_crops_count,
        'harvested_crops_count': harvested_crops_count,
        'total_area_sqm': total_area_sqm,
        'total_area_ha': total_area_ha,
        'reminders': reminders,
        'total_reminders_count': total_reminders_count,
        'pending_reminders_count': pending_reminders_count,
        'completed_reminders_count': completed_reminders_count,
        'overdue_reminders_count': overdue_reminders_count,
        'diagnoses': diagnoses,
        'total_diagnoses_count': total_diagnoses_count,
        'confirmed_diagnoses_count': confirmed_diagnoses_count,
        'unconfirmed_diagnoses_count': unconfirmed_diagnoses_count,
        'conversations': conversations,
        'total_conversations_count': total_conversations_count,
        'total_messages_count': total_messages_count,
        'weather_alerts': weather_alerts,
        'timeline_events': timeline_events,
        'title': f'Farmer Portfolio: {target_user.get_full_name() or target_user.username}',
        **admin.site.each_context(request),
    }
    return render(request, 'admin/users/portfolio.html', context)


def admin_ai_assistant_page(request):
    """Staff-only AI Assistant service status, telemetry, model configuration, and diagnosis logs."""
    from apps.core.gemini import (
        api_key_configured,
        connection_status,
        model_name,
        request_timeout_seconds,
        connect_timeout_seconds,
        max_retries,
    )

    force_refresh = request.GET.get('refresh') == '1'
    status_result = connection_status(force=force_refresh)
    is_configured = api_key_configured()

    raw_key = os.environ.get('GEMINI_API_KEY', '')
    masked_key = f"{raw_key[:4]}...{raw_key[-4:]}" if len(raw_key) > 8 else ("Configured" if is_configured else "Not Configured")

    total_conversations = Conversation.objects.count()
    total_messages = Message.objects.count()
    total_diagnoses = CropDiagnosis.objects.count()
    confirmed_diagnoses = CropDiagnosis.objects.filter(is_confirmed=True).count()
    pending_diagnoses = total_diagnoses - confirmed_diagnoses

    recent_diagnoses = CropDiagnosis.objects.select_related('user').order_by('-created_at')[:8]
    recent_conversations = Conversation.objects.select_related('owner').order_by('-started_at')[:8]

    context = {
        'title': 'AI Assistant Configuration',
        'is_configured': is_configured,
        'masked_key': masked_key,
        'active_model': model_name(),
        'request_timeout': request_timeout_seconds(),
        'connect_timeout': connect_timeout_seconds(),
        'max_retries': max_retries(),
        'status_result': status_result,
        'total_conversations': total_conversations,
        'total_messages': total_messages,
        'total_diagnoses': total_diagnoses,
        'confirmed_diagnoses': confirmed_diagnoses,
        'pending_diagnoses': pending_diagnoses,
        'recent_diagnoses': recent_diagnoses,
        'recent_conversations': recent_conversations,
        **admin.site.each_context(request),
    }
    return render(request, 'admin/ai_assistant.html', context)


admin_user_portfolio_view = admin.site.admin_view(admin_user_portfolio_page)
admin_ai_assistant_view = admin.site.admin_view(admin_ai_assistant_page)
