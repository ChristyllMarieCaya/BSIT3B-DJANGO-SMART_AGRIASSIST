from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('home/', views.home, name='dashboard'),
    path('home/chat/', views.chat_view, name='chat'),
    path('assistant/', views.aiassistant_page, name='ai_assistant'),
    path('assistant/status/', views.gemini_status, name='gemini_status'),
    path('chat/conversations/', views.chat_conversations, name='chat_conversations'),
    path('chat/conversations/new/', views.chat_new_conversation, name='chat_new_conversation'),
    path('chat/conversations/<int:conversation_id>/delete/', views.chat_delete_conversation, name='chat_delete_conversation'),
    path('chat/conversations/<int:conversation_id>/clear/', views.chat_clear_conversation, name='chat_clear_conversation'),
    path(
        'chat/conversations/<int:conversation_id>/messages/',
        views.chat_messages,
        name='chat_messages',
    ),
    path('diagnoses/', views.diagnoses_list, name='diagnoses_list'),
    path('diagnoses/<int:pk>/', views.diagnosis_detail, name='diagnosis_detail'),
    path('weather/', views.weather_page, name='weather'),
    path('weather/api/', views.weather_api, name='weather_api'),
    path('notifications/', views.notifications_page, name='notifications'),
    path('notifications/api/', views.notifications_api, name='notifications_api'),
    path('settings/', views.settings_page, name='settings'),
    path('settings/save/', views.settings_save, name='settings_save'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
]
