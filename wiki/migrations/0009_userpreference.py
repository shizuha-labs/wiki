from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wiki', '0008_template_content_text'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPreference',
            fields=[
                ('user_id', models.IntegerField(
                    help_text='Shizuha ID user id',
                    primary_key=True,
                    serialize=False,
                )),
                ('diagrams', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
