from datetime import date, datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.crops.growth_engine import CROP_PROFILES, calculate_crop_growth, get_crop_profile
from apps.crops.models import Crop, ScheduledReminder


@login_required
def crop_tracker(request):
    """List registered crops, lifecycle progress, and upcoming farming activities."""
    crops = Crop.objects.filter(owner=request.user)
    status_filter = request.GET.get('status', 'active')

    if status_filter and status_filter != 'all':
        crops = crops.filter(status=status_filter)

    reminders = (
        ScheduledReminder.objects.filter(user=request.user)
        .select_related('crop')
        .order_by('due_date')
    )
    pending_reminders = reminders.filter(status=ScheduledReminder.Status.PENDING)[:10]

    active_count = Crop.objects.filter(owner=request.user, status=Crop.Status.ACTIVE).count()
    harvested_count = Crop.objects.filter(owner=request.user, status=Crop.Status.HARVESTED).count()

    context = {
        'crops': crops,
        'status_filter': status_filter,
        'pending_reminders': pending_reminders,
        'active_count': active_count,
        'harvested_count': harvested_count,
        'available_crops': list(CROP_PROFILES.keys()),
    }
    return render(request, 'crops/crop_list.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def crop_add(request):
    """Register a new crop with automatic growth calculations and care reminders."""
    if request.method == 'POST':
        crop_name = request.POST.get('crop_name', '').strip()
        variety = request.POST.get('variety', '').strip()
        planting_date_str = request.POST.get('planting_date', '').strip()
        farm_location = request.POST.get('farm_location', '').strip()
        field_name = request.POST.get('field_name', '').strip()
        expected_duration_raw = request.POST.get('expected_duration_days', '').strip()
        area_sqm_raw = request.POST.get('area_sqm', '0').strip()
        notes = request.POST.get('notes', '').strip()

        errors = []
        if not crop_name:
            errors.append('Crop name is required.')
        if not planting_date_str:
            errors.append('Planting date is required.')

        try:
            planting_date = datetime.strptime(planting_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            errors.append('Invalid planting date format. Use YYYY-MM-DD.')
            planting_date = None

        profile = get_crop_profile(crop_name)
        duration = profile.get('default_duration_days', 90)
        if expected_duration_raw:
            try:
                duration = max(10, int(expected_duration_raw))
            except ValueError:
                pass

        try:
            area_sqm = float(area_sqm_raw) if area_sqm_raw else 0.0
        except ValueError:
            area_sqm = 0.0

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(
                request,
                'crops/crop_form.html',
                {
                    'action': 'add',
                    'available_crops': list(CROP_PROFILES.keys()),
                    'form_data': request.POST,
                },
            )

        crop = Crop.objects.create(
            owner=request.user,
            crop_name=crop_name,
            variety=variety,
            planting_date=planting_date,
            farm_location=farm_location,
            field_name=field_name,
            expected_duration_days=duration,
            area_sqm=area_sqm,
            notes=notes,
            status=Crop.Status.ACTIVE,
        )

        # Generate automated stage-based reminders
        _generate_crop_reminders(crop)

        messages.success(
            request,
            f'"{crop.crop_name}" registered successfully! Growth timeline and reminders generated.',
        )
        return redirect('crops:crop_detail', pk=crop.pk)

    return render(
        request,
        'crops/crop_form.html',
        {
            'action': 'add',
            'available_crops': list(CROP_PROFILES.keys()),
            'today': date.today().isoformat(),
        },
    )


@login_required
def crop_detail(request, pk):
    """View detailed timeline, growth milestones, and stage activities for a crop."""
    crop = get_object_or_404(Crop, pk=pk, owner=request.user)
    growth = crop.growth_data
    reminders = crop.reminders.all().order_by('due_date')

    context = {
        'crop': crop,
        'growth': growth,
        'reminders': reminders,
    }
    return render(request, 'crops/crop_detail.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def crop_edit(request, pk):
    """Edit crop details and update growth schedule."""
    crop = get_object_or_404(Crop, pk=pk, owner=request.user)

    if request.method == 'POST':
        crop.crop_name = request.POST.get('crop_name', crop.crop_name).strip()
        crop.variety = request.POST.get('variety', '').strip()
        planting_date_str = request.POST.get('planting_date', '').strip()
        crop.farm_location = request.POST.get('farm_location', '').strip()
        crop.field_name = request.POST.get('field_name', '').strip()
        crop.status = request.POST.get('status', crop.status)
        crop.notes = request.POST.get('notes', '').strip()

        duration_raw = request.POST.get('expected_duration_days', '').strip()
        if duration_raw:
            try:
                crop.expected_duration_days = max(10, int(duration_raw))
            except ValueError:
                pass

        area_raw = request.POST.get('area_sqm', '').strip()
        if area_raw:
            try:
                crop.area_sqm = max(0.0, float(area_raw))
            except ValueError:
                pass

        if planting_date_str:
            try:
                crop.planting_date = datetime.strptime(planting_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        crop.save()
        messages.success(request, f'"{crop.crop_name}" updated successfully.')
        return redirect('crops:crop_detail', pk=crop.pk)

    return render(
        request,
        'crops/crop_form.html',
        {
            'action': 'edit',
            'crop': crop,
            'available_crops': list(CROP_PROFILES.keys()),
        },
    )


@login_required
@require_POST
def crop_delete(request, pk):
    """Delete a registered crop."""
    crop = get_object_or_404(Crop, pk=pk, owner=request.user)
    name = crop.crop_name
    crop.delete()
    messages.success(request, f'Crop "{name}" was removed.')
    return redirect('crops:crop_tracker')


@login_required
@require_POST
def toggle_reminder(request, pk):
    """Toggle a reminder between completed and pending."""
    reminder = get_object_or_404(ScheduledReminder, pk=pk, user=request.user)
    if reminder.status == ScheduledReminder.Status.COMPLETED:
        reminder.status = ScheduledReminder.Status.PENDING
        reminder.completed_at = None
    else:
        reminder.status = ScheduledReminder.Status.COMPLETED
        reminder.completed_at = timezone.now()
    reminder.save()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'status': 'success',
            'reminder_id': reminder.pk,
            'new_status': reminder.status,
            'is_completed': reminder.status == ScheduledReminder.Status.COMPLETED,
        })
    return redirect(request.META.get('HTTP_REFERER', 'crops:crop_tracker'))


@login_required
def crop_stage_preview_api(request):
    """Dynamic preview endpoint used by frontend when farmer selects crop & planting date."""
    crop_name = request.GET.get('crop_name', '').strip()
    planting_date_str = request.GET.get('planting_date', '').strip()
    duration_str = request.GET.get('duration', '').strip()

    if not crop_name:
        return JsonResponse({'error': 'crop_name is required'}, status=400)

    try:
        planting_date = datetime.strptime(planting_date_str, '%Y-%m-%d').date() if planting_date_str else date.today()
    except ValueError:
        planting_date = date.today()

    duration = int(duration_str) if duration_str and duration_str.isdigit() else None
    growth = calculate_crop_growth(crop_name, planting_date, custom_duration=duration)

    milestones_json = []
    for m in growth.get('milestones', []):
        milestones_json.append({
            'name': m['name'],
            'order': m['order'],
            'start_day': m['start_day'],
            'end_day': m['end_day'],
            'start_date': m['start_date'].isoformat(),
            'end_date': m['end_date'].isoformat(),
            'description': m['description'],
            'activities': m.get('activities', []),
            'fertilizer_guidance': m.get('fertilizer_guidance', ''),
        })

    return JsonResponse({
        'crop_name': crop_name,
        'planting_date': growth['planting_date'].isoformat(),
        'total_duration_days': growth['total_duration_days'],
        'estimated_harvest_date': growth['estimated_harvest_date'].isoformat(),
        'days_until_harvest': growth['days_until_harvest'],
        'milestones': milestones_json,
        'water_need': growth.get('water_need', 'Moderate'),
    })


def _generate_crop_reminders(crop: Crop):
    """Generate activity reminders for the crop's milestone stages."""
    milestones = crop.milestones
    for m in milestones:
        stage_name = m['name']
        start_date = m['start_date']

        # Inspection / seedling care reminder at stage start
        if m['order'] == 1:
            ScheduledReminder.objects.get_or_create(
                user=crop.owner,
                crop=crop,
                title=f'{crop.crop_name}: Seedling Care & Emergence Check',
                activity_type=ScheduledReminder.ActivityType.SEEDLING_CARE,
                due_date=start_date,
                defaults={'notes': f'Inspect field "{crop.field_name or "main"}" for uniform emergence.'},
            )
        else:
            ScheduledReminder.objects.get_or_create(
                user=crop.owner,
                crop=crop,
                title=f'{crop.crop_name}: {stage_name} Monitoring',
                activity_type=ScheduledReminder.ActivityType.GROWTH_MONITORING,
                due_date=start_date,
                defaults={'notes': f'Crop entering {stage_name}. Inspect canopy and monitor water/nutrient needs.'},
            )

        # Fertilizer reminder if guidance provided
        if m.get('fertilizer_guidance'):
            ScheduledReminder.objects.get_or_create(
                user=crop.owner,
                crop=crop,
                title=f'{crop.crop_name}: Fertilizer Schedule ({stage_name})',
                activity_type=ScheduledReminder.ActivityType.FERTILIZER,
                due_date=start_date,
                defaults={'notes': m.get('fertilizer_guidance', '')},
            )

    # Harvest preparation reminder 7 days before harvest
    harvest_prep_date = max(crop.planting_date, crop.estimated_harvest_date - timezone.timedelta(days=7))
    ScheduledReminder.objects.get_or_create(
        user=crop.owner,
        crop=crop,
        title=f'{crop.crop_name}: Harvest Preparation & Field Inspection',
        activity_type=ScheduledReminder.ActivityType.HARVEST_PREP,
        due_date=harvest_prep_date,
        defaults={'notes': 'Inspect crop maturity (grain color, fruit firmness), drain excess water, and prepare harvest tools.'},
    )
