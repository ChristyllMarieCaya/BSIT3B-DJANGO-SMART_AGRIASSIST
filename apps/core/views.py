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
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.admin_auth import get_login_context, resolve_post_login_redirect
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
from apps.core.weather import geocode_location, get_weather, api_key_configured as weather_configured
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
    next_url = request.GET.get('next') or request.POST.get('next')

    if request.user.is_authenticated:
        return redirect(resolve_post_login_redirect(request.user, request, next_url))

    failed_attempts, remaining = _get_lock_state(request)
    context = get_login_context(request)
    if remaining is not None:
        messages.error(request, f'Too many failed attempts. Try again in {remaining} seconds.')
        context.update({'locked': True, 'remaining': remaining})
        return render(request, 'auth/login.html', context)

    if request.method == 'GET':
        return render(request, 'auth/login.html', context)

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is not None:
        _reset_lock_state(request)
        login(request, user)
        return redirect(resolve_post_login_redirect(user, request, next_url))

    failed_attempts += 1
    request.session['failed_attempts'] = failed_attempts
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        remaining = _set_lock_state(request)
        messages.error(request, LOCKED_MESSAGE)
        context.update({'locked': True, 'remaining': remaining})
        return render(request, 'auth/login.html', context)

    remaining_attempts = MAX_FAILED_ATTEMPTS - failed_attempts
    messages.error(request, f'{INVALID_LOGIN_MESSAGE} {remaining_attempts} attempts remaining.')
    return render(request, 'auth/login.html', context)


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
def home(request):
    from apps.catalog.models import CropCatalog
    from apps.info.models import Notification

    total_crops = CropCatalog.objects.count()

    # AI Assistant status
    from apps.core.gemini import api_key_configured as ai_configured
    if ai_configured():
        ai_status = 'Ready'
        ai_status_text = 'Gemini AI Assistant Connected'
        ai_available = True
    else:
        ai_status = 'Not configured'
        ai_status_text = 'Set GEMINI_API_KEY to enable'
        ai_available = False

    # Retrieve user preferences
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    location = pref.farm_location.strip() if pref.farm_location else ''
    units = 'imperial' if pref.temperature_unit == 'fahrenheit' else 'metric'

    weather_data = {
        'available': False,
        'error': 'Farm location has not been configured yet. Configure your farm location in Settings or using the option below.',
        'current': None,
        'forecast': [],
        'location': '',
        'updated_at': None,
        'source': 'Open-Meteo Live API',
    }

    if location:
        lat = float(pref.latitude) if pref.latitude is not None else None
        lon = float(pref.longitude) if pref.longitude is not None else None

        if lat is None or lon is None:
            geo = geocode_location(location)
            if geo:
                lat = geo['latitude']
                lon = geo['longitude']
                pref.latitude = lat
                pref.longitude = lon
                if not pref.farm_timezone:
                    pref.farm_timezone = geo.get('timezone', 'Asia/Manila')
                pref.save(update_fields=['latitude', 'longitude', 'farm_timezone'])

        if lat is not None and lon is not None:
            weather_data = get_weather(lat, lon, units=units, location_name=location)
            if weather_data.get('available'):
                pref.weather_last_updated = timezone.now()
                pref.save(update_fields=['weather_last_updated'])
        else:
            weather_data['error'] = f'Farm location "{location}" could not be geocoded. Please check the spelling in Settings.'

    weather_available = weather_data.get('available', False)
    weather_current = weather_data.get('current')
    weather_forecast = weather_data.get('forecast', [])[:4]
    weather_location = weather_data.get('location') or location or 'Not configured'
    weather_error = weather_data.get('error', '')

    if pref.weather_last_updated:
        weather_updated = timezone.localtime(pref.weather_last_updated).strftime('%b %d, %Y %I:%M %p')
    elif weather_data.get('updated_at'):
        weather_updated = timezone.localtime(timezone.now()).strftime('%b %d, %Y %I:%M %p')
    else:
        weather_updated = 'Not available'

    # Registered Active Crops with calculated stages
    active_crops = list(Crop.objects.filter(owner=request.user, status=Crop.Status.ACTIVE)[:6])
    total_active_crops = Crop.objects.filter(owner=request.user, status=Crop.Status.ACTIVE).count()

    # Active severe weather alerts (with official distinction)
    active_weather_alerts = list(WeatherAlert.objects.filter(user=request.user, is_active=True).order_by('-created_at')[:4])

    # Upcoming farming activities & reminders
    upcoming_reminders = list(
        ScheduledReminder.objects.filter(
            user=request.user,
            status__in=[ScheduledReminder.Status.PENDING, ScheduledReminder.Status.OVERDUE]
        ).select_related('crop').order_by('due_date')[:6]
    )

    # Recent Crop Diagnoses
    recent_diagnoses = list(CropDiagnosis.objects.filter(user=request.user).order_by('-created_at')[:4])

    # Recent Chat Conversations
    recent_conversations = list(Conversation.objects.filter(owner=request.user).order_by('-started_at')[:4])

    # Recent notifications
    recent_notifications = Notification.objects.filter(
        user=request.user,
        deleted_at__isnull=True,
    ).order_by('-created_at')[:5]

    return render(request, 'home.html', {
        'total_crops': total_crops,
        'total_active_crops': total_active_crops,
        'active_crops': active_crops,
        'active_weather_alerts': active_weather_alerts,
        'upcoming_reminders': upcoming_reminders,
        'recent_diagnoses': recent_diagnoses,
        'recent_conversations': recent_conversations,
        'recent_notifications': recent_notifications,
        'unread_count': Notification.objects.filter(user=request.user, read=False, deleted_at__isnull=True).count(),
        'weather_available': weather_available,
        'weather_current': weather_current,
        'weather_forecast': weather_forecast,
        'weather_location': weather_location,
        'weather_error': weather_error,
        'weather_updated': weather_updated,
        'ai_status': ai_status,
        'ai_status_text': ai_status_text,
        'ai_available': ai_available,
        'pref': pref,
    })

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


def _delete_diagnoses_for_user(request, diagnosis_ids):
    """Delete diagnosis records and clean up image files only when unreferenced."""
    diagnosis_ids = set(diagnosis_ids)
    if not diagnosis_ids:
        return JsonResponse({'error': 'Select at least one diagnosis to delete.'}, status=400)

    try:
        with transaction.atomic():
            diagnoses = list(
                CropDiagnosis.objects.select_for_update().filter(
                    user=request.user,
                    pk__in=diagnosis_ids,
                )
            )
            if len(diagnoses) != len(diagnosis_ids):
                return JsonResponse({'error': 'One or more diagnoses were not found.'}, status=404)

            image_files = {
                diagnosis.image.name: diagnosis.image.storage
                for diagnosis in diagnoses
                if diagnosis.image
            }
            Notification.objects.filter(
                user=request.user,
                related_url__in=[f'/diagnoses/{pk}/' for pk in diagnosis_ids],
            ).delete()
            CropDiagnosis.objects.filter(pk__in=diagnosis_ids, user=request.user).delete()

            for image_name, storage in image_files.items():
                transaction.on_commit(
                    lambda storage=storage, image_name=image_name: _delete_unreferenced_diagnosis_image(
                        storage, image_name
                    ),
                    robust=True,
                )
    except DatabaseError:
        logger.exception('Failed to delete crop diagnosis records for user %s', request.user.pk)
        return JsonResponse(
            {'error': 'The diagnosis could not be deleted. Please try again.'},
            status=500,
        )

    return JsonResponse({
        'status': 'ok',
        'deleted_ids': sorted(diagnosis_ids),
        'message': (
            'Diagnosis deleted successfully.'
            if len(diagnosis_ids) == 1
            else f'{len(diagnosis_ids)} diagnoses deleted successfully.'
        ),
    })


def _delete_unreferenced_diagnosis_image(storage, image_name):
    if (
        CropDiagnosis.objects.filter(image=image_name).exists()
        or Message.objects.filter(image=image_name).exists()
    ):
        return

    try:
        storage.delete(image_name)
    except OSError:
        logger.exception('Failed to remove unreferenced diagnosis image %s', image_name)


@login_required(login_url='login')
@require_POST
def diagnosis_delete(request, pk):
    """Delete a diagnosis owned by the current user."""
    return _delete_diagnoses_for_user(request, [pk])


@login_required(login_url='login')
@require_POST
def diagnoses_delete(request):
    """Bulk-delete diagnoses owned by the current user."""
    raw_ids = request.POST.getlist('diagnosis_ids')
    try:
        diagnosis_ids = [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': 'The selected diagnosis list is invalid.'}, status=400)
    return _delete_diagnoses_for_user(request, diagnosis_ids)



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
        pref = UserPreference.objects.create(user=request.user)

    location = pref.farm_location.strip() if pref.farm_location else ''
    units = 'imperial' if pref.temperature_unit == 'fahrenheit' else 'metric'

    weather_data = {
        'available': False,
        'error': 'No farm location configured. Configure your farm location in Settings to view live weather.',
        'current': None,
        'forecast': [],
        'location': '',
        'updated_at': None,
        'source': 'Open-Meteo Live API',
    }

    if location:
        lat = float(pref.latitude) if pref.latitude is not None else None
        lon = float(pref.longitude) if pref.longitude is not None else None

        if lat is None or lon is None:
            geo = geocode_location(location)
            if geo:
                lat = geo['latitude']
                lon = geo['longitude']
                pref.latitude = lat
                pref.longitude = lon
                if not pref.farm_timezone:
                    pref.farm_timezone = geo.get('timezone', 'Asia/Manila')
                pref.save(update_fields=['latitude', 'longitude', 'farm_timezone'])

        if lat is not None and lon is not None:
            weather_data = get_weather(lat, lon, units=units, location_name=location)
            if weather_data.get('available'):
                pref.weather_last_updated = timezone.now()
                pref.save(update_fields=['weather_last_updated'])
        else:
            weather_data['error'] = f'Farm location "{location}" was not found by geocoding. Please check the spelling in Settings.'

    active_weather_alerts = list(WeatherAlert.objects.filter(user=request.user, is_active=True).order_by('-created_at'))

    return render(request, 'weather.html', {
        'weather': weather_data,
        'weather_configured': True,
        'units': pref.temperature_unit or 'celsius',
        'active_alerts': active_weather_alerts,
        'pref': pref,
    })


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def weather_api(request):
    """Return weather data as JSON for AJAX refresh or quick location update."""
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    requested_location = request.POST.get('location')
    if requested_location is None:
        requested_location = request.GET.get('location')
    if requested_location is not None:
        requested_location = requested_location.strip()
        if not requested_location or len(requested_location) > 255:
            return JsonResponse({
                'available': False,
                'error': 'Enter a farm location using no more than 255 characters.',
            }, status=400)

    location = requested_location or (pref.farm_location.strip() if pref.farm_location else '')
    location_changed = bool(requested_location and requested_location != pref.farm_location.strip())
    units = 'imperial' if pref.temperature_unit == 'fahrenheit' else 'metric'

    if not location:
        return JsonResponse({
            'available': False,
            'error': 'No farm location configured. Configure your farm location in Settings.',
        })

    lat = float(pref.latitude) if pref.latitude is not None and not location_changed else None
    lon = float(pref.longitude) if pref.longitude is not None and not location_changed else None
    geo = None

    if lat is None or lon is None:
        geo = geocode_location(location)
        if geo:
            lat = geo['latitude']
            lon = geo['longitude']
        else:
            return JsonResponse({
                'available': False,
                'error': f'Location "{location}" could not be geocoded.',
            })

    weather_data = get_weather(lat, lon, units=units, location_name=location)
    if weather_data.get('available'):
        pref.weather_last_updated = timezone.now()
        pref.farm_location = location
        pref.latitude = lat
        pref.longitude = lon
        if geo and not pref.farm_timezone:
            pref.farm_timezone = geo.get('timezone', 'Asia/Manila')
        pref.save(update_fields=[
            'farm_location', 'latitude', 'longitude', 'farm_timezone', 'weather_last_updated',
        ])
        weather_data['updated_str'] = timezone.localtime(pref.weather_last_updated).strftime('%b %d, %Y %I:%M %p')

    return JsonResponse(weather_data)


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

    if request.method == 'GET' and request.GET.get('count_only') == '1':
        return JsonResponse({
            'unread_count': active_notifications.filter(read=False).count(),
        })

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

COUNTRIES = [
    ('Philippines', 'Philippines'),
    ('United States', 'United States'),
    ('Japan', 'Japan'),
    ('United Kingdom', 'United Kingdom'),
    ('Canada', 'Canada'),
    ('Australia', 'Australia'),
    ('India', 'India'),
    ('Indonesia', 'Indonesia'),
    ('Vietnam', 'Vietnam'),
    ('Thailand', 'Thailand'),
    ('Malaysia', 'Malaysia'),
    ('Singapore', 'Singapore'),
    ('New Zealand', 'New Zealand'),
    ('Germany', 'Germany'),
    ('France', 'France'),
    ('Spain', 'Spain'),
    ('Italy', 'Italy'),
    ('Netherlands', 'Netherlands'),
    ('Switzerland', 'Switzerland'),
    ('Brazil', 'Brazil'),
    ('Mexico', 'Mexico'),
    ('South Africa', 'South Africa'),
    ('South Korea', 'South Korea'),
    ('China', 'China'),
    ('Taiwan', 'Taiwan'),
    ('United Arab Emirates', 'United Arab Emirates'),
    ('Saudi Arabia', 'Saudi Arabia'),
    ('Argentina', 'Argentina'),
    ('Chile', 'Chile'),
    ('Colombia', 'Colombia'),
    ('Egypt', 'Egypt'),
    ('Nigeria', 'Nigeria'),
    ('Kenya', 'Kenya'),
]

PREFERRED_LANGUAGES = [
    ('en', 'English'),
    ('fil', 'Filipino (Tagalog)'),
    ('ceb', 'Cebuano / Bisaya'),
    ('ilo', 'Ilokano'),
]

COMMON_TIMEZONES = [
    ('Asia/Manila', 'Asia/Manila (GMT+8) — Philippines'),
    ('Asia/Tokyo', 'Asia/Tokyo (GMT+9) — Japan'),
    ('Asia/Singapore', 'Asia/Singapore (GMT+8) — Singapore'),
    ('Asia/Bangkok', 'Asia/Bangkok (GMT+7) — Thailand / Vietnam / Indochina'),
    ('Asia/Jakarta', 'Asia/Jakarta (GMT+7) — Indonesia (WIB)'),
    ('Asia/Kuala_Lumpur', 'Asia/Kuala_Lumpur (GMT+8) — Malaysia'),
    ('Asia/Hong_Kong', 'Asia/Hong_Kong (GMT+8) — Hong Kong'),
    ('Asia/Seoul', 'Asia/Seoul (GMT+9) — South Korea'),
    ('Asia/Taipei', 'Asia/Taipei (GMT+8) — Taiwan'),
    ('Asia/Shanghai', 'Asia/Shanghai (GMT+8) — China'),
    ('Asia/Kolkata', 'Asia/Kolkata (GMT+5:30) — India / Sri Lanka'),
    ('Asia/Dubai', 'Asia/Dubai (GMT+4) — UAE / Gulf'),
    ('Asia/Riyadh', 'Asia/Riyadh (GMT+3) — Saudi Arabia'),
    ('Australia/Sydney', 'Australia/Sydney (AEST/AEDT) — Australia East'),
    ('Australia/Melbourne', 'Australia/Melbourne (AEST/AEDT) — Victoria'),
    ('Australia/Brisbane', 'Australia/Brisbane (AEST GMT+10) — Queensland'),
    ('Australia/Perth', 'Australia/Perth (AWST GMT+8) — Western Australia'),
    ('Pacific/Auckland', 'Pacific/Auckland (NZST/NZDT) — New Zealand'),
    ('Pacific/Honolulu', 'Pacific/Honolulu (HST GMT-10) — Hawaii'),
    ('America/New_York', 'America/New_York (EST/EDT) — US East'),
    ('America/Chicago', 'America/Chicago (CST/CDT) — US Central'),
    ('America/Denver', 'America/Denver (MST/MDT) — US Mountain'),
    ('America/Los_Angeles', 'America/Los_Angeles (PST/PDT) — US Pacific'),
    ('America/Anchorage', 'America/Anchorage (AKST/AKDT) — Alaska'),
    ('America/Toronto', 'America/Toronto (EST/EDT) — Canada East'),
    ('America/Vancouver', 'America/Vancouver (PST/PDT) — Canada West'),
    ('America/Sao_Paulo', 'America/Sao_Paulo (BRT GMT-3) — Brazil'),
    ('America/Mexico_City', 'America/Mexico_City (CST GMT-6) — Mexico'),
    ('America/Bogota', 'America/Bogota (COT GMT-5) — Colombia'),
    ('America/Buenos_Aires', 'America/Buenos_Aires (ART GMT-3) — Argentina'),
    ('Europe/London', 'Europe/London (GMT/BST) — United Kingdom'),
    ('Europe/Paris', 'Europe/Paris (CET/CEST) — France'),
    ('Europe/Berlin', 'Europe/Berlin (CET/CEST) — Germany'),
    ('Europe/Rome', 'Europe/Rome (CET/CEST) — Italy'),
    ('Europe/Madrid', 'Europe/Madrid (CET/CEST) — Spain'),
    ('Europe/Amsterdam', 'Europe/Amsterdam (CET/CEST) — Netherlands'),
    ('Europe/Zurich', 'Europe/Zurich (CET/CEST) — Switzerland'),
    ('Europe/Athens', 'Europe/Athens (EET/EEST) — Greece'),
    ('Africa/Cairo', 'Africa/Cairo (EET GMT+2) — Egypt'),
    ('Africa/Johannesburg', 'Africa/Johannesburg (SAST GMT+2) — South Africa'),
    ('Africa/Nairobi', 'Africa/Nairobi (EAT GMT+3) — Kenya / East Africa'),
    ('Africa/Lagos', 'Africa/Lagos (WAT GMT+1) — Nigeria / West Africa'),
    ('UTC', 'UTC (Coordinated Universal Time)'),
]


@login_required(login_url='login')
def settings_page(request):
    """Render the settings page with current preferences, theme, country, and searchable timezone list."""
    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    categories = Notification.Category.choices if hasattr(Notification, 'Category') else []
    now_in_tz = timezone.localtime(timezone.now())
    current_time_str = now_in_tz.strftime('%A, %B %d, %Y - %I:%M:%S %p (%Z)')

    return render(request, 'settings.html', {
        'pref': pref,
        'weather_configured': True,
        'categories': categories,
        'countries': COUNTRIES,
        'preferred_languages': PREFERRED_LANGUAGES,
        'timezones': COMMON_TIMEZONES,
        'current_time_str': current_time_str,
        'theme_choices': UserPreference.Theme.choices,
    })


@login_required(login_url='login')
@require_http_methods(['POST'])
def settings_save(request):
    """Save comprehensive farm, AI assistant, weather thresholds, theme, country, and timezone preferences."""
    regional_preferences = request.POST.get('action') == 'regional_preferences'
    if regional_preferences:
        country = request.POST.get('country', '')
        preferred_language = request.POST.get('preferred_language', '')
        if country not in {value for value, _label in COUNTRIES}:
            return JsonResponse({'status': 'error', 'message': 'Choose a supported country or region.'}, status=400)
        if preferred_language not in {value for value, _label in PREFERRED_LANGUAGES}:
            return JsonResponse({'status': 'error', 'message': 'Choose a supported language.'}, status=400)

    try:
        pref = request.user.preference
    except UserPreference.DoesNotExist:
        pref = UserPreference.objects.create(user=request.user)

    if regional_preferences:
        pref.country = country
        pref.preferred_language = preferred_language
        pref.ai_response_language = preferred_language
        pref.save(update_fields=['country', 'preferred_language', 'ai_response_language', 'updated_at'])
        return JsonResponse({
            'status': 'ok',
            'message': 'Country/region and language preferences saved.',
            'country': pref.country,
            'preferred_language': pref.preferred_language,
        })

    # 1. Farm profile & GPS coordinates
    pref.farm_name = request.POST.get('farm_name', pref.farm_name).strip()
    new_farm_location = request.POST.get('farm_location', pref.farm_location).strip()
    location_changed = (new_farm_location != pref.farm_location)
    pref.farm_location = new_farm_location

    lat_raw = request.POST.get('latitude', '').strip()
    lon_raw = request.POST.get('longitude', '').strip()
    if lat_raw:
        try:
            pref.latitude = float(lat_raw)
        except ValueError:
            pass
    elif location_changed and new_farm_location:
        # Auto-geocode location if coordinates were not explicitly set
        geo = geocode_location(new_farm_location)
        if geo:
            pref.latitude = geo['latitude']
            pref.longitude = geo['longitude']
            if not pref.farm_timezone:
                pref.farm_timezone = geo.get('timezone', 'Asia/Manila')

    if lon_raw:
        try:
            pref.longitude = float(lon_raw)
        except ValueError:
            pass

    # 2. General, Country, Timezone, Units & Theme
    pref.country = request.POST.get('country', pref.country or 'Philippines').strip()
    pref.preferred_language = request.POST.get('preferred_language', pref.preferred_language).strip()
    pref.timezone = request.POST.get('timezone', pref.timezone or 'Asia/Manila').strip()
    pref.farm_timezone = request.POST.get('farm_timezone', pref.farm_timezone or pref.timezone).strip()
    pref.measurement_units = request.POST.get('measurement_units', pref.measurement_units).strip()
    pref.temperature_unit = request.POST.get('temperature_unit', pref.temperature_unit).strip()
    new_theme = request.POST.get('theme', pref.theme).strip().lower()
    if new_theme in ('light', 'dark', 'system'):
        pref.theme = new_theme

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

    # Legacy category toggles
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
            message='Your farm preferences, timezone, theme, and notification settings have been updated.',
            category=Notification.Category.NOTICE,
            priority=Notification.Priority.NORMAL,
        )

    now_in_tz = timezone.localtime(timezone.now())
    response = JsonResponse({
        'status': 'ok',
        'message': 'Farm preferences saved successfully.',
        'theme': pref.theme,
        'country': pref.country,
        'timezone': pref.timezone,
        'current_time_str': now_in_tz.strftime('%A, %B %d, %Y - %I:%M:%S %p (%Z)'),
    })
    response.set_cookie(
        'smart_app_theme',
        pref.theme,
        max_age=31536000,
        samesite='Lax',
        secure=request.is_secure(),
    )
    return response
