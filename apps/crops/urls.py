from django.urls import path
from apps.crops import views

app_name = 'crops'

urlpatterns = [
    path('tracker/', views.crop_tracker, name='crop_tracker'),
    path('tracker/add/', views.crop_add, name='crop_add'),
    path('tracker/<int:pk>/', views.crop_detail, name='crop_detail'),
    path('tracker/<int:pk>/edit/', views.crop_edit, name='crop_edit'),
    path('tracker/<int:pk>/delete/', views.crop_delete, name='crop_delete'),
    path('tracker/reminders/<int:pk>/toggle/', views.toggle_reminder, name='toggle_reminder'),
    path('tracker/api/stage-preview/', views.crop_stage_preview_api, name='stage_preview_api'),
]
