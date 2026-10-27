import logging
import uuid
from datetime import timedelta
from django.http import JsonResponse

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.conversations import (
    add_message,
    create_conversation,
    get_conversation,
    get_history,
    list_conversations,
    touch_last_message,
)
from apps.core.models import Conversation, CropDiagnosis, Message
from apps.crops.models import Crop, ScheduledReminder
from apps.info.models import WeatherAlert
from apps.core.gemini import (
    GeminiAuthenticationError,
    GeminiConfigurationError,
    GeminiModelConfigurationError,
    GeminiRequestError,
    GeminiRateLimitError,
    GeminiUnavailableError,
    ImageValidationError,
    RateLimitError,
    check_rate_limit,
    connection_status,
    generate_reply,
    validate_image,
)
from apps.core.weather import get_weather, api_key_configured as weather_configured
from apps.info.models import Notification, UserPreference
User = get_user_model()
logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=1)
INVALID_LOGIN_MESSAGE = 'Invalid username or password.'
LOCKED_MESSAGE = 'Too many failed attempts. Locked for 1 minute.'


def _reset_lock_state(request):
    request.session['failed_attempts'] = 0
    request.session['lock_time'] = None


def _get_lock_state(request):
    failed_attempts = request.session.get('failed_attempts', 0)
    lock_time = request.session.get('lock_time')

    if not lock_time:
        return failed_attempts, None

    try:
        unlock_time = timezone.datetime.fromisoformat(lock_time)
    except (TypeError, ValueError):
        _reset_lock_state(request)
        return 0, None

    if timezone.now() < unlock_time:
        remaining = int((unlock_time - timezone.now()).total_seconds())
        return failed_attempts, remaining

    _reset_lock_state(request)
    return 0, None


def _set_lock_state(request):
    lock_until = timezone.now() + LOCK_DURATION
    request.session['failed_attempts'] = MAX_FAILED_ATTEMPTS
    request.session['lock_time'] = lock_until.isoformat()
    return int(LOCK_DURATION.total_seconds())


def _validate_registration_data(data):
    errors = {}

    username = data.get('username', '').strip()
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not username:
        errors['username'] = 'Username is required.'
    elif User.objects.filter(username=username).exists():
        errors['username'] = 'Username already taken.'

    if not first_name:
        errors['first_name'] = 'First name is required.'

    if not last_name:
        errors['last_name'] = 'Last name is required.'

    if not email:
        errors['email'] = 'Email is required.'
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors['email'] = 'Enter a valid email address.'
        else:
            if User.objects.filter(email=email).exists():
                errors['email'] = 'Email already registered.'

    if not password:
        errors['password'] = 'Password is required.'
    elif len(password) < 8:
        errors['password'] = 'Password must be at least 8 characters.'
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors['password'] = ' '.join(exc.messages)

    if password != confirm_password:
        errors['confirm_password'] = 'Passwords do not match.'

    return errors


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    failed_attempts, remaining = _get_lock_state(request)
    if remaining is not None:
        messages.error(request, f'Too many failed attempts. Try again in {remaining} seconds.')
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    if request.method == 'GET':
        return render(request, 'auth/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is not None:
        _reset_lock_state(request)
        login(request, user)
        return redirect('dashboard')

    failed_attempts += 1
    request.session['failed_attempts'] = failed_attempts
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        remaining = _set_lock_state(request)
        messages.error(request, LOCKED_MESSAGE)
        return render(request, 'auth/login.html', {'locked': True, 'remaining': remaining})

    remaining_attempts = MAX_FAILED_ATTEMPTS - failed_attempts
    messages.error(request, f'{INVALID_LOGIN_MESSAGE} {remaining_attempts} attempts remaining.')
    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
def home(request):
    from apps.catalog.models import CropCatalog
    from apps.core.weather import api_key_configured as weather_configured
    from apps.info.models import Notification

    total_crops = CropCatalog.objects.count()

    # AI Assistant status
    from apps.core.gemini import api_key_configured as ai_configured
    if ai_configured():
        ai_status = 'Checking'
        ai_status_text = 'Checking Gemini connection...'
        ai_available = True
    else:
        ai_status = 'Not configured'
        ai_status_text = 'Set GEMINI_API_KEY to enable'
        ai_available = False

    # Weather status
    weather_data = {'available': False, 'error': 'No location configured.', 'current': None, 'forecast': [], 'location': '', 'updated_at': None}
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = None

    location = pref.farm_location if pref and pref.farm_location else ''
    units = 'metric' if not pref or pref.temperature_unit == 'celsius' else 'imperial'
    if location and weather_configured():
        import requests
        from apps.core.weather import _env, API_KEY_ENV_VAR
        api_key = _env(API_KEY_ENV_VAR)
        if api_key:
            try:
                geo_resp = requests.get(
                    'https://api.openweathermap.org/geo/1.0/direct',
                    params={'q': location, 'limit': 1, 'appid': api_key},
                    timeout=10,
                )
                if geo_resp.status_code != 200:
                    weather_data['error'] = 'Unable to geocode farm location.'
                else:
                    geo = geo_resp.json()
                    if geo:
                        lat = geo[0]['lat']
                        lon = geo[0]['lon']
                        weather_data = get_weather(lat, lon, units)
                        weather_data['location'] = geo[0].get('name', location)
                    else:
                        weather_data['error'] = 'Farm location was not found.'
            except Exception:
                logger.exception('Unable to retrieve dashboard weather for user %s.', request.user.pk)
                weather_data['error'] = 'Unable to retrieve weather data.'

    weather_available = weather_data.get('available', False)
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
    })


# ---------------------------------------------------------------------------
# Agri AI Assistant chat endpoint
# ---------------------------------------------------------------------------


@login_required(login_url='login')
def chat_conversations(request):
    """List the signed-in user's conversations, newest first."""
    conversations = list_conversations(request.user)
    data = []
    for conversation in conversations:
        data.append({
            'id': conversation.id,
            'started_at': conversation.started_at.isoformat(),
            'last_message_at': (
                conversation.last_message_at.isoformat()
                if conversation.last_message_at
                else None
            ),
            'message_count': conversation.message_count,
        })
    return JsonResponse({'conversations': data})


@login_required(login_url='login')
def chat_messages(request, conversation_id):
    """Return the messages of one of the user's conversations."""
    conversation = get_conversation(request.user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Conversation not found.'}, status=404)

    data = []
    for message in get_history(conversation):
        entry = {
            'id': message.id,
            'sender': message.sender.username if message.sender else None,
            'body': message.body,
            'created_at': message.created_at.isoformat(),
            'has_image': message.has_image,
        }
        if message.has_image:
            entry['image_content_type'] = message.image_content_type
            entry['image_size'] = message.image_size
            entry['image_url'] = message.image.url if message.image else None
        data.append(entry)
    return JsonResponse({
        'conversation_id': conversation.id,
        'messages': data,
    })


@login_required(login_url='login')
@require_POST
def chat_view(request):
    try:
        return _chat_view(request)
    except Exception as exc:
        logger.error('Unexpected AI chat endpoint error (error_type=%s).', type(exc).__name__)
        return JsonResponse({'error': 'Unexpected server error.'}, status=500)


def _chat_view(request):
    message = (request.POST.get('message') or '').strip()
    raw_request_id = (request.POST.get('request_id') or '').strip()
    try:
        request_id = uuid.UUID(raw_request_id) if raw_request_id else None
    except (AttributeError, TypeError, ValueError):
        return JsonResponse({'error': 'Invalid request ID.'}, status=400)

    image_file = request.FILES.get('image')
    if image_file is not None:
        try:
            _, image_size = validate_image(image_file)
        except ImageValidationError as exc:
            return JsonResponse({'error': str(exc)}, status=400)

    # A message with only an image is allowed (e.g. "What is wrong with this plant?").
    if not message and image_file is None:
        return JsonResponse({'error': 'Message is required.'}, status=400)

    if not message:
        message = '[Image attached]'

    if request_id is not None:
        previous_request = Message.objects.filter(
            sender=request.user,
            client_request_id=request_id,
        ).first()
        if previous_request is not None:
            previous_reply = Message.objects.filter(reply_to=previous_request).first()
            if previous_reply is not None:
                return JsonResponse({
                    'reply': previous_reply.body,
                    'conversation_id': previous_request.conversation_id,
                    'user_message_id': previous_request.id,
                    'has_image': previous_request.has_image,
                })
            return JsonResponse(
                {
                    'error': 'This request is still being processed. Please retry shortly.',
                    'code': 'request_in_progress',
                },
                status=409,
            )

    conversation_id = (request.POST.get('conversation_id') or '').strip() or None
    if conversation_id:
        conversation = get_conversation(request.user, conversation_id)
        if conversation is None:
            return JsonResponse({'error': 'Conversation not found.'}, status=404)
    else:
        conversation = None

    try:
        check_rate_limit(request.user)
    except RateLimitError as exc:
        return JsonResponse({'error': str(exc)}, status=429)

    history = _build_history(conversation, before=timezone.now()) if conversation else []

    try:
        reply = generate_reply(
            request.user,
            message,
            history,
            image_file=image_file,
        )
    except GeminiConfigurationError as exc:
        return JsonResponse({
            'error': str(exc),
            'code': 'configuration_error',
        }, status=503)
    except GeminiAuthenticationError as exc:
        return JsonResponse({'error': str(exc), 'code': 'authentication_error'}, status=503)
    except GeminiModelConfigurationError as exc:
        return JsonResponse({'error': str(exc), 'code': 'model_configuration_error'}, status=503)
    except GeminiRateLimitError as exc:
        response = JsonResponse({
            'error': str(exc),
            'code': 'rate_limited',
            'retry_after': exc.retry_after,
        }, status=429)
        if exc.retry_after is not None:
            response['Retry-After'] = str(max(1, int(exc.retry_after)))
        return response
    except GeminiUnavailableError as exc:
        return JsonResponse({'error': str(exc), 'code': 'temporarily_unavailable'}, status=503)
    except GeminiRequestError as exc:
        return JsonResponse({'error': str(exc)}, status=502)
    except Exception as exc:
        logger.error('Unexpected AI response error (error_type=%s).', type(exc).__name__)
        return JsonResponse({'error': 'Unexpected server error.'}, status=500)

    try:
        with transaction.atomic():
            if conversation is None:
                conversation = create_conversation(request.user)
            if image_file is not None:
                image_file.seek(0)
            user_message = add_message(
                conversation,
                request.user,
                message,
                image=image_file,
                image_content_type=image_file.content_type if image_file else '',
                image_size=image_size if image_file else None,
                client_request_id=request_id,
            )
            add_message(conversation, None, reply, reply_to=user_message)
            touch_last_message(conversation)
            if image_file is not None:
                from apps.core.gemini import save_crop_diagnosis_from_reply
                save_crop_diagnosis_from_reply(
                    user=request.user,
                    conversation=conversation,
                    user_message=user_message,
                    reply_text=reply,
                    image_file=image_file,
                )
    except IntegrityError:
        if request_id is None:
            raise
        previous_request = Message.objects.filter(
            sender=request.user,
            client_request_id=request_id,
        ).first()
        previous_reply = (
            Message.objects.filter(reply_to=previous_request).first()
            if previous_request is not None
            else None
        )
        if previous_request is None or previous_reply is None:
            raise
        return JsonResponse({
            'reply': previous_reply.body,
            'conversation_id': previous_request.conversation_id,
            'user_message_id': previous_request.id,
            'has_image': previous_request.has_image,
        })

    return JsonResponse({
        'reply': reply,
        'conversation_id': conversation.id,
        'user_message_id': user_message.id,
        'has_image': image_file is not None,
    })

@login_required(login_url='login')
@require_POST
def chat_new_conversation(request):
    """Start a fresh conversation with the Agri AI Assistant."""
    conversation = create_conversation(request.user)
    return JsonResponse({
        'status': 'success',
        'conversation_id': conversation.id,
        'started_at': conversation.started_at.isoformat(),
    })


@login_required(login_url='login')
@require_POST
def chat_delete_conversation(request, conversation_id):
    """Delete a conversation and its messages."""
    conversation = get_conversation(request.user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Conversation not found.'}, status=404)
    conversation.delete()
    return JsonResponse({'status': 'success', 'deleted_id': conversation_id})


@login_required(login_url='login')
@require_POST
def chat_clear_conversation(request, conversation_id):
    """Clear all messages inside a conversation."""
    conversation = get_conversation(request.user, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Conversation not found.'}, status=404)
    conversation.messages.all().delete()
    conversation.last_message_at = None
    conversation.save(update_fields=['last_message_at'])
    return JsonResponse({'status': 'success', 'cleared_id': conversation_id})


@login_required(login_url='login')
def diagnoses_list(request):
    """List all recorded image-based crop diagnoses for this user."""
    diagnoses = CropDiagnosis.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'users/diagnoses_list.html', {'diagnoses': diagnoses})


@login_required(login_url='login')
def diagnosis_detail(request, pk):
    """Detail view of an individual crop health and disease diagnosis."""
    from django.shortcuts import get_object_or_404
    diagnosis = get_object_or_404(CropDiagnosis, pk=pk, user=request.user)
    return render(request, 'users/diagnosis_detail.html', {'diagnosis': diagnosis})



def _build_history(conversation, before):
    """Return the conversation's earlier messages, in chronological order.

    Messages with attached images include the image data so the vision model
    can see prior context.
    """
    history = []
    for message in get_history(conversation):
        if message.created_at >= before:
            break
        role = 'model' if message.sender is None else 'user'
        entry = {
            'role': role,
            'body': message.body,
        }
        if message.has_image and message.image:
            try:
                message.image.seek(0)
                image_data = message.image.read()
            except Exception:
                logger.exception('Could not read an image from chat history.')
            else:
                entry['image'] = True
                entry['image_content_type'] = message.image_content_type
                entry['image_data'] = image_data
        history.append(entry)
    return history


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'GET':
        return render(request, 'auth/register.html')

    form_data = {
        'username': request.POST.get('username', ''),
        'first_name': request.POST.get('first_name', ''),
        'last_name': request.POST.get('last_name', ''),
        'email': request.POST.get('email', ''),
        'password': request.POST.get('password', ''),
        'confirm_password': request.POST.get('confirm_password', ''),
    }

    errors = _validate_registration_data(form_data)
    if errors:
        return render(request, 'auth/register.html', {'errors': errors, 'form_data': form_data})

    user = User.objects.create_user(
        username=form_data['username'].strip(),
        first_name=form_data['first_name'].strip(),
        last_name=form_data['last_name'].strip(),
        email=form_data['email'].strip(),
        password=form_data['password'],
    )
    login(request, user)
    return redirect('dashboard')


# ---------------------------------------------------------------------------
# AI Assistant page
# ---------------------------------------------------------------------------

@login_required(login_url='login')
def aiassistant_page(request):
    """Render the dedicated Agri AI Assistant page."""
    from apps.core.gemini import api_key_configured as ai_configured

    ai_available = ai_configured()

    return render(request, 'users/aiassistant.html', {
        'ai_status': 'Checking connection',
        'ai_status_text': 'Checking Gemini connection...',
        'ai_available': ai_available,
    })


@login_required(login_url='login')
@require_http_methods(['GET'])
def gemini_status(request):
    """Return a safe, server-side Gemini credential/model connectivity status."""
    result = connection_status()
    return JsonResponse(result, status=200 if result['state'] == 'connected' else 503)


# ---------------------------------------------------------------------------
# Weather page and API
# ---------------------------------------------------------------------------

@login_required(login_url='login')
def weather_page(request):
    """Render the weather page with live data when configured."""
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = None

    location = pref.farm_location if pref and pref.farm_location else ''
    units = pref.temperature_unit if pref and pref.temperature_unit else 'celsius'

    weather_data = {'available': False, 'error': 'No location configured. Set your farm location in Settings.', 'current': None, 'forecast': [], 'location': '', 'updated_at': None}

    if location:
        # Geocode the location name to lat/lon using OpenWeatherMap geocoding API
        try:
            import requests
            api_key = None
            from apps.core.weather import _env, API_KEY_ENV_VAR
            api_key = _env(API_KEY_ENV_VAR)
            if api_key:
                geo_resp = requests.get(
                    'https://api.openweathermap.org/geo/1.0/direct',
                    params={'q': location, 'limit': 1, 'appid': api_key},
                    timeout=10,
                )
                if geo_resp.status_code != 200:
                    weather_data['error'] = 'Unable to geocode farm location.'
                else:
                    geo = geo_resp.json()
                    if geo:
                        lat = geo[0]['lat']
                        lon = geo[0]['lon']
                        weather_data = get_weather(lat, lon, units='metric' if units == 'celsius' else 'imperial')
                        weather_data['location'] = geo[0].get('name', location)
                    else:
                        weather_data['error'] = 'Farm location was not found.'
        except Exception:
            logger.exception('Unable to retrieve weather for user %s.', request.user.pk)
            weather_data = {'available': False, 'error': 'Unable to retrieve weather data.', 'current': None, 'forecast': [], 'location': location, 'updated_at': None}

    return render(request, 'weather.html', {
        'weather': weather_data,
        'weather_configured': weather_configured(),
        'units': units,
    })


@login_required(login_url='login')
@require_http_methods(['GET'])
def weather_api(request):
    """Return weather data as JSON for AJAX refresh."""
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = None

    location = pref.farm_location if pref and pref.farm_location else ''
    units = pref.temperature_unit if pref and pref.temperature_unit else 'celsius'

    if not location:
        return JsonResponse({'available': False, 'error': 'No location configured.'})

    try:
        import requests
        from apps.core.weather import _env, API_KEY_ENV_VAR
        api_key = _env(API_KEY_ENV_VAR)
        if not api_key:
            return JsonResponse({'available': False, 'error': 'Weather API key not configured.'})

        geo_resp = requests.get(
            'https://api.openweathermap.org/geo/1.0/direct',
            params={'q': location, 'limit': 1, 'appid': api_key},
            timeout=10,
        )
        if geo_resp.status_code != 200:
            return JsonResponse({'available': False, 'error': 'Unable to geocode location.'})
        geo = geo_resp.json()
        if not geo:
            return JsonResponse({'available': False, 'error': 'Location not found.'})

        lat = geo[0]['lat']
        lon = geo[0]['lon']
        weather_data = get_weather(lat, lon, units='metric' if units == 'celsius' else 'imperial')
        weather_data['location'] = geo[0].get('name', location)
        return JsonResponse(weather_data)
    except Exception:
        logger.exception('Unable to refresh weather for user %s.', request.user.pk)
        return JsonResponse(
            {'available': False, 'error': 'Unable to retrieve weather data.'},
            status=502,
        )


# ---------------------------------------------------------------------------
# Notifications page and API
# ---------------------------------------------------------------------------

@login_required(login_url='login')
def notifications_page(request):
    """Render the notifications page."""
    categories = Notification.Category.choices
    return render(request, 'notifications.html', {
        'categories': categories,
        'priority_choices': Notification.Priority.choices,
        'category_filter': request.GET.get('category', ''),
        'status_filter': request.GET.get('status', 'all'),
    })


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def notifications_api(request):
    """List and update notifications owned by the authenticated user."""
    active_notifications = request.user.notifications.filter(deleted_at__isnull=True)

    if request.method == 'GET' or request.POST.get('action') == 'list':
        notifications = active_notifications
        status = request.GET.get('status', 'all')
        category = request.GET.get('category', '')
        priority = request.GET.get('priority', '')
        search = request.GET.get('search', '').strip()[:200]
        ordering = request.GET.get('ordering', 'newest')

        if status == 'unread':
            notifications = notifications.filter(read=False)
        elif status == 'read':
            notifications = notifications.filter(read=True)
        elif status != 'all':
            return JsonResponse({'error': 'Invalid status filter.'}, status=400)

        valid_categories = {value for value, _label in Notification.Category.choices}
        valid_priorities = {value for value, _label in Notification.Priority.choices}
        if category:
            if category not in valid_categories:
                return JsonResponse({'error': 'Invalid category filter.'}, status=400)
            notifications = notifications.filter(category=category)
        if priority:
            if priority not in valid_priorities:
                return JsonResponse({'error': 'Invalid priority filter.'}, status=400)
            notifications = notifications.filter(priority=priority)
        if search:
            notifications = notifications.filter(
                Q(title__icontains=search) | Q(message__icontains=search)
            )
        notifications = notifications.order_by(
            'created_at' if ordering == 'oldest' else '-created_at', '-pk'
        )[:500]
        data = [{
            'id': notification.pk,
            'title': notification.title,
            'message': notification.message,
            'category': notification.category,
            'category_label': notification.get_category_display(),
            'priority': notification.priority,
            'priority_label': notification.get_priority_display(),
            'created_at': timezone.localtime(notification.created_at).isoformat(),
            'read': notification.read,
            'related_url': notification.related_url,
        } for notification in notifications]
        return JsonResponse({
            'notifications': data,
            'unread_count': active_notifications.filter(read=False).count(),
            'total_count': active_notifications.count(),
        })

    action = request.POST.get('action', '')
    now = timezone.now()

    if action in {'mark_read', 'mark_unread', 'delete', 'dismiss'}:
        notification_id = request.POST.get('notification_id')
        if not notification_id:
            return JsonResponse({'error': 'A notification ID is required.'}, status=400)
        try:
            notification = active_notifications.get(pk=notification_id)
        except (Notification.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Notification not found.'}, status=404)

        if action == 'mark_read' and not notification.read:
            notification.read = True
            notification.read_at = now
            notification.save(update_fields=['read', 'read_at'])
        elif action == 'mark_unread' and notification.read:
            notification.read = False
            notification.read_at = None
            notification.save(update_fields=['read', 'read_at'])
        elif action in {'delete', 'dismiss'}:
            notification.deleted_at = now
            notification.save(update_fields=['deleted_at'])
        return JsonResponse({
            'status': 'ok',
            'read': notification.read,
            'unread_count': active_notifications.filter(read=False).count(),
            'total_count': active_notifications.count(),
        })

    if action == 'mark_all_read':
        with transaction.atomic():
            active_notifications.filter(read=False).update(read=True, read_at=now)
        return JsonResponse({
            'status': 'ok',
            'unread_count': 0,
            'total_count': active_notifications.count(),
        })

    if action == 'delete_read':
        with transaction.atomic():
            active_notifications.filter(read=True).update(deleted_at=now)
        return JsonResponse({
            'status': 'ok',
            'unread_count': active_notifications.filter(read=False).count(),
            'total_count': active_notifications.count(),
        })

    if action == 'delete_selected':
        ids = request.POST.getlist('notification_ids')
        if not ids:
            return JsonResponse({'error': 'Select at least one notification.'}, status=400)
        with transaction.atomic():
            active_notifications.filter(pk__in=ids).update(deleted_at=now)
        return JsonResponse({
            'status': 'ok',
            'unread_count': active_notifications.filter(read=False).count(),
            'total_count': active_notifications.count(),
        })

    return JsonResponse({'error': 'Unknown action.'}, status=400)


# ---------------------------------------------------------------------------
# Settings page and API
# ---------------------------------------------------------------------------

@login_required(login_url='login')
def settings_page(request):
    """Render the settings page with current preferences."""
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    categories = Notification.Category.choices if hasattr(Notification, 'Category') else []
    return render(request, 'settings.html', {
        'pref': pref,
        'weather_configured': weather_configured(),
        'categories': categories,
    })


@login_required(login_url='login')
@require_http_methods(['POST'])
def settings_save(request):
    """Save comprehensive farm, AI assistant, weather thresholds, and reminder preferences."""
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

    return JsonResponse({'status': 'ok', 'message': 'Farm preferences saved successfully.'})
