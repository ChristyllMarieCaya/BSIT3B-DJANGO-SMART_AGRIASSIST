import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_add_message_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='client_request_id',
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='message',
            name='reply_to',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='assistant_reply',
                to='core.message',
            ),
        ),
    ]
