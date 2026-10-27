"""Service layer for the Gemini-powered Agri AI Assistant.

Credentials and model selection are read from the environment so that no
secrets live in source control:

- ``GEMINI_API_KEY``      API key used to authenticate against Google AI.
- ``GEMINI_MODEL``       Model name (defaults to ``gemini-2.5-flash``).
- ``GEMINI_TIMEOUT_SECONDS``  Response timeout in seconds (default 30).
- ``GEMINI_CONNECT_TIMEOUT_SECONDS``  Connection timeout in seconds (default 10).
- ``GEMINI_MAX_RETRIES``  Number of retries for transient failures (default 2).

When ``GEMINI_API_KEY`` is not configured the service raises
:class:`GeminiConfigurationError`; the chat endpoints return an error state
instead of falling back to a canned reply.

Image analysis:
- Uploaded images are validated for content type and size before being sent
  to the vision model.
- Image analysis results are suggestions only, not guaranteed diagnoses.
- Uploaded images are not stored as crop records.
"""

import logging
import os
import random
import socket
import ssl
import time
from email.utils import parsedate_to_datetime
from hashlib import sha256

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from apps.info.models import CropGuideline

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = 'GEMINI_API_KEY'
MODEL_ENV_VAR = 'GEMINI_MODEL'
TIMEOUT_ENV_VAR = 'GEMINI_TIMEOUT_SECONDS'
CONNECT_TIMEOUT_ENV_VAR = 'GEMINI_CONNECT_TIMEOUT_SECONDS'
READ_TIMEOUT_ENV_VAR = 'GEMINI_READ_TIMEOUT_SECONDS'
MAX_RETRIES_ENV_VAR = 'GEMINI_MAX_RETRIES'

DEFAULT_MODEL = 'gemini-2.5-flash'
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 8
CONNECTION_STATUS_CACHE_SECONDS = 30

# How many of the user's own crop guidelines are offered as reference data.
MAX_GUIDELINES_PER_REQUEST = 5

# Guard against excessive requests to the external AI provider.
RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

# Image upload limits.
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/webp',
}


class GeminiConfigurationError(Exception):
    """Raised when the Gemini API key is missing or misconfigured."""


class GeminiRequestError(Exception):
    """Raised when the Gemini API call fails."""


class GeminiAuthenticationError(GeminiRequestError):
    """Raised when Google rejects the configured credentials."""


class GeminiModelConfigurationError(GeminiRequestError):
    """Raised when the configured model is invalid or unavailable."""


class GeminiRateLimitError(GeminiRequestError):
    """Raised when Google throttles the configured project."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class GeminiUnavailableError(GeminiRequestError):
    """Raised when Gemini cannot be reached after transient retries."""


class RateLimitError(Exception):
    """Raised when a user exceeds the configured request rate."""


class ImageValidationError(Exception):
    """Raised when an uploaded image fails validation."""


_client = None
_client_key_fingerprint = None
_recent_request_times = {}
_connection_status = None
_connection_status_checked_at = 0
_connection_status_model = None


def _env(name, default=''):
    return os.environ.get(name, default).strip()


def api_key_configured():
    return bool(_env(API_KEY_ENV_VAR))


def model_name():
    return _env(MODEL_ENV_VAR) or DEFAULT_MODEL


def request_timeout_seconds():
    raw = _env(TIMEOUT_ENV_VAR, str(DEFAULT_TIMEOUT_SECONDS))
    try:
        return min(300, max(1, int(raw)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def connect_timeout_seconds():
    raw = _env(CONNECT_TIMEOUT_ENV_VAR, str(DEFAULT_CONNECT_TIMEOUT_SECONDS))
    try:
        return min(120, max(1, int(raw)))
    except ValueError:
        return DEFAULT_CONNECT_TIMEOUT_SECONDS


def max_retries():
    raw = _env(MAX_RETRIES_ENV_VAR, str(DEFAULT_MAX_RETRIES))
    try:
        return min(4, max(0, int(raw)))
    except ValueError:
        return DEFAULT_MAX_RETRIES


def get_client():
    """Create (once) and return the shared Gemini client."""
    global _client, _client_key_fingerprint, _connection_status, _connection_status_model
    api_key = _env(API_KEY_ENV_VAR)
    if not api_key:
        raise GeminiConfigurationError(
            f'{API_KEY_ENV_VAR} is not configured on the server.'
        )
    key_fingerprint = sha256(api_key.encode('utf-8')).digest()
    if _client is not None and _client_key_fingerprint == key_fingerprint:
        return _client

    previous_client = _client
    _client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=None,
            client_args={
                'timeout': httpx.Timeout(
                    timeout=request_timeout_seconds(),
                    connect=connect_timeout_seconds(),
                    read=request_timeout_seconds(),
                    write=request_timeout_seconds(),
                    pool=connect_timeout_seconds(),
                ),
            },
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    _client_key_fingerprint = key_fingerprint
    _connection_status = None
    _connection_status_model = None
    if previous_client is not None:
        previous_client.close()
    return _client


def _retry_after_seconds(exc):
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    value = headers.get('Retry-After')
    if not value:
        return None
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def _api_status(exc):
    code = getattr(exc, 'code', None)
    if isinstance(code, int):
        return code
    status = getattr(exc, 'status', None)
    return status if isinstance(status, int) else None


def _is_authentication_error(exc, status):
    if status in (401, 403):
        return True
    if status != 400:
        return False
    message = str(getattr(exc, 'message', '')).lower()
    return any(phrase in message for phrase in (
        'api key not valid',
        'invalid api key',
        'api_key_invalid',
    ))


def _raise_for_api_error(exc):
    status = _api_status(exc)
    if _is_authentication_error(exc, status):
        raise GeminiAuthenticationError(
            'Gemini rejected the configured API credentials. Check GEMINI_API_KEY and its API access.'
        ) from exc
    if status == 404:
        raise GeminiModelConfigurationError(
            f'The configured Gemini model "{model_name()}" is unavailable. Check GEMINI_MODEL.'
        ) from exc
    if status == 429:
        retry_after = _retry_after_seconds(exc)
        raise GeminiRateLimitError(
            'Gemini is temporarily rate-limiting requests. Please wait and try again.',
            retry_after=retry_after,
        ) from exc
    if status == 408 or (isinstance(status, int) and status >= 500):
        raise GeminiUnavailableError(
            'Sorry, the AI assistant is temporarily unable to connect. Please check your connection and try again.'
        ) from exc
    raise GeminiRequestError(
        'Gemini could not process this request. Check the message and configured model, then try again.'
    ) from exc


def _is_transient_network_error(exc):
    return isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            ssl.SSLError,
            socket.timeout,
            TimeoutError,
            ConnectionError,
        ),
    )


def _generate_with_retries(client, contents, config):
    attempts = max_retries() + 1
    for attempt in range(attempts):
        try:
            return client.models.generate_content(
                model=model_name(),
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as exc:
            status = _api_status(exc)
            retryable = status == 429 or status == 408 or (
                isinstance(status, int) and status >= 500
            )
            retry_after = _retry_after_seconds(exc) if status == 429 else None
            if not retryable or attempt + 1 >= attempts:
                _raise_for_api_error(exc)
            if retry_after is not None and retry_after > MAX_RETRY_DELAY_SECONDS:
                _raise_for_api_error(exc)
            delay = retry_after if retry_after is not None else min(
                MAX_RETRY_DELAY_SECONDS,
                0.5 * (2 ** attempt) + random.uniform(0, 0.25),
            )
            time.sleep(delay)
        except Exception as exc:
            if not _is_transient_network_error(exc):
                raise GeminiRequestError(
                    'Gemini could not process this request. Check the configured model and try again.'
                ) from exc
            if attempt + 1 >= attempts:
                raise GeminiUnavailableError(
                    'Sorry, the AI assistant is temporarily unable to connect. Please check your connection and try again.'
                ) from exc
            time.sleep(min(
                MAX_RETRY_DELAY_SECONDS,
                0.5 * (2 ** attempt) + random.uniform(0, 0.25),
            ))
    raise GeminiUnavailableError(
        'Sorry, the AI assistant is temporarily unable to connect. Please check your connection and try again.'
    )


def connection_status(force=False):
    """Check configured credentials and model availability without generating content."""
    global _connection_status, _connection_status_checked_at, _connection_status_model
    now = time.monotonic()
    configured_model = model_name()
    if not api_key_configured():
        return {
            'state': 'configuration_error',
            'message': 'Set GEMINI_API_KEY on the server to enable Gemini.',
        }
    if (
        not force
        and _connection_status is not None
        and _connection_status_model == configured_model
        and now - _connection_status_checked_at < CONNECTION_STATUS_CACHE_SECONDS
    ):
        return dict(_connection_status)

    try:
        get_client().models.get(model=model_name())
        result = {'state': 'connected', 'message': 'Gemini connection verified'}
    except GeminiConfigurationError:
        result = {
            'state': 'configuration_error',
            'message': 'Set GEMINI_API_KEY on the server to enable Gemini.',
        }
    except genai_errors.APIError as exc:
        status = _api_status(exc)
        if _is_authentication_error(exc, status):
            result = {
                'state': 'configuration_error',
                'message': 'Gemini rejected the configured API credentials. Check GEMINI_API_KEY.',
            }
        elif status == 404:
            result = {
                'state': 'configuration_error',
                'message': f'The configured Gemini model "{model_name()}" is unavailable. Check GEMINI_MODEL.',
            }
        else:
            result = {
                'state': 'temporarily_unavailable',
                'message': 'Gemini is temporarily unavailable. You can retry your request.',
            }
        logger.warning('Gemini connectivity check failed (status=%s).', status)
    except Exception as exc:
        result = {
            'state': 'temporarily_unavailable',
            'message': 'Gemini is temporarily unavailable. You can retry your request.',
        }
        logger.warning('Gemini connectivity check failed (error_type=%s).', type(exc).__name__)

    _connection_status = result
    _connection_status_checked_at = now
    _connection_status_model = configured_model
    return dict(result)


def check_rate_limit(user):
    """Allow at most RATE_LIMIT_MAX_REQUESTS generations per user per window."""
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    user_id = user.pk
    recent = [stamp for stamp in _recent_request_times.get(user_id, []) if stamp > window_start]
    if len(recent) >= RATE_LIMIT_MAX_REQUESTS:
        raise RateLimitError(
            f'Too many requests. Please wait a moment before asking again.'
        )
    recent.append(now)
    _recent_request_times[user_id] = recent


def validate_image(image_file):
    """Validate an uploaded image file.

    Returns (content_type, size) or raises :class:`ImageValidationError`.
    """
    if image_file is None:
        return None, 0

    content_type = getattr(image_file, 'content_type', '') or ''
    if content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ImageValidationError(
            f'Unsupported image type "{content_type}". '
            f'Allowed: {", ".join(sorted(ALLOWED_IMAGE_CONTENT_TYPES))}.'
        )

    size = getattr(image_file, 'size', None)
    if size is None:
        # Fall back to reading the file.
        image_file.seek(0, os.SEEK_END)
        size = image_file.tell()
        image_file.seek(0)

    if size > MAX_IMAGE_SIZE_BYTES:
        raise ImageValidationError(
            f'Image too large: {size / (1024 * 1024):.1f} MB. '
            f'Maximum: {MAX_IMAGE_SIZE_BYTES / (1024 * 1024):.0f} MB.'
        )

    return content_type, size


def build_system_instruction(user_context=None):
    """Return instructions shaping the SMART AGRIASSIST behavior with context awareness."""
    lang = user_context.get('language', 'en') if user_context else 'en'
    detail = user_context.get('response_detail', 'balanced') if user_context else 'balanced'

    lang_instruction = ''
    if lang in ('fil', 'tl'):
        lang_instruction = 'Pangunahing wika: Sumagot sa natural at magalang na wikang Filipino (Tagalog/Taglish) na madaling maunawaan ng mga magsasaka sa bukid.\n'
    elif lang == 'ceb':
        lang_instruction = 'Pangunahing wika: Tubaga sa pinulongang Bisaya/Cebuano nga sayon masabtan sa mga mag-uuma.\n'
    elif lang == 'ilo':
        lang_instruction = 'Pangunahing wika: Sungbatan iti pagsasao nga Ilokano nga nalaka a maawatan dagiti mannalon.\n'

    detail_instruction = (
        'Keep responses concise, bulleted, and immediately actionable.' if detail == 'concise'
        else 'Provide comprehensive agronomic reasoning, stage-by-stage instructions, and preventive protocols.' if detail == 'detailed'
        else 'Provide practical, balanced, and clear farming guidance with actionable steps.'
    )

    return (
        'You are SMART AGRIASSIST, an intelligent agricultural assistant chatbot for farmers.\n'
        'Your mission is to help farmers identify crop diseases, diagnose plant problems, '
        'monitor crop growth stages, understand weather conditions, and receive contextual farming recommendations.\n\n'
        f'{lang_instruction}'
        f'{detail_instruction}\n\n'
        'Core Principles:\n'
        '1. Provide understandable, evidence-based recommendations tailored to the farmer\'s crops and current weather.\n'
        '2. When the user\'s active crops or weather conditions are provided, directly integrate them into your answer (e.g. "Given your Rice is currently in tillering stage...").\n'
        '3. If rain is forecast, advise checking drainage canals and delaying pesticide spraying or fertilizer topdressing to prevent chemical wash-off and nutrient runoff.\n'
        '4. If extreme heat is forecast, advise early morning or late afternoon irrigation, avoiding midday foliage wetting, and organic mulching.\n'
        '5. Image Diagnosis Workflow (When a crop, leaf, stem, fruit, or pest image is attached):\n'
        '   • Plant Identification: State the likely crop species (Rice, Corn, Tomato, Eggplant, Pepper, etc.).\n'
        '   • Visible Symptoms: Describe lesions, spots, yellowing, holes, wilting, or pest activity seen in the photo.\n'
        '   • Likely Diagnosis: Name suspected diseases, insect pests, or nutrient deficiencies with confidence estimation (High, Moderate, or Low).\n'
        '   • Evidence: Explain the specific visual cues supporting your diagnosis.\n'
        '   • Practical Next Steps: Clear, safe cultural and agronomic interventions.\n'
        '   • Preventive Measures: Long-term sanitation, crop rotation, and soil health management.\n'
        '   • Follow-up Inquiries: Ask 1-2 clarifying questions to narrow down uncertain symptoms.\n'
        '   • Local Expert Advice: Advise having suspicious samples confirmed by a municipal agricultural extension officer or certified agronomist.\n'
        '   • Safety: Strictly advise following product label directions, protective equipment, and observing harvest intervals for any agrochemical.\n'
        '6. Be completely honest about uncertainty. Photo-based AI suggestions are not laboratory-certified diagnoses. Do not fabricate symptoms not visible in the image.\n'
        '7. Strictly focus on agriculture, crop health, weather, and farm automation. Do not discuss online sales, shopping carts, or financial transactions.'
    )


def retrieve_farm_context(owner):
    """Retrieve user's registered active crops, growth stages, guidelines, and current weather."""
    context_data = {
        'crops': [],
        'guidelines': [],
        'weather': None,
        'language': 'en',
        'response_detail': 'balanced',
    }

    try:
        from apps.crops.models import Crop
        active_crops = Crop.objects.filter(owner=owner, status=Crop.Status.ACTIVE)[:5]
        for c in active_crops:
            g = c.growth_data
            current_stage = g.get('current_stage')
            context_data['crops'].append({
                'name': c.crop_name,
                'variety': c.variety or 'Standard',
                'field': c.field_name or 'Main plot',
                'days_planted': c.days_since_planting,
                'stage': current_stage['name'] if current_stage else 'Growing',
                'harvest_date': str(g.get('estimated_harvest_date')),
                'days_until_harvest': g.get('days_until_harvest'),
                'activities': current_stage.get('activities', []) if current_stage else [],
                'fertilizer_guidance': current_stage.get('fertilizer_guidance', '') if current_stage else '',
                'weather_vulnerability': current_stage.get('weather_vulnerability', '') if current_stage else '',
            })
    except Exception as exc:
        logger.debug('Could not load crops: %s', exc)

    try:
        guidelines = (
            CropGuideline.objects
            .filter(owner=owner)
            .order_by('-created_at')[:MAX_GUIDELINES_PER_REQUEST]
        )
        for guideline in guidelines:
            context_data['guidelines'].append({
                'crop_type': guideline.get_crop_type_display(),
                'crop_name': guideline.crop_name,
                'variety': guideline.variety,
                'sow_date': guideline.sow_date.isoformat(),
                'notes': guideline.notes,
            })
    except Exception as exc:
        logger.debug('Could not load guidelines: %s', exc)

    try:
        from apps.core.weather import get_weather
        pref = getattr(owner, 'preference', None)
        if pref:
            context_data['language'] = pref.preferred_language or pref.ai_response_language or 'en'
            context_data['response_detail'] = pref.ai_response_detail or 'balanced'
            loc = pref.farm_location or ''
            lat = float(pref.latitude) if pref.latitude else 16.9754
            lon = float(pref.longitude) if pref.longitude else 121.7743
            w = get_weather(lat, lon, units=pref.temperature_unit or 'metric', location_name=loc)
            if w.get('available') and w.get('current'):
                context_data['weather'] = {
                    'location': w.get('location'),
                    'temperature': w['current'].get('temperature'),
                    'temp_unit': w['current'].get('temp_unit', '°C'),
                    'condition': w['current'].get('condition'),
                    'description': w['current'].get('description'),
                    'humidity': w['current'].get('humidity'),
                    'wind': w['current'].get('wind_speed'),
                    'wind_unit': w['current'].get('wind_unit', 'km/h'),
                    'rain_1h': w['current'].get('rain_1h', 0),
                }
    except Exception as exc:
        logger.debug('Could not load weather: %s', exc)

    return context_data


def retrieve_guidelines(owner):
    """Preserve backwards compatibility for guideline extraction."""
    ctx = retrieve_farm_context(owner)
    return ctx['guidelines']


def _image_part(image_file):
    """Build an image part dict for the Gemini API from an uploaded file."""
    image_file.seek(0)
    return {
        'inline_data': {
            'mime_type': image_file.content_type,
            'data': image_file.read(),
        }
    }


def build_contents(message, history, guidelines, image_file=None, farm_context=None):
    """Assemble the conversation contents for a single request, including active farm records."""
    contents = []

    context_lines = []
    if farm_context and farm_context.get('crops'):
        context_lines.append('Farmer Registered Active Crops:')
        for cr in farm_context['crops']:
            context_lines.append(
                f"- {cr['name']} (Variety: {cr['variety']}, Field: {cr['field']}): "
                f"{cr['days_planted']} days since planting, Stage: {cr['stage']}, "
                f"Est. Harvest: {cr['harvest_date']} ({cr['days_until_harvest']} days remaining). "
                f"Stage Vulnerability: {cr['weather_vulnerability']}"
            )

    if guidelines:
        context_lines.append('Farm Historical Crop Guidelines:')
        for item in guidelines:
            notes_str = f" Notes: {item['notes']}" if item.get('notes') else ''
            context_lines.append(
                f"- {item['crop_type']} {item['crop_name']} (variety: {item['variety'] or 'n/a'}, sown {item['sow_date']}){notes_str}"
            )

    if farm_context and farm_context.get('weather'):
        w = farm_context['weather']
        context_lines.append(
            f"Current Local Weather at {w['location']}: {w['temperature']}{w['temp_unit']}, "
            f"{w['condition']} ({w['description']}), Humidity: {w['humidity']}%, Wind: {w['wind']} {w['wind_unit']}."
        )

    if context_lines:
        contents.append({
            'role': 'user',
            'parts': [{'text': 'Current Farm Context & Real-Time Records:\n' + '\n'.join(context_lines)}],
        })

    for turn in history:
        parts = [{'text': turn['body']}]
        if turn.get('image'):
            parts.append({
                'inline_data': {
                    'mime_type': turn['image_content_type'],
                    'data': turn['image_data'],
                }
            })
        contents.append({
            'role': turn['role'],
            'parts': parts,
        })

    user_parts = [{'text': message}]
    if image_file is not None:
        user_parts.append(_image_part(image_file))
    contents.append({'role': 'user', 'parts': user_parts})
    return contents


def generate_reply(owner, message, history, image_file=None):
    """Return the assistant's reply for a message, using the Gemini API or development fallback."""
    farm_ctx = retrieve_farm_context(owner)
    guidelines = farm_ctx['guidelines']
    contents = build_contents(message, history, guidelines, image_file=image_file, farm_context=farm_ctx)

    client = get_client()
    config = types.GenerateContentConfig(
        system_instruction=build_system_instruction(user_context=farm_ctx),
        temperature=0.4,
    )

    response = _generate_with_retries(client, contents, config)

    reply = response.text
    if not reply:
        raise GeminiRequestError('The assistant returned an empty response.')
    return reply


def save_crop_diagnosis_from_reply(user, conversation, user_message, reply_text, image_file=None):
    """Parse and record a CropDiagnosis entry from an image-based diagnosis reply."""
    try:
        from apps.core.models import CropDiagnosis
    except ImportError:
        return None

    crop_name = 'Farm Crop'
    for c in ['Rice', 'Corn (Maize)', 'Corn', 'Tomato', 'Eggplant', 'Pepper', 'Onion', 'Potato', 'Cabbage', 'Wheat']:
        if c.lower() in reply_text.lower():
            crop_name = c
            break

    possible_disease = 'Plant Health / Symptom Assessment'
    lines = reply_text.split('\n')
    for line in lines:
        l = line.lower()
        if any(k in l for k in ['possible disease:', 'diagnosis:', 'suspected issue:', 'identified disease:']):
            parts = line.split(':', 1)
            if len(parts) > 1 and parts[1].strip():
                possible_disease = parts[1].strip()[:255]
                break

    if possible_disease == 'Plant Health / Symptom Assessment':
        for dis in ['Bacterial Leaf Blight', 'Rice Blast', 'Early Blight', 'Late Blight', 'Anthracnose', 'Fall Armyworm', 'Stem Borer', 'Fruit Borer', 'Mosaic Virus', 'Nutrient Deficiency', 'Leaf Spot', 'Damping Off', 'Rust']:
            if dis.lower() in reply_text.lower():
                possible_disease = dis
                break

    confidence_level = 'Moderate'
    confidence_score = 0.65
    if any(k in reply_text.lower() for k in ['high confidence', 'very likely', 'strong evidence']):
        confidence_level = 'High'
        confidence_score = 0.85
    elif any(k in reply_text.lower() for k in ['low confidence', 'uncertain', 'unclear', 'blurry']):
        confidence_level = 'Low (Uncertain)'
        confidence_score = 0.40

    observed_symptoms = ''
    for line in lines:
        if any(k in line.lower() for k in ['symptom', 'lesion', 'spot', 'yellow', 'wilt', 'hole']):
            observed_symptoms += line.strip() + ' '
    if not observed_symptoms:
        observed_symptoms = 'Visible plant foliage / stem discoloration or spots identified from uploaded photo.'

    try:
        diagnosis = CropDiagnosis.objects.create(
            user=user,
            conversation=conversation,
            message=user_message,
            crop_name=crop_name,
            image=user_message.image if user_message and user_message.image else image_file,
            observed_symptoms=observed_symptoms[:1000],
            possible_disease=possible_disease,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            contributing_factors='Weather, humidity, or crop stage conditions observed in context.',
            treatment_recommendations=reply_text[:1500],
            preventive_measures='Practice crop rotation, sanitize cutting tools, and ensure proper plant spacing.',
            technician_advice='Consult local municipal agricultural extension technician for certified confirmation.',
            is_confirmed=False,
        )
        return diagnosis
    except Exception as exc:
        logger.warning('Failed to record CropDiagnosis: %s', exc)
        return None
