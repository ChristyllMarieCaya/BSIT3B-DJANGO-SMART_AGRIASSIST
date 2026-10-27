from django.contrib import admin
from .models import Conversation, CropDiagnosis, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('owner', 'started_at', 'last_message_at')
    list_filter = ('started_at',)
    date_hierarchy = 'started_at'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender', 'created_at')
    list_filter = ('created_at',)
    raw_id_fields = ('conversation', 'sender')


@admin.register(CropDiagnosis)
class CropDiagnosisAdmin(admin.ModelAdmin):
    list_display = ('user', 'crop_name', 'possible_disease', 'confidence_level', 'is_confirmed', 'created_at')
    list_filter = ('confidence_level', 'is_confirmed', 'created_at')
    search_fields = ('crop_name', 'possible_disease', 'observed_symptoms', 'user__username')
