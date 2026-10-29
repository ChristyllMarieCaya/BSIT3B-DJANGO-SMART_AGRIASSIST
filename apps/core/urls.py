from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset_form.html',
            email_template_name='auth/password_reset_email.html',
            subject_template_name='auth/password_reset_subject.txt',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
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
    path('diagnoses/delete/', views.diagnoses_delete, name='diagnoses_delete'),
    path('diagnoses/<int:pk>/delete/', views.diagnosis_delete, name='diagnosis_delete'),
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
