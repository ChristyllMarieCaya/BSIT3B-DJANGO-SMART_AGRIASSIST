from datetime import date
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.crops.models import Crop, CropGrowthStage, ScheduledReminder
from apps.crops.views import _generate_crop_reminders
from apps.crops.admin_actions import (
    export_crops_csv,
    generate_stage_reminders,
    mark_as_active,
    mark_as_harvested,
    mark_as_lost,
    mark_reminders_cancelled,
    mark_reminders_completed,
)


class ScheduledReminderInline(admin.TabularInline):
    """Inline area to view and manage reminders directly on a Crop's edit page."""
    model = ScheduledReminder
    extra = 1
    fields = ('title', 'activity_type', 'due_date', 'status', 'is_automated')
    show_change_link = True
    classes = ('collapse',)


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = (
        'crop_name_badge',
        'variety',
        'owner',
        'farm_location',
        'field_name',
        'formatted_area',
        'planting_date',
        'growth_progress_bar',
        'current_stage_badge',
        'days_until_harvest_display',
        'weather_risk',
        'status_badge',
    )
    list_filter = (
        'status',
        'crop_name',
        'farm_location',
        ('planting_date', admin.DateFieldListFilter),
    )
    search_fields = (
        'crop_name',
        'variety',
        'field_name',
        'farm_location',
        'owner__username',
        'owner__email',
    )
    date_hierarchy = 'planting_date'
    ordering = ('-planting_date', 'crop_name')
    list_per_page = 25
    raw_id_fields = ('owner',)
    inlines = [ScheduledReminderInline]

    fieldsets = (
        (_('1. Basic Information'), {
            'fields': (
                ('crop_name', 'variety'),
                ('owner', 'status'),
            )
        }),
        (_('2. Land & Area Specification'), {
            'description': _('Field identification and total planted land coverage.'),
            'fields': (
                ('farm_location', 'field_name'),
                ('area_sqm', 'formatted_area_preview'),
            )
        }),
        (_('3. Planting Schedule & Duration'), {
            'fields': (
                ('planting_date', 'expected_duration_days'),
            )
        }),
        (_('4. Live Growth Analytics (Engine Telemetry)'), {
            'description': _('Real-time crop metrics evaluated from planting date and agronomic reference data.'),
            'fields': (
                ('current_stage_badge', 'days_since_planting_display'),
                ('growth_progress_bar', 'days_until_harvest_display'),
                'estimated_harvest_display',
                'recommended_care_tasks',
            )
        }),
        (_('5. Health & Risk Cross-Intelligence'), {
            'description': _('Cross-referenced AI pest/disease diagnoses and active local weather warnings.'),
            'fields': (
                'ai_health_status',
                'weather_risk_detail',
            )
        }),
        (_('6. Agronomic Notes & Field Observations'), {
            'classes': ('collapse',),
            'fields': ('notes',)
        }),
        (_('7. System Audit Timestamps'), {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at')
        }),
    )

    readonly_fields = (
        'created_at',
        'updated_at',
        'formatted_area_preview',
        'growth_progress_bar',
        'current_stage_badge',
        'days_since_planting_display',
        'days_until_harvest_display',
        'estimated_harvest_display',
        'recommended_care_tasks',
        'ai_health_status',
        'weather_risk_detail',
    )

    actions = [
        generate_stage_reminders,
        export_crops_csv,
        mark_as_harvested,
        mark_as_lost,
        mark_as_active,
    ]

    def save_model(self, request, obj, form, change):
        """Automatically generate stage reminders when a crop is added through admin."""
        super().save_model(request, obj, form, change)
        if not change:
            try:
                _generate_crop_reminders(obj)
                self.message_user(
                    request,
                    f'Automated lifecycle reminders generated for "{obj.crop_name}".',
                    messages.INFO,
                )
            except Exception as e:
                self.message_user(
                    request,
                    f'Note: Reminders could not be auto-generated: {e}',
                    messages.WARNING,
                )

    # --- Area Formatting & Conversions ---
    @admin.display(description='Planted Area', ordering='area_sqm')
    def formatted_area(self, obj):
        if not obj.area_sqm:
            return '-'
        sqm = float(obj.area_sqm)
        hectares = sqm / 10000.0
        if hectares >= 1.0:
            return f'{sqm:,.0f} m² ({hectares:,.2f} ha)'
        return f'{sqm:,.0f} m²'

    @admin.display(description='Area Conversion Preview')
    def formatted_area_preview(self, obj):
        if not obj.area_sqm:
            return 'Enter area in square meters above to preview conversions.'
        sqm = float(obj.area_sqm)
        hectares = sqm / 10000.0
        acres = sqm * 0.000247105
        sqm_str = f'{sqm:,.2f} m²'
        ha_str = f'{hectares:,.3f} ha'
        acres_str = f'{acres:,.3f} acres'
        return format_html(
            '<div style="font-size: 13px; line-height: 1.6;">'
            '📐 <strong>{}</strong> (Square Meters)<br>'
            '🌾 <strong>{}</strong> (Hectares)<br>'
            '🚜 <strong>{}</strong>'
            '</div>',
            sqm_str, ha_str, acres_str
        )

    # --- Visual Display Badges ---
    @admin.display(description='Crop Name', ordering='crop_name')
    def crop_name_badge(self, obj):
        return format_html('<strong>{}</strong>', obj.crop_name.capitalize())

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        colors = {
            Crop.Status.ACTIVE: '#28a745',     # Green
            Crop.Status.HARVESTED: '#007bff',  # Blue
            Crop.Status.LOST: '#dc3545',       # Red
            Crop.Status.PLANNED: '#ffc107',    # Amber
        }
        text_colors = {
            Crop.Status.PLANNED: '#212529',
        }
        bg = colors.get(obj.status, '#6c757d')
        fg = text_colors.get(obj.status, '#ffffff')
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; text-transform: uppercase;">{}</span>',
            bg, fg, obj.get_status_display()
        )

    @admin.display(description='Growth Progress')
    def growth_progress_bar(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return 'Calculated upon saving with planting date'
        try:
            pct = min(max(float(obj.overall_progress), 0.0), 100.0)
        except (ValueError, TypeError):
            pct = 0.0
        bar_color = '#22c55e' if pct < 100 else '#0ea5e9'
        pct_formatted = f'{pct:.1f}%'
        bar_style = f'width: {pct:.1f}%; background: {bar_color}; height: 100%;'
        return format_html(
            '<div style="display: flex; align-items: center; gap: 8px; min-width: 120px;">'
            '<div style="flex-grow: 1; background: rgba(255,255,255,0.08); border-radius: 4px; height: 8px; overflow: hidden;">'
            '<div style="{}"></div>'
            '</div>'
            '<span style="font-size: 11px; font-weight: bold; width: 38px; text-align: right; color: #fff;">{}</span>'
            '</div>',
            bar_style, pct_formatted
        )

    @admin.display(description='Current Stage')
    def current_stage_badge(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return 'Pending planting date'
        stage_name = obj.current_stage_name or 'Establishing'
        return format_html(
            '<span style="background: #e2f0d9; color: #276a3c; padding: 2px 7px; border-radius: 3px; font-weight: 500; font-size: 11px;">🌱 {}</span>',
            stage_name
        )

    @admin.display(description='Days Since Planting')
    def days_since_planting_display(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return '-'
        days = obj.days_since_planting
        return f'Sowing in {abs(days)} day(s)' if days < 0 else f'{days} day(s)'

    @admin.display(description='Days Until Harvest')
    def days_until_harvest_display(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return '-'
        days = obj.days_until_harvest
        if days <= 0:
            return format_html('<span style="color: #0ea5e9; font-weight: bold;">Ready for Harvest</span>')
        return f'{days} day(s)'

    @admin.display(description='Estimated Harvest Date')
    def estimated_harvest_display(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return '-'
        d = obj.estimated_harvest_date
        return d.strftime('%B %d, %Y') if d else 'Not calculated'

    @admin.display(description='Recommended Care Tasks')
    def recommended_care_tasks(self, obj):
        if not obj or not getattr(obj, 'planting_date', None):
            return 'Available after saving with planting date.'
        activities = obj.recommended_activities
        if not activities:
            return 'No current stage care guidelines available.'
        items = ''.join([f'<li style="margin-bottom: 4px;">{act}</li>' for act in activities])
        return format_html('<ul style="margin: 0; padding-left: 20px; color: #495057;">{}</ul>', format_html(items))

    # --- Cross-App Intelligence: AI Diagnoses & Weather Alerts ---
    @admin.display(description='AI Health Flags')
    def ai_health_status(self, obj):
        if not obj or not getattr(obj, 'owner_id', None) or not getattr(obj, 'crop_name', None):
            return 'Available after saving crop record.'
        try:
            from apps.core.models import CropDiagnosis
            diagnoses = CropDiagnosis.objects.filter(
                user=obj.owner,
                crop_name__icontains=obj.crop_name,
            ).order_by('-created_at')[:4]

            if not diagnoses.exists():
                return format_html('<span style="color: #28a745;">✅ No reported disease or pest issues for this crop.</span>')

            items = []
            for d in diagnoses:
                badge = ' <span style="background:#28a745;color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;">Confirmed</span>' if d.is_confirmed else ''
                items.append(
                    f'<li style="margin-bottom: 4px;"><strong>{d.possible_disease}</strong> — {d.confidence_level} confidence{badge} ({d.created_at.strftime("%b %d, %Y")})</li>'
                )
            return format_html(
                '<div style="color: #b02a37;"><strong>Recent AI Diagnoses logged by {}:</strong>'
                '<ul style="margin: 4px 0 0 18px; padding: 0;">{}</ul></div>',
                obj.owner.username,
                format_html(''.join(items)),
            )
        except Exception:
            return 'Unavailable'

    @admin.display(description='Weather Risk')
    def weather_risk(self, obj):
        if not obj.farm_location:
            return '-'
        try:
            from apps.info.models import WeatherAlert
            alert = WeatherAlert.objects.filter(
                is_active=True,
                farm_location__icontains=obj.farm_location,
            ).first()
            if alert:
                return format_html(
                    '<span style="background: #dc3545; color: #fff; padding: 2px 7px; border-radius: 3px; font-weight: 600; font-size: 11px;">⛈️ {}</span>',
                    alert.title[:20],
                )
        except Exception:
            pass
        return format_html('<span style="color: #28a745; font-size: 11px;">Clear</span>')

    @admin.display(description='Active Weather Alerts for Location')
    def weather_risk_detail(self, obj):
        if not obj.farm_location:
            return 'No farm location specified on this crop record.'
        try:
            from apps.info.models import WeatherAlert
            alerts = WeatherAlert.objects.filter(
                is_active=True,
                farm_location__icontains=obj.farm_location,
            )
            if not alerts.exists():
                return format_html('<span style="color: #28a745;">✅ No active severe weather warnings for "{}"</span>', obj.farm_location)
            items = []
            for a in alerts:
                items.append(f'<li><strong>{a.title}</strong> ({a.get_severity_display()} severity) — {a.created_at.strftime("%b %d")}</li>')
            return format_html(
                '<div style="color: #dc3545;"><strong>Active Advisories in {}:</strong><ul>{}</ul></div>',
                obj.farm_location,
                format_html(''.join(items)),
            )
        except Exception:
            return 'Weather alert telemetry unavailable.'


@admin.register(CropGrowthStage)
class CropGrowthStageAdmin(admin.ModelAdmin):
    list_display = ('crop_name', 'stage_order', 'stage_name', 'start_day', 'end_day', 'duration_display')
    list_filter = ('crop_name',)
    ordering = ('crop_name', 'stage_order')
    search_fields = ('crop_name', 'stage_name', 'description')

    fieldsets = (
        (_('Stage Timing'), {
            'fields': (('crop_name', 'stage_order'), 'stage_name', ('start_day', 'end_day'))
        }),
        (_('Agronomic Guidance'), {
            'fields': ('description', 'recommended_care', 'water_requirements', 'fertilizer_guidance')
        }),
        (_('Risk Vulnerabilities'), {
            'classes': ('collapse',),
            'fields': ('weather_vulnerabilities',)
        }),
    )

    @admin.display(description='Stage Duration')
    def duration_display(self, obj):
        days = obj.end_day - obj.start_day
        return f'{days} days (Days {obj.start_day}–{obj.end_day})'


@admin.register(ScheduledReminder)
class ScheduledReminderAdmin(admin.ModelAdmin):
    list_display = (
        'title_with_crop',
        'crop_display',
        'assigned_user_display',
        'activity_type_pill',
        'due_date_display',
        'overdue_status_pill',
        'status_badge_display',
        'automation_badge',
    )
    list_display_links = ('title_with_crop',)
    list_filter = ('status', 'activity_type', 'is_automated', 'due_date')
    search_fields = ('title', 'notes', 'user__username', 'user__first_name', 'user__last_name', 'crop__crop_name', 'crop__field_name')
    date_hierarchy = 'due_date'
    ordering = ('due_date', 'status')
    raw_id_fields = ('user', 'crop')
    actions = [mark_reminders_completed, mark_reminders_cancelled]

    fieldsets = (
        ('Reminder Classification & Target', {
            'description': 'Assign the reminder to a farmer user and target crop.',
            'fields': (
                ('user', 'crop'),
                'title',
                'activity_type',
            ),
        }),
        ('Schedule & Execution State', {
            'description': 'Specify target completion dates, automation triggers, and progress status.',
            'fields': (
                ('due_date', 'status'),
                'is_automated',
                'completed_at',
            ),
        }),
        ('Agronomic Guidance & Instructions', {
            'description': 'Detailed instructions, application quantities, or agronomic guidelines.',
            'fields': ('notes',),
        }),
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        today = date.today()
        qs = ScheduledReminder.objects.all()
        extra_context.update({
            'total_reminders_count': qs.count(),
            'pending_reminders_count': qs.filter(status=ScheduledReminder.Status.PENDING).count(),
            'overdue_reminders_count': qs.filter(status=ScheduledReminder.Status.PENDING, due_date__lt=today).count(),
            'completed_reminders_count': qs.filter(status=ScheduledReminder.Status.COMPLETED).count(),
            'automated_reminders_count': qs.filter(is_automated=True).count(),
        })
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description='Title & Field Context', ordering='title')
    def title_with_crop(self, obj):
        subtitle = f'{obj.crop.crop_name} • {obj.crop.field_name or "Field Plot"}' if obj.crop else 'General Farm Task'
        return format_html(
            '<div class="d-flex flex-column">'
            '  <span class="fw-bold text-body" style="font-size: 0.88rem;">{}</span>'
            '  <span class="text-muted small" style="font-size: 0.75rem;">{}</span>'
            '</div>',
            obj.title,
            subtitle,
        )

    @admin.display(description='Target Crop', ordering='crop__crop_name')
    def crop_display(self, obj):
        if not obj.crop:
            return format_html('<span class="text-muted small">&mdash;</span>')
        variety = f' ({obj.crop.variety})' if obj.crop.variety else ''
        return format_html(
            '<span class="badge bg-green-lt"><i class="fa-solid fa-seedling me-1"></i>{}{}</span>',
            obj.crop.crop_name,
            variety,
        )

    @admin.display(description='Assigned Farmer', ordering='user__username')
    def assigned_user_display(self, obj):
        initial = (obj.user.first_name[:1] or obj.user.username[:1]).upper() if obj.user else '?'
        name = obj.user.get_full_name() or obj.user.username if obj.user else 'Unassigned'
        return format_html(
            '<div class="d-inline-flex align-items-center gap-2">'
            '  <span class="admin-user-avatar-sm">{}</span>'
            '  <div class="d-flex flex-column">'
            '    <span class="small fw-semibold text-body">{}</span>'
            '    <span class="text-muted" style="font-size: 0.7rem;">@{}</span>'
            '  </div>'
            '</div>',
            initial,
            name,
            obj.user.username if obj.user else '',
        )

    @admin.display(description='Activity Type', ordering='activity_type')
    def activity_type_pill(self, obj):
        icon_map = {
            ScheduledReminder.ActivityType.SEEDLING_CARE: 'fa-seedling',
            ScheduledReminder.ActivityType.IRRIGATION: 'fa-droplet',
            ScheduledReminder.ActivityType.FERTILIZER: 'fa-flask',
            ScheduledReminder.ActivityType.PEST_INSPECTION: 'fa-bug',
            ScheduledReminder.ActivityType.GROWTH_MONITORING: 'fa-chart-line',
            ScheduledReminder.ActivityType.HARVEST_PREP: 'fa-wheat-awn',
            ScheduledReminder.ActivityType.GENERAL: 'fa-calendar-check',
        }
        activity_class_map = {
            ScheduledReminder.ActivityType.SEEDLING_CARE: 'reminder-activity-seedling',
            ScheduledReminder.ActivityType.IRRIGATION: 'reminder-activity-irrigation',
            ScheduledReminder.ActivityType.FERTILIZER: 'reminder-activity-fertilizer',
            ScheduledReminder.ActivityType.PEST_INSPECTION: 'reminder-activity-pest',
            ScheduledReminder.ActivityType.GROWTH_MONITORING: 'reminder-activity-growth',
            ScheduledReminder.ActivityType.HARVEST_PREP: 'reminder-activity-harvest',
            ScheduledReminder.ActivityType.GENERAL: 'reminder-activity-general',
        }
        icon = icon_map.get(obj.activity_type, 'fa-tasks')
        activity_class = activity_class_map.get(obj.activity_type, 'reminder-activity-general')
        return format_html(
            '<span class="badge reminder-activity-pill {}"><i class="fa-solid {} me-1" aria-hidden="true"></i>{}</span>',
            activity_class,
            icon,
            obj.get_activity_type_display(),
        )

    @admin.display(description='Due Date', ordering='due_date')
    def due_date_display(self, obj):
        today = date.today()
        days_diff = (obj.due_date - today).days
        if days_diff == 0:
            rel = '<span class="badge bg-warning text-dark ms-1">Today</span>'
        elif days_diff == 1:
            rel = '<span class="badge bg-info-lt ms-1">Tomorrow</span>'
        elif days_diff < 0 and obj.status == ScheduledReminder.Status.PENDING:
            rel = f'<span class="badge bg-danger-lt ms-1">{abs(days_diff)}d ago</span>'
        elif days_diff > 0:
            rel = f'<span class="text-muted small ms-1">in {days_diff}d</span>'
        else:
            rel = ''

        return format_html(
            '<div class="d-flex align-items-center gap-1">'
            '  <i class="fa-regular fa-calendar text-muted" style="font-size: 0.8rem;"></i>'
            '  <span class="small text-body">{}</span>'
            '  {}'
            '</div>',
            obj.due_date.strftime('%b %d, %Y'),
            format_html(rel),
        )

    @admin.display(description='Schedule Status')
    def overdue_status_pill(self, obj):
        if obj.status == ScheduledReminder.Status.COMPLETED:
            return format_html('<span class="badge bg-success-lt"><i class="fa-solid fa-check me-1"></i>Fulfilled</span>')
        if obj.is_overdue:
            return format_html('<span class="badge bg-danger text-white"><i class="fa-solid fa-triangle-exclamation me-1"></i>Overdue</span>')
        return format_html('<span class="badge bg-teal-lt"><i class="fa-solid fa-circle-check me-1"></i>On Schedule</span>')

    @admin.display(description='Status', ordering='status')
    def status_badge_display(self, obj):
        badge_configs = {
            ScheduledReminder.Status.PENDING: ('bg-blue-lt', 'fa-clock', 'Pending'),
            ScheduledReminder.Status.COMPLETED: ('bg-success text-white', 'fa-circle-check', 'Completed'),
            ScheduledReminder.Status.OVERDUE: ('bg-danger-lt text-danger', 'fa-circle-exclamation', 'Overdue'),
            ScheduledReminder.Status.CANCELLED: ('bg-secondary-lt text-muted', 'fa-ban', 'Cancelled'),
        }
        css_class, icon, label = badge_configs.get(obj.status, ('bg-secondary-lt', 'fa-circle', obj.get_status_display()))
        return format_html(
            '<span class="badge {}"><i class="fa-solid {} me-1"></i>{}</span>',
            css_class, icon, label
        )

    @admin.display(description='Automation', ordering='is_automated')
    def automation_badge(self, obj):
        if obj.is_automated:
            return format_html(
                '<span class="badge bg-purple-lt" title="System Automated lifecycle trigger"><i class="fa-solid fa-robot me-1"></i>Auto</span>'
            )
        return format_html(
            '<span class="badge bg-light text-muted border" title="Manual farmer reminder"><i class="fa-solid fa-user me-1"></i>Manual</span>'
        )
