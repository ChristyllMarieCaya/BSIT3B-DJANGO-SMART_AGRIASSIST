from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import CropCatalogAdminForm
from .models import CropCatalog


@admin.register(CropCatalog)
class CropCatalogAdmin(admin.ModelAdmin):
    list_display = ('common_name', 'scientific_name', 'category', 'is_active', 'display_actions')
    list_filter = ('category', 'is_active')
    search_fields = ('common_name', 'scientific_name', 'description')
    list_editable = ('is_active',)
    readonly_fields = ('created_at', 'updated_at')
    form = CropCatalogAdminForm
    change_list_template = 'admin/catalog/cropcatalog/change_list.html'

    def get_urls(self):
        opts = self.model._meta
        custom_urls = [
            path(
                '<int:object_id>/edit-crop/',
                self.admin_site.admin_view(self.edit_crop_view),
                name=f'{opts.app_label}_{opts.model_name}_edit_crop',
            ),
            path(
                '<int:object_id>/delete-crop/',
                self.admin_site.admin_view(self.delete_crop_view),
                name=f'{opts.app_label}_{opts.model_name}_delete_crop',
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.display(description='Actions', ordering=None)
    def display_actions(self, obj):
        edit_url = reverse(
            f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_edit_crop',
            args=(obj.pk,),
        )
        delete_url = reverse(
            f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_delete_crop',
            args=(obj.pk,),
        )
        return format_html(
            '<div class="crop-row-actions">'
            '<button type="button" class="crop-action-button crop-action-edit" '
            'data-crop-edit-url="{}" aria-label="Edit {}" title="Edit">'
            '<i class="fa-solid fa-pen-to-square" aria-hidden="true"></i> Edit</button>'
            '<button type="button" class="crop-action-button crop-action-delete" '
            'data-crop-delete-url="{}" data-crop-name="{}" aria-label="Delete {}" title="Delete">'
            '<i class="fa-solid fa-trash" aria-hidden="true"></i> Delete</button>'
            '</div>',
            edit_url,
            obj.common_name,
            delete_url,
            obj.common_name,
            obj.common_name,
        )

    def edit_crop_view(self, request, object_id):
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        crop = get_object_or_404(CropCatalog, pk=object_id)
        if not self.has_change_permission(request, crop):
            return HttpResponseForbidden('You do not have permission to change crops.')
        if request.method == 'GET':
            form = CropCatalogAdminForm(instance=crop)
            return JsonResponse({
                'form_html': form.as_p(),
                'photo_url': crop.photo_url,
                'crop_name': crop.common_name,
            })

        old_photo = crop.reference_photo
        form = CropCatalogAdminForm(request.POST, request.FILES, instance=crop)
        if not form.is_valid():
            return JsonResponse({
                'ok': False,
                'form_html': form.as_p(),
                'photo_url': crop.photo_url,
            }, status=400)

        with transaction.atomic():
            updated_crop = form.save()
        if old_photo and old_photo.name != updated_crop.reference_photo.name:
            old_photo.storage.delete(old_photo.name)
        messages.success(request, f'{updated_crop.common_name} was updated.')
        return JsonResponse({'ok': True})

    def delete_crop_view(self, request, object_id):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        crop = get_object_or_404(CropCatalog, pk=object_id)
        if not self.has_delete_permission(request, crop):
            return HttpResponseForbidden('You do not have permission to delete crops.')
        crop_name = crop.common_name
        photo = crop.reference_photo
        with transaction.atomic():
            crop.delete()
        if photo:
            photo.storage.delete(photo.name)
        messages.success(request, f'{crop_name} was deleted from the catalog.')
        return JsonResponse({'ok': True})
