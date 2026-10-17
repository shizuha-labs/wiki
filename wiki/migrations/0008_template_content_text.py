from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wiki', '0007_upload_intent_cleanup_claim'),
    ]

    operations = [
        migrations.AddField(
            model_name='template',
            name='content_text',
            field=models.TextField(blank=True),
        ),
    ]
