"""URLs for apps.info.

All customer-facing Info CRUD endpoints have been removed. The remaining
models (CropGuideline, WeatherRecord, VisualIdentificationLog) are
administered through the Django admin and referenced internally by services.
"""

from django.urls import path

app_name = 'info'

urlpatterns = []
