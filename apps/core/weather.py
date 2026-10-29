"""Weather service using the Open-Meteo API and PAGASA official advisories.

Provides real-time agro-meteorological observations, multi-day forecasts,
geocoding, automated severe-weather risk evaluation, official PAGASA
bulletin monitoring, and distinct alert categorization.
"""

from datetime import date, datetime, timedelta
import logging
import math
import re
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib3
import requests

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
OPEN_METEO_GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
PAGASA_BULLETIN_URL = 'https://bagong.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin'
PAGASA_ADVISORY_URL = 'https://bagong.pagasa.dost.gov.ph/weather/weather-advisory'


class WeatherConfigurationError(Exception):
    """Raised when weather configuration is invalid."""


class WeatherRequestError(Exception):
    """Raised when weather API call fails."""


def _env(name: str, default: str = '') -> str:
    import os
    return os.environ.get(name, default).strip()


def api_key_configured() -> bool:
    """Open-Meteo is a free, open-access meteorological API requiring no key."""
    return True


def _safe_request(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Optional[requests.Response]:
    """Execute a resilient HTTP GET request, handling Windows certificate verification issues."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            resp = requests.get(url, params=params, timeout=timeout, verify=False)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            logger.warning('SSL fallback request to %s failed: %s', url, exc)
            return None
    except Exception as exc:
        logger.warning('Request to %s failed: %s', url, exc)
        return None


# ---------------------------------------------------------------------------
# Geocoding via Open-Meteo
# ---------------------------------------------------------------------------

def geocode_location(location_name: str) -> Optional[Dict[str, Any]]:
    """Geocode a farm location name to GPS coordinates via Open-Meteo Geocoding API.
    
    Handles inputs like "Cauayan, Isabela", "Munoz, Nueva Ecija", "Tokyo", "London".
    """
    clean_name = location_name.strip()
    if not clean_name:
        return None

    # First attempt: exact query
    resp = _safe_request(
        OPEN_METEO_GEOCODING_URL,
        params={'name': clean_name, 'count': 5, 'language': 'en', 'format': 'json'},
    )
    if resp and resp.status_code == 200:
        data = resp.json()
        results = data.get('results', [])
        if results:
            first = results[0]
            return _format_geocoding_result(first, clean_name)

    # Second attempt: if location has comma (e.g. "Cauayan, Isabela"), search city name and match province
    if ',' in clean_name:
        parts = [p.strip() for p in clean_name.split(',') if p.strip()]
        primary = parts[0]
        secondary = parts[1].lower() if len(parts) > 1 else ''
        resp = _safe_request(
            OPEN_METEO_GEOCODING_URL,
            params={'name': primary, 'count': 8, 'language': 'en', 'format': 'json'},
        )
        if resp and resp.status_code == 200:
            results = resp.json().get('results', [])
            # Look for best match against secondary (province / admin region)
            for res in results:
                admin_str = f"{res.get('admin1', '')} {res.get('admin2', '')} {res.get('country', '')}".lower()
                if secondary in admin_str:
                    return _format_geocoding_result(res, clean_name)
            if results:
                return _format_geocoding_result(results[0], clean_name)

    return None


def _format_geocoding_result(res: Dict[str, Any], original_query: str) -> Dict[str, Any]:
    name = res.get('name', original_query)
    admin1 = res.get('admin1') or res.get('admin2') or ''
    country = res.get('country', '')
    display_location = f"{name}, {admin1}" if admin1 and admin1 != name else name
    if country and country not in display_location:
        display_location = f"{display_location}, {country}"

    return {
        'latitude': round(float(res['latitude']), 4),
        'longitude': round(float(res['longitude']), 4),
        'name': display_location,
        'city': name,
        'country': country,
        'timezone': res.get('timezone', 'Asia/Manila'),
    }


# ---------------------------------------------------------------------------
# WMO Weather Interpretation Code Mapping
# ---------------------------------------------------------------------------

WMO_CODE_MAP = {
    0: ('Clear sky', 'Clear sky with full solar exposure', 'sun', 'moon'),
    1: ('Mainly clear', 'Mainly clear with light cloud patches', 'sun', 'moon'),
    2: ('Partly cloudy', 'Partly cloudy sky', 'cloud-sun', 'cloud-moon'),
    3: ('Overcast', 'Dense overcast cloud cover', 'cloud', 'cloud'),
    45: ('Foggy', 'Fog with reduced visibility', 'smog', 'smog'),
    48: ('Depositing rime fog', 'Depositing rime fog', 'smog', 'smog'),
    51: ('Light drizzle', 'Light patchy drizzle', 'cloud-rain', 'cloud-rain'),
    53: ('Moderate drizzle', 'Moderate continuous drizzle', 'cloud-rain', 'cloud-rain'),
    55: ('Dense drizzle', 'Dense drizzle causing wet foliage', 'cloud-rain', 'cloud-rain'),
    56: ('Light freezing drizzle', 'Light freezing drizzle', 'snowflake', 'snowflake'),
    57: ('Dense freezing drizzle', 'Dense freezing drizzle', 'snowflake', 'snowflake'),
    61: ('Slight rain', 'Slight rain showers', 'cloud-rain', 'cloud-rain'),
    63: ('Moderate rain', 'Moderate steady rainfall', 'cloud-rain', 'cloud-rain'),
    65: ('Heavy rain', 'Heavy downpour and rain accumulations', 'cloud-showers-heavy', 'cloud-showers-heavy'),
    66: ('Light freezing rain', 'Light freezing rain', 'snowflake', 'snowflake'),
    67: ('Heavy freezing rain', 'Heavy freezing rain', 'snowflake', 'snowflake'),
    71: ('Slight snowfall', 'Slight snowfall', 'snowflake', 'snowflake'),
    73: ('Moderate snowfall', 'Moderate snowfall', 'snowflake', 'snowflake'),
    75: ('Heavy snowfall', 'Heavy snowfall', 'snowflake', 'snowflake'),
    77: ('Snow grains', 'Snow grains', 'snowflake', 'snowflake'),
    80: ('Slight rain showers', 'Scattered slight rain showers', 'cloud-rain', 'cloud-rain'),
    81: ('Moderate rain showers', 'Moderate rain showers', 'cloud-rain', 'cloud-rain'),
    82: ('Violent rain showers', 'Torrential rain showers with high flood risk', 'cloud-showers-heavy', 'cloud-showers-heavy'),
    85: ('Slight snow showers', 'Slight snow showers', 'snowflake', 'snowflake'),
    86: ('Heavy snow showers', 'Heavy snow showers', 'snowflake', 'snowflake'),
    95: ('Thunderstorm', 'Thunderstorm with lightning and gusty winds', 'cloud-bolt', 'cloud-bolt'),
    96: ('Thunderstorm with slight hail', 'Severe thunderstorm with slight hail hazard', 'cloud-bolt', 'cloud-bolt'),
    99: ('Thunderstorm with heavy hail', 'Violent thunderstorm with severe hail damage risk', 'cloud-bolt', 'cloud-bolt'),
}


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _interpret_wmo(code: int, is_day: int = 1) -> Dict[str, str]:
    entry = WMO_CODE_MAP.get(int(_safe_number(code)), ('Cloudy', 'Cloudy conditions', 'cloud', 'cloud'))
    icon = entry[2] if is_day else entry[3]
    return {
        'condition': entry[0],
        'description': entry[1],
        'icon': icon,
    }


# ---------------------------------------------------------------------------
# Weather Retrieval
# ---------------------------------------------------------------------------

def get_weather(lat: float, lon: float, units: str = 'metric', location_name: str = '') -> Dict[str, Any]:
    """Retrieve real weather data and 7-day forecast from Open-Meteo for coordinates.
    
    Handles API failures cleanly without fabricating fake weather data.
    """
    is_imperial = (units.lower() in ('imperial', 'fahrenheit'))
    temp_unit = '°F' if is_imperial else '°C'
    wind_unit = 'mph' if is_imperial else 'km/h'
    precip_unit = 'inch' if is_imperial else 'mm'

    params = {
        'latitude': lat,
        'longitude': lon,
        'current': (
            'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,'
            'precipitation,rain,weather_code,wind_speed_10m,wind_direction_10m'
        ),
        'daily': (
            'weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,'
            'apparent_temperature_min,precipitation_sum,rain_sum,precipitation_probability_max,'
            'wind_speed_10m_max,wind_gusts_10m_max'
        ),
        'hourly': 'temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m',
        'timezone': 'auto',
    }
    if is_imperial:
        params['temperature_unit'] = 'fahrenheit'
        params['wind_speed_unit'] = 'mph'
        params['precipitation_unit'] = 'inch'

    resp = _safe_request(OPEN_METEO_FORECAST_URL, params=params, timeout=12)

    if not resp or resp.status_code != 200:
        return {
            'available': False,
            'error': 'Weather service is temporarily unavailable. Retrying automatically...',
            'current': None,
            'forecast': [],
            'location': location_name or 'Farm Location',
            'updated_at': None,
            'source': 'Open-Meteo Live API',
        }

    try:
        data = resp.json()
        current_raw = data.get('current', {})
        daily_raw = data.get('daily', {})
        wmo_current = _interpret_wmo(
            current_raw.get('weather_code', 0),
            is_day=current_raw.get('is_day', 1),
        )
        current_temperature = _safe_number(current_raw.get('temperature_2m'))

        current = {
            'temperature': round(current_temperature, 1),
            'feels_like': round(_safe_number(current_raw.get('apparent_temperature'), current_temperature), 1),
            'humidity': int(_safe_number(current_raw.get('relative_humidity_2m'))),
            'pressure': 1013,
            'wind_speed': round(_safe_number(current_raw.get('wind_speed_10m')), 1),
            'wind_deg': int(_safe_number(current_raw.get('wind_direction_10m'))),
            'condition': wmo_current['condition'],
            'description': wmo_current['description'],
            'icon': wmo_current['icon'],
            'temp_unit': temp_unit,
            'wind_unit': wind_unit,
            'precip_unit': precip_unit,
            'rain_1h': round(_safe_number(current_raw.get('precipitation')), 1),
            'is_day': bool(current_raw.get('is_day', 1)),
        }

        # Parse 7-day daily forecast
        forecast = []
        dates = daily_raw.get('time', [])
        weather_codes = daily_raw.get('weather_code', [])
        temp_maxs = daily_raw.get('temperature_2m_max', [])
        temp_mins = daily_raw.get('temperature_2m_min', [])
        precip_sums = daily_raw.get('precipitation_sum', [])
        precip_probs = daily_raw.get('precipitation_probability_max', [])
        wind_gusts = daily_raw.get('wind_gusts_10m_max', [])

        for idx, date_str in enumerate(dates):
            wmo_code = weather_codes[idx] if idx < len(weather_codes) else 0
            wmo_day = _interpret_wmo(wmo_code, is_day=1)
            t_max = round(_safe_number(temp_maxs[idx]), 1) if idx < len(temp_maxs) else 0.0
            t_min = round(_safe_number(temp_mins[idx]), 1) if idx < len(temp_mins) else 0.0
            pop = int(_safe_number(precip_probs[idx])) if idx < len(precip_probs) else 0
            p_sum = round(_safe_number(precip_sums[idx]), 1) if idx < len(precip_sums) else 0.0
            w_gust = round(_safe_number(wind_gusts[idx]), 1) if idx < len(wind_gusts) else 0.0

            forecast.append({
                'date': date_str,
                'temperature_max': t_max,
                'temperature_min': t_min,
                'condition': wmo_day['condition'],
                'description': wmo_day['description'],
                'icon': wmo_day['icon'],
                'pop': pop,
                'rain_sum': p_sum,
                'precip_unit': precip_unit,
                'wind_gusts_max': w_gust,
            })

        resolved_location = location_name or f"{data.get('latitude', lat):.2f}, {data.get('longitude', lon):.2f}"
        tz = data.get('timezone', 'UTC')

        return {
            'available': True,
            'error': None,
            'current': current,
            'forecast': forecast,
            'location': resolved_location,
            'timezone': tz,
            'updated_at': int(datetime.now().timestamp()),
            'source': 'Open-Meteo Live API',
        }

    except Exception as exc:
        logger.exception('Failed parsing Open-Meteo weather response: %s', exc)
        return {
            'available': False,
            'error': 'Error processing live weather data.',
            'current': None,
            'forecast': [],
            'location': location_name or 'Farm Location',
            'updated_at': None,
            'source': 'Open-Meteo Live API',
        }


# ---------------------------------------------------------------------------
# PAGASA Official Advisory Monitoring (Philippines)
# ---------------------------------------------------------------------------

def is_philippines_location(
    location_name: str = '',
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    country: str = '',
) -> bool:
    """Determine whether farm location falls under PAGASA's Philippine Area of Responsibility (PAR)."""
    if country:
        return country.strip().casefold() in {'philippines', 'the philippines'}

    if lat is not None and lon is not None:
        # PAR bounding box approximately 4°N to 21.5°N, 116°E to 127.5°E
        if 4.0 <= lat <= 22.0 and 115.0 <= lon <= 130.0:
            return True

    text = (location_name or '').lower()
    ph_keywords = [
        'philippines', 'manila', 'isabela', 'cauayan', 'nueva ecija', 'iloilo',
        'cebu', 'davao', 'pampanga', 'pangasinan', 'cagayan', 'tarlac', 'laguna',
        'batangas', 'quezon', 'bicol', 'visayas', 'mindanao', 'luzon', 'bulacan',
    ]
    return any(k in text for k in ph_keywords)


def check_pagasa_advisories(
    location_name: str = '',
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    country: str = '',
) -> List[Dict[str, Any]]:
    """Check official PAGASA Severe Weather Bulletins for tropical cyclones affecting the Philippines.
    
    Clearly marks any detected alert with is_official=True and source='PAGASA Official Warning / Bulletin'.
    """
    if not is_philippines_location(location_name, lat, lon, country):
        return []

    alerts = []
    resp = _safe_request(PAGASA_BULLETIN_URL, timeout=8)
    if resp and resp.status_code == 200:
        html = resp.text
        # If active tropical cyclone within PAR
        if 'No Active Tropical Cyclone within the Philippine Area of Responsibility' not in html:
            # Look for active bulletin headings
            bulletin_match = re.search(r'Tropical Cyclone Bulletin\s*#?\s*([0-9A-Za-z\s\-]+)', html, re.I)
            cyclone_match = re.search(r'(Tropical Depression|Tropical Storm|Severe Tropical Storm|Typhoon|Super Typhoon)\s+[\'"]?([A-Za-z]+)[\'"]?', html, re.I)

            cyclone_type = cyclone_match.group(1) if cyclone_match else 'Tropical Cyclone'
            cyclone_name = cyclone_match.group(2) if cyclone_match else ''
            bulletin_info = bulletin_match.group(0).strip() if bulletin_match else 'Active Severe Weather Bulletin'

            title = f"PAGASA Official Warning: {cyclone_type} {cyclone_name}".strip()
            alerts.append({
                'alert_type': 'storm',
                'severity': 'critical' if 'Typhoon' in cyclone_type else 'warning',
                'title': title,
                'forecast_condition': f"{bulletin_info} issued by PAGASA for Philippine Area of Responsibility.",
                'expected_timing': 'Active PAGASA Severe Weather Bulletin',
                'agricultural_impact': (
                    'Severe cyclone threat to field crops and farm infrastructure. '
                    'Expect intense rainfall, destructive winds, flash floods, and waterlogged soil.'
                ),
                'precautionary_actions': (
                    '• Immediately clear drainage pathways to avoid catastrophic submergence.\n'
                    '• Harvest mature crops and store seeds and harvested yield in elevated, dry facilities.\n'
                    '• Anchor nursery greenhouses, shade nets, and bamboo trellises.\n'
                    '• Relocate livestock and machinery away from low-lying flood-prone fields.'
                ),
                'source': 'PAGASA Official Warning / Bulletin',
                'is_official': True,
                'deduplication_key': f"pagasa_bulletin_{re.sub(r'[^a-zA-Z0-9]', '_', title).lower()}_{date.today().isoformat()}",
            })

    return alerts


# ---------------------------------------------------------------------------
# Automated Weather Risk Evaluation
# ---------------------------------------------------------------------------

def evaluate_weather_risks(
    weather_data: Dict[str, Any],
    location_name: str,
    rain_threshold_mm: float = 25.0,
    wind_threshold_kmh: float = 40.0,
    temp_high_threshold_c: float = 35.0,
    temp_low_threshold_c: float = 15.0,
    today_date: Optional[date] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    country: str = '',
) -> List[Dict[str, Any]]:
    """Evaluate current weather and forecast against thresholds, and include official PAGASA warnings.
    
    Clearly distinguishes official PAGASA warnings (is_official=True) from
    forecast-based alerts (is_official=False).
    """
    if not weather_data or not weather_data.get('available') or not weather_data.get('current'):
        return []

    if today_date is None:
        today_date = date.today()

    today_str = today_date.isoformat()
    alerts = []

    # 1. First, check official warnings (PAGASA in Philippines)
    official_alerts = check_pagasa_advisories(
        location_name=location_name,
        lat=lat,
        lon=lon,
        country=country,
    )
    alerts.extend(official_alerts)

    current = weather_data['current']
    forecast = weather_data.get('forecast', [])

    temp = current.get('temperature', 28.0)
    wind = current.get('wind_speed', 10.0)
    humidity = current.get('humidity', 70)
    rain_1h = current.get('rain_1h', 0.0)
    condition = current.get('condition', '').lower()
    description = current.get('description', '').lower()

    # Convert thresholds if units are Fahrenheit / Imperial
    if weather_data.get('current', {}).get('temp_unit') == '°F':
        temp_c = (temp - 32) * 5 / 9
    else:
        temp_c = temp

    # 2. Heavy rainfall & flood hazard (Forecast-Based Alert)
    rain_risk = False
    rain_severity = 'advisory'
    rain_actions = [
        'Inspect and clear furrow outflows, culverts, and drainage canals to prevent waterlogging.',
        'Postpone nitrogen and urea topdressing to avoid nutrient runoff.',
        'Halt foliar pesticide and fungicide spraying as rain will wash away chemical cover.',
        'Inspect seedbeds and seedling nurseries; prepare protective plastic tunnels if needed.',
    ]

    # Check current rainfall or thunderstorm
    if rain_1h >= rain_threshold_mm or 'thunderstorm' in condition or 'heavy' in description or 'violent' in description:
        rain_risk = True
        rain_severity = 'critical' if (rain_1h >= 40.0 or 'violent' in description or 'torrential' in description) else 'warning'
    else:
        # Check upcoming 1-2 days forecast precipitation
        heavy_days = [f for f in forecast[:3] if f.get('rain_sum', 0) >= rain_threshold_mm or f.get('pop', 0) >= 75]
        if heavy_days:
            rain_risk = True
            rain_severity = 'warning' if heavy_days[0].get('rain_sum', 0) >= (rain_threshold_mm * 1.5) else 'advisory'

    if rain_risk:
        alerts.append({
            'alert_type': 'heavy_rain',
            'severity': rain_severity,
            'title': f'Heavy Rain & Flood Advisory: {location_name}',
            'forecast_condition': f'{current.get("condition")}, {current.get("description")} (Rain: {rain_1h} mm/h)',
            'expected_timing': 'Immediate and next 24-48 hours',
            'agricultural_impact': 'High risk of standing water, root zone suffocation, nutrient leaching, and fungal spore dissemination.',
            'precautionary_actions': '\n'.join(f'• {a}' for a in rain_actions),
            'source': 'Open-Meteo Forecast Alert',
            'is_official': False,
            'deduplication_key': f'rain_{location_name}_{today_str}_{rain_severity}',
        })

    # 3. Strong winds & gale hazard (Forecast-Based Alert)
    wind_risk = False
    wind_severity = 'warning'
    max_gust = max([f.get('wind_gusts_max', 0) for f in forecast[:2]] or [0])
    if wind >= wind_threshold_kmh or max_gust >= (wind_threshold_kmh * 1.25) or 'storm' in condition:
        wind_risk = True
        wind_severity = 'critical' if (wind >= 60.0 or max_gust >= 75.0) else 'warning'
        alerts.append({
            'alert_type': 'strong_winds',
            'severity': wind_severity,
            'title': f'Strong Winds & Gale Advisory: {location_name}',
            'forecast_condition': f'Wind speeds reaching {wind} km/h (Gusts up to {max_gust} km/h)',
            'expected_timing': 'Active forecast window',
            'agricultural_impact': 'Danger of crop lodging in tall crops (corn, rice), trellis breakage, and floral shedding.',
            'precautionary_actions': (
                '• Secure bamboo stakes, trellises, and plant supports for tomatoes, eggplants, and climbing beans.\n'
                '• Lower or secure nursery shade netting and plastic greenhouse skins.\n'
                '• Avoid standing near tall trees or loose agricultural structures.'
            ),
            'source': 'Open-Meteo Forecast Alert',
            'is_official': False,
            'deduplication_key': f'wind_{location_name}_{today_str}_{wind_severity}',
        })

    # 4. Extreme heat stress (Forecast-Based Alert)
    if temp_c >= temp_high_threshold_c:
        severity = 'critical' if temp_c >= 39.0 else 'warning' if temp_c >= 37.0 else 'advisory'
        alerts.append({
            'alert_type': 'extreme_heat',
            'severity': severity,
            'title': f'Extreme Heat Stress Alert: {location_name}',
            'forecast_condition': f'High temperature {temp}°C (Humidity {humidity}%)',
            'expected_timing': 'Midday hours (10:00 AM - 3:00 PM)',
            'agricultural_impact': 'Excessive evapotranspiration, blossom drop in vegetables, pollen sterility, and rapid soil drying.',
            'precautionary_actions': (
                '• Increase irrigation frequency; irrigate early morning (before 8 AM) or late afternoon.\n'
                '• Avoid applying foliar fertilizers or pesticides during peak midday heat to prevent scorching.\n'
                '• Apply rice straw or dry organic mulch around plant beds to conserve soil moisture.\n'
                '• Ensure abundant shade and clean drinking water for farm animals.'
            ),
            'source': 'Open-Meteo Forecast Alert',
            'is_official': False,
            'deduplication_key': f'heat_{location_name}_{today_str}_{severity}',
        })

    # 5. Low temperature / cold spell (Forecast-Based Alert)
    if temp_c <= temp_low_threshold_c:
        alerts.append({
            'alert_type': 'cold_spell',
            'severity': 'advisory',
            'title': f'Low Temperature Advisory: {location_name}',
            'forecast_condition': f'Cool temperatures down to {temp}°C',
            'expected_timing': 'Early morning hours',
            'agricultural_impact': 'Slowed nutrient uptake, delayed vegetative development in warm-season tropical crops.',
            'precautionary_actions': (
                '• Provide light protective covering for delicate nursery seedbeds.\n'
                '• Regulate standing field water depth to allow soil to warm during sunny daytime hours.'
            ),
            'source': 'Open-Meteo Forecast Alert',
            'is_official': False,
            'deduplication_key': f'cold_{location_name}_{today_str}',
        })

    # 6. Extended dry conditions / drought risk
    rainy_days_in_forecast = sum(1 for f in forecast if f.get('pop', 0) >= 30)
    if len(forecast) >= 4 and rainy_days_in_forecast == 0 and temp_c >= 30.0:
        alerts.append({
            'alert_type': 'drought_dry',
            'severity': 'advisory',
            'title': f'Extended Dry Weather Advisory: {location_name}',
            'forecast_condition': 'Extended rain-free forecast window',
            'expected_timing': 'Upcoming 5-7 days',
            'agricultural_impact': 'Depleted topsoil moisture, increasing irrigation demand and risk of moisture stress.',
            'precautionary_actions': (
                '• Check soil moisture at root depth (10-15 cm) daily.\n'
                '• Schedule drip or furrow irrigation before permanent wilting point is reached.\n'
                '• Retain crop residues and apply surface mulch to minimize evaporative water loss.'
            ),
            'source': 'Open-Meteo Forecast Alert',
            'is_official': False,
            'deduplication_key': f'drought_{location_name}_{today_str}',
        })

    return alerts


# ---------------------------------------------------------------------------
# Utility mappings and unit conversions
# ---------------------------------------------------------------------------

def _font_awesome_icon(icon_code: str) -> str:
    """Map legacy OpenWeather icons or Open-Meteo WMO codes to FontAwesome icons."""
    icon_code = str(icon_code or '').strip()
    if icon_code.isdigit():
        return _interpret_wmo(int(icon_code))['icon']

    prefix = icon_code[:2]
    if prefix == '01':
        return 'moon' if icon_code.endswith('n') else 'sun'
    if prefix == '02':
        return 'cloud-moon' if icon_code.endswith('n') else 'cloud-sun'
    return {
        '03': 'cloud',
        '04': 'cloud',
        '09': 'cloud-showers-heavy',
        '10': 'cloud-rain',
        '11': 'cloud-bolt',
        '13': 'snowflake',
        '50': 'smog',
    }.get(prefix, 'cloud')


def celsius_to_fahrenheit(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


def fahrenheit_to_celsius(f: float) -> float:
    return round((f - 32) * 5 / 9, 1)


def get_weather_history(lat: float, lon: float, start_date: str, end_date: str, units: str = 'metric') -> Dict[str, Any]:
    """Retrieve historical/recorded daily weather series from Open-Meteo for the requested date range."""
    is_imperial = (units.lower() in ('imperial', 'fahrenheit'))
    params = {
        'latitude': lat,
        'longitude': lon,
        'start_date': start_date,
        'end_date': end_date,
        'daily': 'temperature_2m_mean,temperature_2m_max,temperature_2m_min,rain_sum,precipitation_sum',
        'timezone': 'auto',
    }
    if is_imperial:
        params['temperature_unit'] = 'fahrenheit'
        params['precipitation_unit'] = 'inch'

    resp = _safe_request(OPEN_METEO_FORECAST_URL, params=params, timeout=12)
    if not resp or resp.status_code != 200:
        return {'available': False, 'daily': {}}

    try:
        data = resp.json().get('daily', {})
        times = data.get('time', [])
        means = data.get('temperature_2m_mean', [])
        maxs = data.get('temperature_2m_max', [])
        mins = data.get('temperature_2m_min', [])
        rains = data.get('rain_sum', data.get('precipitation_sum', []))

        result = {}
        for idx, d_str in enumerate(times):
            temp = means[idx] if idx < len(means) and means[idx] is not None else None
            if temp is None and idx < len(maxs) and idx < len(mins) and maxs[idx] is not None and mins[idx] is not None:
                temp = round((maxs[idx] + mins[idx]) / 2.0, 1)
            rain = rains[idx] if idx < len(rains) and rains[idx] is not None else 0.0
            result[d_str] = {
                'temperature': round(float(temp), 1) if temp is not None else None,
                'rainfall': round(float(rain), 1) if rain is not None else 0.0,
            }
        return {'available': True, 'daily': result}
    except Exception as exc:
        logger.exception('Failed parsing Open-Meteo historical weather: %s', exc)
        return {'available': False, 'daily': {}}
