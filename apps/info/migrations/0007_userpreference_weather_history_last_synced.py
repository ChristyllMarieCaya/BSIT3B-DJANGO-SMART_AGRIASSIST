from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('info', '0006_userpreference_country_userpreference_farm_timezone_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreference',
            name='weather_history_last_synced',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
