from django.test import SimpleTestCase

from apps.core.weather import _font_awesome_icon


class WeatherIconTests(SimpleTestCase):
    def test_day_and_night_clear_sky_icons_are_mapped(self):
        self.assertEqual(_font_awesome_icon('01d'), 'sun')
        self.assertEqual(_font_awesome_icon('01n'), 'moon')

    def test_common_weather_conditions_map_to_valid_icon_names(self):
        self.assertEqual(_font_awesome_icon('10d'), 'cloud-rain')
        self.assertEqual(_font_awesome_icon('11n'), 'cloud-bolt')
        self.assertEqual(_font_awesome_icon('unknown'), 'cloud')
