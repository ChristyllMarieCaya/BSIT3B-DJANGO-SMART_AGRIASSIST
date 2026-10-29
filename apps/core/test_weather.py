from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.core.weather import _font_awesome_icon, get_weather


class WeatherIconTests(SimpleTestCase):
    def test_day_and_night_clear_sky_icons_are_mapped(self):
        self.assertEqual(_font_awesome_icon('01d'), 'sun')
        self.assertEqual(_font_awesome_icon('01n'), 'moon')

    def test_common_weather_conditions_map_to_valid_icon_names(self):
        self.assertEqual(_font_awesome_icon('10d'), 'cloud-rain')
        self.assertEqual(_font_awesome_icon('11n'), 'cloud-bolt')
        self.assertEqual(_font_awesome_icon('unknown'), 'cloud')

    @patch('apps.core.weather._safe_request')
    def test_weather_response_maps_forecast_and_handles_missing_values(self, safe_request):
        response = Mock(status_code=200)
        response.json.return_value = {
            'current': {
                'temperature_2m': 28.5,
                'apparent_temperature': None,
                'relative_humidity_2m': None,
                'precipitation': 1.2,
                'weather_code': 2,
                'wind_speed_10m': 4.5,
            },
            'daily': {
                'time': ['2026-10-29'],
                'weather_code': [61],
                'temperature_2m_max': [None],
                'temperature_2m_min': [22.0],
                'precipitation_sum': [3.5],
                'precipitation_probability_max': [80],
            },
        }
        safe_request.return_value = response

        weather = get_weather(10.0, 20.0, units='imperial', location_name='Test Farm')

        self.assertTrue(weather['available'])
        self.assertEqual(weather['current']['precip_unit'], 'inch')
        self.assertEqual(weather['current']['feels_like'], 28.5)
        self.assertEqual(weather['forecast'][0]['date'], '2026-10-29')
        self.assertEqual(weather['forecast'][0]['description'], 'Slight rain showers')
        self.assertEqual(weather['forecast'][0]['temperature_max'], 0.0)
        self.assertEqual(weather['forecast'][0]['temperature_min'], 22.0)
        self.assertEqual(weather['forecast'][0]['rain_sum'], 3.5)
        self.assertEqual(weather['forecast'][0]['precip_unit'], 'inch')
