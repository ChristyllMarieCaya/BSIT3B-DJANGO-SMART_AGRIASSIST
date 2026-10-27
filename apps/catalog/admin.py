from django.contrib import admin

from .models import CropCatalog


@admin.register(CropCatalog)
class CropCatalogAdmin(admin.ModelAdmin):
    list_display = ('common_name', 'scientific_name', 'category', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('common_name', 'scientific_name', 'description')
    list_editable = ('is_active',)
    readonly_fields = ('created_at', 'updated_at')
