from datetime import date

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.info.models import CropGuideline, Notification, UserPreference, VisualIdentificationLog


def _preference_enabled(user, field_name):
    try:
        preferences = user.preference
    except UserPreference.DoesNotExist:
        return True
    return getattr(preferences, field_name)


def _format_date(value, include_year=False):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    date_format = '%b %d, %Y' if include_year else '%b %d'
    return value.strftime(date_format).replace(' 0', ' ')


@receiver(post_save, sender=VisualIdentificationLog)
def notify_for_field_observation(sender, instance, created, **kwargs):
    if not created or not instance.findings.strip():
        return
    if not _preference_enabled(instance.owner, 'pest_disease_advisories_enabled'):
        return

    Notification.objects.get_or_create(
        deduplication_key=f'field-observation:{instance.pk}',
        defaults={
            'user': instance.owner,
            'title': f'Field observation recorded: {instance.field_name}',
            'message': (
                f'Observation from {instance.field_name} on {_format_date(instance.inspected_on)}: '
                f'{instance.findings}. Review and confirm the findings before taking action.'
            ),
            'category': Notification.Category.PEST_DISEASE,
            'priority': Notification.Priority.NORMAL,
            'source_type': 'field_observation',
            'source_id': str(instance.pk),
        },
    )


@receiver(post_save, sender=CropGuideline)
def notify_for_crop_registration(sender, instance, created, **kwargs):
    if not created or not _preference_enabled(instance.owner, 'crop_care_reminders_enabled'):
        return

    dates = f'Sowing date: {_format_date(instance.sow_date, include_year=True)}.'
    if instance.harvest_date:
        dates += f' Planned harvest date: {_format_date(instance.harvest_date, include_year=True)}.'
    Notification.objects.get_or_create(
        deduplication_key=f'crop-guideline:{instance.pk}',
        defaults={
            'user': instance.owner,
            'title': f'Crop registered: {instance.crop_name}',
            'message': f'{dates} Review your crop care plan and update it as field activities are completed.',
            'category': Notification.Category.CROP_CARE,
            'priority': Notification.Priority.NORMAL,
            'source_type': 'crop_guideline',
            'source_id': str(instance.pk),
        },
    )
