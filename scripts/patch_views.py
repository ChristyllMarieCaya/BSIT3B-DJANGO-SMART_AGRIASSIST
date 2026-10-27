from pathlib import Path

target = Path('apps/core/views.py')
with open(target, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update imports
old_imp = """from apps.core.models import Message"""
new_imp = """from apps.core.models import Conversation, CropDiagnosis, Message
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import WeatherAlert"""
assert old_imp in text, "old_imp not found"
text = text.replace(old_imp, new_imp)

# 2. Update home view
old_home_block = """    weather_available = weather_data.get('available', False)
    weather_current = weather_data.get('current')
    weather_forecast = weather_data.get('forecast', [])[:3]
    weather_location = weather_data.get('location', location or 'Not set')
    weather_error = weather_data.get('error', '')

    from datetime import datetime
    if weather_data.get('updated_at'):
        weather_updated = datetime.fromtimestamp(weather_data['updated_at']).strftime('%b %d, %H:%M')
    else:
        weather_updated = 'Not available'

    # Recent notifications
    recent_notifications = Notification.objects.filter(
        user=request.user,
        deleted_at__isnull=True,
    ).order_by('-created_at')[:3]

    return render(request, 'home.html', {
        'total_crops': total_crops,
        'ai_status': ai_status,
        'ai_status_text': ai_status_text,
        'ai_available': ai_available,
        'weather_configured': weather_configured(),
        'weather_available': weather_available,
        'weather_current': weather_current,
        'weather_forecast': weather_forecast,
        'weather_location': weather_location,
        'weather_updated': weather_updated,
        'weather_error': weather_error,
        'weather_source': 'OpenWeatherMap' if weather_configured() else 'Not configured',
        'recent_notifications': recent_notifications,
    })"""

new_home_block = """    weather_available = weather_data.get('available', False)
    weather_current = weather_data.get('current')
    weather_forecast = weather_data.get('forecast', [])[:3]
    weather_location = weather_data.get('location', location or 'Not set')
    weather_error = weather_data.get('error', '')

    from datetime import datetime
    if weather_data.get('updated_at'):
        weather_updated = datetime.fromtimestamp(weather_data['updated_at']).strftime('%b %d, %H:%M')
    else:
        weather_updated = 'Not available'

    # Registered Active Crops with calculated stages
    active_crops = list(Crop.objects.filter(owner=request.user, status=Crop.Status.ACTIVE)[:4])
    total_active_crops = Crop.objects.filter(owner=request.user, status=Crop.Status.ACTIVE).count()

    # Active severe weather alerts
    active_weather_alerts = list(WeatherAlert.objects.filter(user=request.user, is_active=True).order_by('-created_at')[:3])

    # Upcoming farming activities & reminders
    upcoming_reminders = list(
        ScheduledReminder.objects.filter(
            user=request.user,
            status__in=[ScheduledReminder.Status.PENDING, ScheduledReminder.Status.OVERDUE]
        ).select_related('crop').order_by('due_date')[:5]
    )

    # Recent Crop Diagnoses
    recent_diagnoses = list(CropDiagnosis.objects.filter(user=request.user).order_by('-created_at')[:4])

    # Recent Chat Conversations
    recent_conversations = list(Conversation.objects.filter(owner=request.user).order_by('-started_at')[:4])

    # Recent notifications
    recent_notifications = Notification.objects.filter(
        user=request.user,
        deleted_at__isnull=True,
    ).order_by('-created_at')[:4]

    return render(request, 'home.html', {
        'total_crops': total_crops,
        'total_active_crops': total_active_crops,
        'active_crops': active_crops,
        'active_weather_alerts': active_weather_alerts,
        'upcoming_reminders': upcoming_reminders,
        'recent_diagnoses': recent_diagnoses,
        'recent_conversations': recent_conversations,
        'ai_status': ai_status,
        'ai_status_text': ai_status_text,
        'ai_available': ai_available,
        'weather_configured': weather_configured(),
        'weather_available': weather_available,
        'weather_current': weather_current,
        'weather_forecast': weather_forecast,
        'weather_location': weather_location,
        'weather_updated': weather_updated,
        'weather_error': weather_error,
        'weather_source': 'OpenWeatherMap' if weather_configured() else 'Agro-Met Dev Mode',
        'recent_notifications': recent_notifications,
    })"""
assert old_home_block in text, "old_home_block not found"
text = text.replace(old_home_block, new_home_block)

# 3. Update _chat_view to save CropDiagnosis
old_chat_save = """            add_message(conversation, None, reply, reply_to=user_message)
            touch_last_message(conversation)"""

new_chat_save = """            add_message(conversation, None, reply, reply_to=user_message)
            touch_last_message(conversation)
            if image_file is not None:
                from apps.core.gemini import save_crop_diagnosis_from_reply
                save_crop_diagnosis_from_reply(
                    user=request.user,
                    conversation=conversation,
                    user_message=user_message,
                    reply_text=reply,
                    image_file=image_file,
                )"""
assert old_chat_save in text, "old_chat_save not found"
text = text.replace(old_chat_save, new_chat_save)

# 4. Add conversation management and diagnosis views
new_endpoints = """
@login_required(login_url='login')
@require_POST
def chat_new_conversation(request):
    \"\"\"Start a fresh conversation with the Agri AI Assistant.\"\"\"
    conversation = create_conversation(request.user)
    return JsonResponse({
        'status': 'success',
        'conversation_id': conversation.id,
        'started_at': conversation.started_at.isoformat(),
    })


@login_required(login_url='login')
@require_POST
def chat_delete_conversation(request, conversation_id):
    \"\"\"Delete a conversation and its messages.\"\"\"
    conversation = get_conversation(request.user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Conversation not found.'}, status=404)
    conversation.delete()
    return JsonResponse({'status': 'success', 'deleted_id': conversation_id})


@login_required(login_url='login')
@require_POST
def chat_clear_conversation(request, conversation_id):
    \"\"\"Clear all messages inside a conversation.\"\"\"
    conversation = get_conversation(request.user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Conversation not found.'}, status=404)
    conversation.messages.all().delete()
    conversation.last_message_at = None
    conversation.save(update_fields=['last_message_at'])
    return JsonResponse({'status': 'success', 'cleared_id': conversation_id})


@login_required(login_url='login')
def diagnoses_list(request):
    \"\"\"List all recorded image-based crop diagnoses for this user.\"\"\"
    diagnoses = CropDiagnosis.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'users/diagnoses_list.html', {'diagnoses': diagnoses})


@login_required(login_url='login')
def diagnosis_detail(request, pk):
    \"\"\"Detail view of an individual crop health and disease diagnosis.\"\"\"
    from django.shortcuts import get_object_or_404
    diagnosis = get_object_or_404(CropDiagnosis, pk=pk, user=request.user)
    return render(request, 'users/diagnosis_detail.html', {'diagnosis': diagnosis})
"""

# Insert new endpoints right after chat_view
target_chat_end = "return JsonResponse({\n        'reply': reply,\n        'conversation_id': conversation.id,\n        'user_message_id': user_message.id,\n        'has_image': image_file is not None,\n    })"
assert target_chat_end in text, "target_chat_end not found"
text = text.replace(target_chat_end, target_chat_end + '\n' + new_endpoints)

# 5. Update settings_save
old_settings_save = """@login_required(login_url='login')
@require_http_methods(['POST'])
def settings_save(request):
    \"\"\"Save user preferences.\"\"\"
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    pref.farm_name = request.POST.get('farm_name', '').strip()
    pref.farm_location = request.POST.get('farm_location', '').strip()
    pref.temperature_unit = request.POST.get('temperature_unit', 'celsius')
    forecast_days = request.POST.get('forecast_days', '5')
    try:
        pref.forecast_days = int(forecast_days)
    except (TypeError, ValueError):
        pref.forecast_days = 5
    pref.weather_alerts_enabled = request.POST.get('weather_alerts_enabled') == 'on'
    pref.crop_care_reminders_enabled = request.POST.get('crop_care_reminders_enabled') == 'on'
    pref.pest_disease_advisories_enabled = request.POST.get('pest_disease_advisories_enabled') == 'on'
    pref.ai_analysis_notifications_enabled = request.POST.get('ai_analysis_notifications_enabled') == 'on'
    pref.agricultural_recommendations_enabled = request.POST.get('agricultural_recommendations_enabled') == 'on'
    pref.application_notices_enabled = request.POST.get('application_notices_enabled') == 'on'
    pref.ai_response_language = request.POST.get('ai_response_language', 'en')
    pref.ai_response_style = request.POST.get('ai_response_style', 'practical')
    pref.theme = request.POST.get('theme', 'light')
    pref.save()

    # Create a notification about settings saved
    if pref.application_notices_enabled:
        Notification.objects.create(
            user=request.user,
            title='Settings updated',
            message='Your farm preferences have been saved successfully.',
            category=Notification.Category.NOTICE,
            priority=Notification.Priority.NORMAL,
        )

    return JsonResponse({'status': 'ok', 'message': 'Settings saved successfully.'})"""

new_settings_save = """@login_required(login_url='login')
@require_http_methods(['POST'])
def settings_save(request):
    \"\"\"Save comprehensive farm, AI assistant, weather thresholds, and reminder preferences.\"\"\"
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    # 1. Farm profile & GPS coordinates
    pref.farm_name = request.POST.get('farm_name', pref.farm_name).strip()
    pref.farm_location = request.POST.get('farm_location', pref.farm_location).strip()
    lat_raw = request.POST.get('latitude', '').strip()
    lon_raw = request.POST.get('longitude', '').strip()
    if lat_raw:
        try:
            pref.latitude = float(lat_raw)
        except ValueError:
            pass
    if lon_raw:
        try:
            pref.longitude = float(lon_raw)
        except ValueError:
            pass

    # 2. General & Language
    pref.preferred_language = request.POST.get('preferred_language', pref.preferred_language).strip()
    pref.timezone = request.POST.get('timezone', pref.timezone).strip()
    pref.measurement_units = request.POST.get('measurement_units', pref.measurement_units).strip()
    pref.temperature_unit = request.POST.get('temperature_unit', pref.temperature_unit).strip()
    try:
        pref.forecast_days = int(request.POST.get('forecast_days', pref.forecast_days))
    except (TypeError, ValueError):
        pass

    # 3. AI Assistant Settings
    pref.ai_response_language = request.POST.get('ai_response_language', pref.preferred_language)
    pref.ai_response_detail = request.POST.get('ai_response_detail', pref.ai_response_detail)
    pref.enable_conversation_history = request.POST.get('enable_conversation_history') in ('on', 'true', '1')

    # 4. Weather Monitoring & Alert Thresholds
    pref.weather_monitoring_enabled = request.POST.get('weather_monitoring_enabled') in ('on', 'true', '1')
    pref.weather_alerts_enabled = request.POST.get('weather_alerts_enabled') in ('on', 'true', '1')
    pref.weather_alert_min_severity = request.POST.get('weather_alert_min_severity', pref.weather_alert_min_severity)
    try:
        pref.weather_update_frequency_hours = int(request.POST.get('weather_update_frequency_hours', pref.weather_update_frequency_hours))
        pref.rain_alert_threshold_mm = float(request.POST.get('rain_alert_threshold_mm', pref.rain_alert_threshold_mm))
        pref.wind_alert_threshold_kmh = float(request.POST.get('wind_alert_threshold_kmh', pref.wind_alert_threshold_kmh))
        pref.temp_high_threshold_c = float(request.POST.get('temp_high_threshold_c', pref.temp_high_threshold_c))
        pref.temp_low_threshold_c = float(request.POST.get('temp_low_threshold_c', pref.temp_low_threshold_c))
    except (TypeError, ValueError):
        pass

    # 5. Notification Channels & Quiet Hours
    pref.channel_in_app = request.POST.get('channel_in_app') in ('on', 'true', '1')
    pref.channel_browser = request.POST.get('channel_browser') in ('on', 'true', '1')
    pref.channel_email = request.POST.get('channel_email') in ('on', 'true', '1')
    pref.channel_sms = request.POST.get('channel_sms') in ('on', 'true', '1')
    pref.quiet_hours_enabled = request.POST.get('quiet_hours_enabled') in ('on', 'true', '1')
    pref.quiet_hours_start = request.POST.get('quiet_hours_start', pref.quiet_hours_start).strip()
    pref.quiet_hours_end = request.POST.get('quiet_hours_end', pref.quiet_hours_end).strip()

    # 6. Crop Reminder Settings
    pref.auto_crop_reminders_enabled = request.POST.get('auto_crop_reminders_enabled') in ('on', 'true', '1')
    pref.reminder_frequency = request.POST.get('reminder_frequency', pref.reminder_frequency)
    pref.notify_growth_stages = request.POST.get('notify_growth_stages') in ('on', 'true', '1')
    pref.notify_fertilizer_irrigation = request.POST.get('notify_fertilizer_irrigation') in ('on', 'true', '1')
    pref.notify_pest_inspection = request.POST.get('notify_pest_inspection') in ('on', 'true', '1')
    pref.notify_harvest_estimation = request.POST.get('notify_harvest_estimation') in ('on', 'true', '1')

    # Appearance & Legacy
    pref.theme = request.POST.get('theme', pref.theme)
    pref.crop_care_reminders_enabled = pref.auto_crop_reminders_enabled
    pref.pest_disease_advisories_enabled = request.POST.get('pest_disease_advisories_enabled') in ('on', 'true', '1')
    pref.ai_analysis_notifications_enabled = request.POST.get('ai_analysis_notifications_enabled') in ('on', 'true', '1')
    pref.agricultural_recommendations_enabled = request.POST.get('agricultural_recommendations_enabled') in ('on', 'true', '1')
    pref.application_notices_enabled = request.POST.get('application_notices_enabled') in ('on', 'true', '1')
    pref.save()

    # 7. Update User Account profile (First Name, Last Name, Email) if provided
    first_name = request.POST.get('first_name')
    last_name = request.POST.get('last_name')
    email = request.POST.get('email')
    user_updated = False
    if first_name is not None and first_name.strip() != request.user.first_name:
        request.user.first_name = first_name.strip()
        user_updated = True
    if last_name is not None and last_name.strip() != request.user.last_name:
        request.user.last_name = last_name.strip()
        user_updated = True
    if email is not None and email.strip() != request.user.email:
        request.user.email = email.strip()
        user_updated = True
    if user_updated:
        request.user.save()

    # Optional password change
    new_password = request.POST.get('new_password', '').strip()
    confirm_password = request.POST.get('confirm_password', '').strip()
    if new_password and new_password == confirm_password:
        request.user.set_password(new_password)
        request.user.save()

    if pref.application_notices_enabled:
        Notification.objects.create(
            user=request.user,
            title='Settings updated',
            message='Your farm preferences and notification settings have been updated.',
            category=Notification.Category.NOTICE,
            priority=Notification.Priority.NORMAL,
        )

    return JsonResponse({'status': 'ok', 'message': 'Farm preferences saved successfully.'})"""
assert old_settings_save in text, "old_settings_save not found"
text = text.replace(old_settings_save, new_settings_save)

with open(target, 'w', encoding='utf-8') as f:
    f.write(text)
print('Successfully patched apps/core/views.py')
