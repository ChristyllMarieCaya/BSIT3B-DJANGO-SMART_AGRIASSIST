"""Script to update apps/core/gemini.py with enhanced context and diagnosis parsing."""

import os
from pathlib import Path

target_file = Path('apps/core/gemini.py')
with open(target_file, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace retrieve_guidelines and build_contents and generate_reply
old_block = """def retrieve_guidelines(owner):
    \"\"\"Return the most recent crop guidelines that are relevant to this owner.\"\"\"
    guidelines = (
        CropGuideline.objects
        .filter(owner=owner)
        .order_by('-created_at')[:MAX_GUIDELINES_PER_REQUEST]
    )
    return [
        {
            'crop_type': guideline.get_crop_type_display(),
            'crop_name': guideline.crop_name,
            'variety': guideline.variety,
            'sow_date': guideline.sow_date.isoformat(),
            'notes': guideline.notes,
        }
        for guideline in guidelines
    ]


def _image_part(image_file):
    \"\"\"Build an image part dict for the Gemini API from an uploaded file.\"\"\"
    image_file.seek(0)
    return {
        'inline_data': {
            'mime_type': image_file.content_type,
            'data': image_file.read(),
        }
    }


def build_contents(message, history, guidelines, image_file=None):
    \"\"\"Assemble the conversation contents for a single request.

    If ``image_file`` is provided, it is included as an inline image part in
    the latest user turn.
    \"\"\"
    contents = []

    if guidelines:
        reference = '\\n'.join(
            '- {crop_type} {crop_name} (variety: {variety}, sown {sow_date}){notes}'
            .format(
                crop_type=item['crop_type'],
                crop_name=item['crop_name'],
                variety=item['variety'] or 'n/a',
                sow_date=item['sow_date'],
                notes=f\"\\n  Notes: {item['notes']}\" if item['notes'] else '',
            )
            for item in guidelines
        )
        contents.append({
            'role': 'user',
            'parts': [{'text': f'The following crop guidelines were recorded for this farm:\\n{reference}'}],
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
    \"\"\"Return the assistant's reply for a message, using the Gemini API.

    ``image_file`` is an optional uploaded file object for image analysis.
    \"\"\"
    client = get_client()
    guidelines = retrieve_guidelines(owner)
    contents = build_contents(message, history, guidelines, image_file=image_file)

    config = types.GenerateContentConfig(
        system_instruction=build_system_instruction(),
        temperature=0.4,
    )

    response = _generate_with_retries(client, contents, config)

    reply = response.text
    if not reply:
        raise GeminiRequestError('The assistant returned an empty response.')
    return reply"""

new_block = """def retrieve_farm_context(owner):
    \"\"\"Retrieve user's registered active crops, growth stages, guidelines, and current weather.\"\"\"
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
    \"\"\"Preserve backwards compatibility for guideline extraction.\"\"\"
    ctx = retrieve_farm_context(owner)
    return ctx['guidelines']


def _image_part(image_file):
    \"\"\"Build an image part dict for the Gemini API from an uploaded file.\"\"\"
    image_file.seek(0)
    return {
        'inline_data': {
            'mime_type': image_file.content_type,
            'data': image_file.read(),
        }
    }


def build_contents(message, history, guidelines, image_file=None, farm_context=None):
    \"\"\"Assemble the conversation contents for a single request, including active farm records.\"\"\"
    contents = []

    context_lines = []
    if farm_context and farm_context.get('crops'):
        context_lines.append('Farmer Registered Active Crops:')
        for cr in farm_context['crops']:
            context_lines.append(
                f\"- {cr['name']} (Variety: {cr['variety']}, Field: {cr['field']}): \"
                f\"{cr['days_planted']} days since planting, Stage: {cr['stage']}, \"
                f\"Est. Harvest: {cr['harvest_date']} ({cr['days_until_harvest']} days remaining). \"
                f\"Stage Vulnerability: {cr['weather_vulnerability']}\"
            )

    if guidelines:
        context_lines.append('Farm Historical Crop Guidelines:')
        for item in guidelines:
            notes_str = f\" Notes: {item['notes']}\" if item.get('notes') else ''
            context_lines.append(
                f\"- {item['crop_type']} {item['crop_name']} (variety: {item['variety'] or 'n/a'}, sown {item['sow_date']}){notes_str}\"
            )

    if farm_context and farm_context.get('weather'):
        w = farm_context['weather']
        context_lines.append(
            f\"Current Local Weather at {w['location']}: {w['temperature']}{w['temp_unit']}, \"
            f\"{w['condition']} ({w['description']}), Humidity: {w['humidity']}%, Wind: {w['wind']} {w['wind_unit']}.\"
        )

    if context_lines:
        contents.append({
            'role': 'user',
            'parts': [{'text': 'Current Farm Context & Real-Time Records:\\n' + '\\n'.join(context_lines)}],
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
    \"\"\"Return the assistant's reply for a message, using the Gemini API or development fallback.\"\"\"
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
    \"\"\"Parse and record a CropDiagnosis entry from an image-based diagnosis reply.\"\"\"
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
    lines = reply_text.split('\\n')
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
        return None"""

assert old_block in text, "old_block not found in gemini.py"
text = text.replace(old_block, new_block)
with open(target_file, 'w', encoding='utf-8') as f:
    f.write(text)
print('Successfully patched apps/core/gemini.py')
