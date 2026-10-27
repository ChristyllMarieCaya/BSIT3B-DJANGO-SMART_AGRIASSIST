"""Weather service using the OpenWeatherMap API with automated risk analysis.

Provides live weather observations, multi-day forecasts, severe weather risk
evaluation, crop vulnerability correlation, and alert generation.

Credentials and configuration:
- ``OPENWEATHER_API_KEY``: API key from OpenWeatherMap.
"""

from datetime import date, datetime, timedelta
import logging
import os
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = 'OPENWEATHER_API_KEY'
BASE_URL = 'https://api.openweathermap.org/data/2.5'


class WeatherConfigurationError(Exception):
    """Raised when the OpenWeatherMap API key is missing."""


class WeatherRequestError(Exception):
    """Raised when the weather API call fails."""


def _env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def api_key_configured() -> bool:
    val = _env(API_KEY_ENV_VAR)
    return bool(val and val != 'your-openweather-key')


def get_weather(lat: float, lon: float, units: str = 'metric', location_name: str = '') -> Dict[str, Any]:
    """Return current weather and forecast for coordinates.

    If API key is not configured, provides an Agro-Met development baseline
    so that local testing and offline farm management remain functional.
    """
    if not api_key_configured():
        # Provide developmental Agro-Met reading if API key is not yet set
        return _development_weather(lat, lon, units, location_name)

    api_key = _env(API_KEY_ENV_VAR)

    try:
        current_resp = requests.get(
            f'{BASE_URL}/weather',
            params={'lat': lat, 'lon': lon, 'appid': api_key, 'units': units},
            timeout=10,
        )
        current_resp.raise_for_status()
        current_data = current_resp.json()

        forecast_resp = requests.get(
            f'{BASE_URL}/forecast',
            params={'lat': lat, 'lon': lon, 'appid': api_key, 'units': units},
            timeout=10,
        )
        forecast_resp.raise_for_status()
        forecast_data = forecast_resp.json()

    except requests.RequestException as exc:
        logger.warning('Weather provider error: %s', exc)
        return {
            'available': False,
            'error': f'Weather provider unavailable: {exc}',
            'current': None,
            'forecast': [],
            'location': location_name or None,
            'updated_at': None,
            'source': 'OpenWeatherMap',
        }

    current = _parse_current(current_data, units)
    forecast = _parse_forecast(forecast_data, units)

    return {
        'available': True,
        'error': None,
        'current': current,
        'forecast': forecast,
        'location': current_data.get('name') or location_name or 'Farm Location',
        'updated_at': current_data.get('dt'),
        'source': 'OpenWeatherMap Live API',
    }


def evaluate_weather_risks(
    weather_data: Dict[str, Any],
    location_name: str,
    rain_threshold_mm: float = 25.0,
    wind_threshold_kmh: float = 40.0,
    temp_high_threshold_c: float = 35.0,
    temp_low_threshold_c: float = 15.0,
    today_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Evaluate current weather and forecast against thresholds to generate severe weather alerts.

    Checks:
    - Heavy rainfall and flooding risks
    - Tropical cyclone / strong wind hazards
    - Extreme heat waves
    - Cold spells
    - Prolonged dry conditions / drought risk
    """
    if not weather_data or not weather_data.get('available') or not weather_data.get('current'):
        return []

    if today_date is None:
        today_date = date.today()

    current = weather_data['current']
    forecast = weather_data.get('forecast', [])
    alerts = []
    today_str = today_date.isoformat()

    temp = current.get('temperature', 28.0)
    wind = current.get('wind_speed', 10.0)
    humidity = current.get('humidity', 70)
    rain_1h = current.get('rain_1h', 0.0)
    condition = current.get('condition', '').lower()
    description = current.get('description', '').lower()

    # 1. Heavy rainfall & flooding risk
    rain_risk = False
    rain_severity = 'advisory'
    rain_message = ''
    actions = []

    if rain_1h >= rain_threshold_mm or 'thunderstorm' in condition or 'heavy' in description:
        rain_risk = True
        rain_severity = 'critical' if rain_1h >= 40.0 or 'torrential' in description else 'warning'
        rain_message = (
            f'Heavy rainfall ({rain_1h} mm/h) or active thunderstorm detected over {location_name}.'
        )
        actions = [
            'Immediately inspect and clear drainage canals, culverts, and furrow outflows to prevent root suffocation.',
            'Postpone all topdress fertilizer applications to prevent nutrient runoff and leaching.',
            'Halt chemical foliar spraying as rain will wash off active ingredients.',
            'Inspect vulnerable seedling beds and nursery plastic coverings.',
        ]
    else:
        # Check upcoming 24-48h forecast
        heavy_forecast = [f for f in forecast[:2] if f.get('pop', 0) >= 70 and ('rain' in f.get('condition', '').lower() or 'thunder' in f.get('condition', '').lower())]
        if heavy_forecast:
            rain_risk = True
            rain_severity = 'advisory'
            rain_message = f'High probability of continuous rain ({heavy_forecast[0]["pop"]}%) forecast within 24-48 hours.'
            actions = [
                'Inspect farm drainage before heavy rains commence.',
                'Delay pending pesticide/fertilizer applications until clear weather returns.',
                'Harvest any ready-to-pick produce (tomatoes, peppers, mature grain) to prevent field spoil.',
            ]

    if rain_risk:
        alerts.append({
            'alert_type': 'heavy_rain',
            'severity': rain_severity,
            'title': f'Heavy Rain & Flooding Alert: {location_name}',
            'forecast_condition': f'{current.get("condition")}, {current.get("description")}',
            'expected_timing': 'Immediate (Current) and next 24-48 hours',
            'agricultural_impact': 'High risk of waterlogged soil, seedling submersion, nitrogen runoff, and fungal disease outbreaks.',
            'precautionary_actions': '\n'.join(f'• {a}' for a in actions),
            'deduplication_key': f'rain_{location_name}_{today_str}_{rain_severity}',
            'source': weather_data.get('source', 'OpenWeatherMap'),
        })

    # 2. Strong winds & storm hazard
    if wind >= wind_threshold_kmh or 'storm' in condition or 'squall' in condition:
        severity = 'critical' if wind >= 60.0 else 'warning'
        alerts.append({
            'alert_type': 'strong_winds',
            'severity': severity,
            'title': f'Strong Winds & Tropical Storm Alert: {location_name}',
            'forecast_condition': f'Wind speeds reaching {wind} km/h',
            'expected_timing': 'Current conditions and forecast window',
            'agricultural_impact': 'Risk of crop lodging in tall cereals (rice, corn), broken trellises, shedding of flowers and young fruits.',
            'precautionary_actions': (
                '• Secure bamboo stakes, trellises, and plant supports for tomatoes, eggplants, and vine crops.\n'
                '• Lower or secure shade nets, nursery polytunnels, and greenhouse plastic film.\n'
                '• Avoid standing under tall trees or near loose farm structures.'
            ),
            'deduplication_key': f'wind_{location_name}_{today_str}_{severity}',
            'source': weather_data.get('source', 'OpenWeatherMap'),
        })

    # 3. Extreme heat stress
    if temp >= temp_high_threshold_c:
        severity = 'warning' if temp >= 38.0 else 'advisory'
        alerts.append({
            'alert_type': 'extreme_heat',
            'severity': severity,
            'title': f'Extreme Heat Stress Alert: {location_name}',
            'forecast_condition': f'Temperature {temp}°C (Humidity {humidity}%)',
            'expected_timing': 'Midday hours (10:00 AM - 3:00 PM)',
            'agricultural_impact': 'High evapotranspiration, pollen desiccation, flower drop in solanaceous crops, and moisture stress in vegetables.',
            'precautionary_actions': (
                '• Increase irrigation frequency; water early in the morning (before 8 AM) or in late afternoon.\n'
                '• Avoid foliar fertilizers or agrochemicals during peak heat hours to prevent leaf scorch.\n'
                '• Apply rice straw or dry organic mulch around plant bases to conserve soil moisture.\n'
                '• Ensure adequate shade and clean water for farm animals.'
            ),
            'deduplication_key': f'heat_{location_name}_{today_str}_{severity}',
            'source': weather_data.get('source', 'OpenWeatherMap'),
        })

    # 4. Low temperature / cold spell
    if temp <= temp_low_threshold_c:
        alerts.append({
            'alert_type': 'cold_spell',
            'severity': 'advisory',
            'title': f'Low Temperature Advisory: {location_name}',
            'forecast_condition': f'Cool temperatures down to {temp}°C',
            'expected_timing': 'Early morning hours',
            'agricultural_impact': 'Slowed nutrient uptake, stunted growth in tropical crops (eggplant, pepper, rice).',
            'precautionary_actions': (
                '• Provide light protective covering for delicate nursery seedlings.\n'
                '• Reduce standing water depth in fields to allow soil to warm up during daytime sunlight.'
            ),
            'deduplication_key': f'cold_{location_name}_{today_str}',
            'source': weather_data.get('source', 'OpenWeatherMap'),
        })

    # 5. Prolonged dry conditions / drought risk
    rainy_days_in_forecast = sum(1 for f in forecast if f.get('pop', 0) >= 30)
    if len(forecast) >= 3 and rainy_days_in_forecast == 0 and temp >= 30.0:
        alerts.append({
            'alert_type': 'drought_dry',
            'severity': 'advisory',
            'title': f'Extended Dry Weather Advisory: {location_name}',
            'forecast_condition': 'Consecutive rain-free days forecast',
            'expected_timing': 'Upcoming 5-7 days',
            'agricultural_impact': 'Depleted topsoil moisture reserves, increasing irrigation demand.',
            'precautionary_actions': (
                '• Inspect soil moisture at root depth (10-15 cm) daily.\n'
                '• Schedule scheduled furrow or drip irrigation before signs of permanent wilting occur.\n'
                '• Retain crop residues as soil surface mulch to minimize evaporative loss.'
            ),
            'deduplication_key': f'drought_{location_name}_{today_str}',
            'source': weather_data.get('source', 'OpenWeatherMap'),
        })

    return alerts


def _development_weather(lat: float, lon: float, units: str, location_name: str) -> Dict[str, Any]:
    """Realistic developmental Agro-Met baseline for farms when live API credentials are not set."""
    temp_unit = '°C' if units == 'metric' else '°F'
    wind_unit = 'km/h' if units == 'metric' else 'mph'
    today = date.today()

    return {
        'available': True,
        'error': None,
        'current': {
            'temperature': 29.5,
            'feels_like': 32.0,
            'humidity': 75,
            'pressure': 1010,
            'wind_speed': 12.0,
            'wind_deg': 80,
            'condition': 'Partly Cloudy',
            'description': 'Scattered clouds with light breeze',
            'icon': 'cloud-sun',
            'temp_unit': temp_unit,
            'wind_unit': wind_unit,
            'rain_1h': 0.0,
            'sunrise': None,
            'sunset': None,
        },
        'forecast': [
            {
                'date': (today + timedelta(days=1)).isoformat(),
                'temperature_max': 31.0,
                'temperature_min': 23.5,
                'condition': 'Rain',
                'description': 'Afternoon scattered showers',
                'icon': 'cloud-rain',
                'pop': 60,
            },
            {
                'date': (today + timedelta(days=2)).isoformat(),
                'temperature_max': 32.5,
                'temperature_min': 24.0,
                'condition': 'Clear',
                'description': 'Mostly sunny',
                'icon': 'sun',
                'pop': 20,
            },
            {
                'date': (today + timedelta(days=3)).isoformat(),
                'temperature_max': 33.0,
                'temperature_min': 24.5,
                'condition': 'Clouds',
                'description': 'Partly cloudy',
                'icon': 'cloud-sun',
                'pop': 30,
            },
            {
                'date': (today + timedelta(days=4)).isoformat(),
                'temperature_max': 30.0,
                'temperature_min': 23.0,
                'condition': 'Rain',
                'description': 'Thunderstorm in the afternoon',
                'icon': 'cloud-bolt',
                'pop': 75,
            },
            {
                'date': (today + timedelta(days=5)).isoformat(),
                'temperature_max': 29.0,
                'temperature_min': 22.5,
                'condition': 'Rain',
                'description': 'Moderate rain showers',
                'icon': 'cloud-showers-heavy',
                'pop': 80,
            },
        ],
        'location': location_name or 'Farm Location',
        'updated_at': int(datetime.now().timestamp()),
        'source': 'Development Agro-Met Service (Configure OPENWEATHER_API_KEY for live data)',
    }


def _parse_current(data: Dict[str, Any], units: str) -> Dict[str, Any]:
    temp_unit = '°C' if units == 'metric' else '°F'
    wind_unit = 'km/h' if units == 'metric' else 'mph'
    return {
        'temperature': round(data['main']['temp'], 1),
        'feels_like': round(data['main'].get('feels_like', data['main']['temp']), 1),
        'humidity': data['main']['humidity'],
        'pressure': data['main']['pressure'],
        'wind_speed': (
            round(data['wind']['speed'] * 3.6, 1)
            if units == 'metric'
            else round(data['wind']['speed'], 1)
        ),
        'wind_deg': data['wind'].get('deg'),
        'condition': data['weather'][0]['main'],
        'description': data['weather'][0]['description'].capitalize(),
        'icon': _font_awesome_icon(data['weather'][0].get('icon', '')),
        'temp_unit': temp_unit,
        'wind_unit': wind_unit,
        'rain_1h': data.get('rain', {}).get('1h', 0.0),
        'sunrise': data['sys'].get('sunrise'),
        'sunset': data['sys'].get('sunset'),
    }


def _parse_forecast(data: Dict[str, Any], units: str) -> List[Dict[str, Any]]:
    forecast = []
    seen_dates = set()
    for entry in data.get('list', []):
        dt_txt = entry.get('dt_txt', '')
        date_part = dt_txt.split(' ')[0]
        if date_part in seen_dates:
            continue
        seen_dates.add(date_part)
        forecast.append({
            'date': date_part,
            'temperature_max': round(entry['main']['temp_max'], 1),
            'temperature_min': round(entry['main']['temp_min'], 1),
            'condition': entry['weather'][0]['main'],
            'description': entry['weather'][0]['description'].capitalize(),
            'icon': _font_awesome_icon(entry['weather'][0].get('icon', '')),
            'pop': round(entry.get('pop', 0) * 100),
        })
        if len(forecast) >= 7:
            break
    return forecast


def _font_awesome_icon(icon_code: str) -> str:
    icon_code = str(icon_code or '')
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
