from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Conversation, CropDiagnosis, Message

User = get_user_model()

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class UserRoleFilter(admin.SimpleListFilter):
    title = _('account role')
    parameter_name = 'account_role'

    def lookups(self, request, model_admin):
        return (
            ('administrator', _('Administrators')),
            ('farmer', _('Farmers')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'administrator':
            return queryset.filter(is_staff=True)
        if self.value() == 'farmer':
            return queryset.filter(is_staff=False, is_superuser=False)
        return queryset


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """Admin configuration allowing administrators to easily view, edit, inspect portfolios, change passwords, and manage users."""

    fieldsets = tuple(
        (name, {**options, 'fields': tuple(field for field in options['fields'] if field != 'groups')})
        for name, options in BaseUserAdmin.fieldsets
    )
    filter_horizontal = tuple(field for field in BaseUserAdmin.filter_horizontal if field != 'groups')
    list_display = (
        'user_profile_col',
        'account_role_col',
        'account_status_col',
        'associated_crops_col',
        'active_reminders_col',
        'last_activity_col',
        'user_quick_actions',
    )
    list_filter = (UserRoleFilter, 'is_active', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    list_per_page = 25
    change_list_template = 'admin/users/change_list.html'
    actions = ['deactivate_users', 'activate_users']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            crops_count=Count('registered_crops', distinct=True),
            pending_reminders_count=Count('reminders', filter=Q(reminders__status='pending'), distinct=True),
        )

    def changelist_view(self, request, extra_context=None):
        users = self.model._default_manager.all()
        from apps.crops.models import Crop, ScheduledReminder
        context = {
            'total_registered_users': users.count(),
            'active_registered_users': users.filter(is_active=True).count(),
            'inactive_registered_users': users.filter(is_active=False).count(),
            'total_crops': Crop.objects.count(),
            'pending_reminders': ScheduledReminder.objects.filter(status='pending').count(),
        }
        return super().changelist_view(request, extra_context={**context, **(extra_context or {})})

    @admin.display(description=_('User / Farmer'), ordering='username')
    def user_profile_col(self, obj):
        portfolio_url = reverse('admin_user_portfolio', args=[obj.pk])
        initial = (obj.first_name[:1] or obj.username[:1] or 'U').upper()
        full_name = obj.get_full_name() or obj.username
        sub_text = f"@{obj.username}" if not obj.email else f"@{obj.username} &bull; {obj.email}"
        return format_html(
            '<a href="{}" class="d-inline-flex align-items-center gap-2 text-decoration-none admin-user-link">'
            '<span class="admin-user-avatar-sm">{}</span>'
            '<div>'
            '<div class="fw-bold admin-user-name">{}</div>'
            '<div class="small text-muted">{}</div>'
            '</div>'
            '</a>',
            portfolio_url, initial, full_name, sub_text
        )

    @admin.display(description=_('Role'), ordering='is_staff')
    def account_role_col(self, obj):
        if obj.is_superuser:
            return format_html('<span class="badge bg-purple-lt"><i class="fa-solid fa-shield-halved me-1"></i>Superuser</span>')
        if obj.is_staff:
            return format_html('<span class="badge bg-blue-lt"><i class="fa-solid fa-user-shield me-1"></i>Administrator</span>')
        return format_html('<span class="badge bg-green-lt"><i class="fa-solid fa-seedling me-1"></i>Farmer</span>')

    @admin.display(description=_('Status'), ordering='is_active')
    def account_status_col(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success-lt"><i class="fa-solid fa-circle-check me-1"></i>Active</span>')
        return format_html('<span class="badge bg-danger-lt"><i class="fa-solid fa-circle-xmark me-1"></i>Inactive</span>')

    @admin.display(description=_('Crops'), ordering='crops_count')
    def associated_crops_col(self, obj):
        count = getattr(obj, 'crops_count', None)
        if count is None:
            count = obj.registered_crops.count()
        if count > 0:
            url = f"{reverse('admin:crops_crop_changelist')}?owner__id__exact={obj.pk}"
            return format_html(
                '<a href="{}" class="badge bg-success text-white text-decoration-none d-inline-flex align-items-center gap-1" title="View crops">'
                '<i class="fa-solid fa-wheat-awn"></i> {} crops</a>',
                url, count
            )
        return format_html('<span class="text-muted small">0</span>')

    @admin.display(description=_('Active Reminders'), ordering='pending_reminders_count')
    def active_reminders_col(self, obj):
        count = getattr(obj, 'pending_reminders_count', None)
        if count is None:
            count = obj.reminders.filter(status='pending').count()
        if count > 0:
            url = f"{reverse('admin:crops_scheduledreminder_changelist')}?user__id__exact={obj.pk}&status__exact=pending"
            return format_html(
                '<a href="{}" class="badge bg-warning text-dark text-decoration-none d-inline-flex align-items-center gap-1" title="View active reminders">'
                '<i class="fa-regular fa-clock"></i> {} active</a>',
                url, count
            )
        return format_html('<span class="text-muted small">0</span>')

    @admin.display(description=_('Last Activity'), ordering='last_login')
    def last_activity_col(self, obj):
        if not obj.last_login:
            return format_html('<span class="text-muted small">Never</span>')
        return obj.last_login.strftime('%b %d, %Y %H:%M')

    @admin.display(description='Actions')
    def user_quick_actions(self, obj):
        portfolio_url = reverse('admin_user_portfolio', args=[obj.pk])
        password_url = reverse('admin:auth_user_password_change', args=[obj.pk])
        delete_url = reverse('admin:auth_user_delete', args=[obj.pk])
        return format_html(
            '<div class="d-inline-flex gap-1 align-items-center">'
            '<a href="{}" class="btn btn-sm btn-success py-1 px-2 text-white d-inline-flex align-items-center gap-1" style="font-size: 11px; text-decoration: none;" title="Inspect Farmer Portfolio">'
            '<i class="fa-solid fa-id-card"></i> <span>Portfolio</span></a>'
            '<a href="{}" class="btn btn-sm btn-outline-secondary py-1 px-2" style="font-size: 11px; text-decoration: none;" title="Change Password">'
            '<i class="fa-solid fa-key"></i></a>'
            '<a href="{}" class="btn btn-sm btn-outline-danger py-1 px-2" style="font-size: 11px; text-decoration: none;" title="Delete User">'
            '<i class="fa-solid fa-trash"></i></a>'
            '</div>',
            portfolio_url,
            password_url,
            delete_url,
        )

    @admin.action(description=_('🚫 Deactivate selected user accounts'))
    def deactivate_users(self, request, queryset):
        if not request.POST.get('confirm_action'):
            return self._confirm_account_action(request, queryset, 'deactivate_users', _('Deactivate accounts'))
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} user account(s) deactivated.', messages.WARNING)

    @admin.action(description=_('✅ Activate selected user accounts'))
    def activate_users(self, request, queryset):
        if not request.POST.get('confirm_action'):
            return self._confirm_account_action(request, queryset, 'activate_users', _('Activate accounts'))
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user account(s) activated.', messages.SUCCESS)

    def _confirm_account_action(self, request, queryset, action, title):
        from django.template.response import TemplateResponse

        return TemplateResponse(request, 'admin/users/confirm_action.html', {
            **self.admin_site.each_context(request),
            'title': title,
            'action_name': action,
            'users': queryset,
            'selected_ids': [str(user.pk) for user in queryset],
            'opts': self.model._meta,
        })


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
