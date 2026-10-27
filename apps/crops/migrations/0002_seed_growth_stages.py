from django.db import migrations
from apps.crops.growth_engine import CROP_PROFILES


def seed_stages(apps, schema_editor):
    CropGrowthStage = apps.get_model('crops', 'CropGrowthStage')
    for crop_name, data in CROP_PROFILES.items():
        for s in data.get('stages', []):
            CropGrowthStage.objects.get_or_create(
                crop_name=crop_name,
                stage_order=s['order'],
                defaults={
                    'stage_name': s['name'],
                    'start_day': s['start_day'],
                    'end_day': s['end_day'],
                    'description': s['description'],
                    'fertilizer_guidance': s.get('fertilizer_guidance', ''),
                    'weather_vulnerabilities': s.get('weather_vulnerability', ''),
                },
            )


def unseed_stages(apps, schema_editor):
    CropGrowthStage = apps.get_model('crops', 'CropGrowthStage')
    CropGrowthStage.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('crops', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_stages, unseed_stages),
    ]
