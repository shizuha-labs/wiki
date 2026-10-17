from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0009_userpreference'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='verify_owner_id',
            field=models.IntegerField(blank=True, help_text='Accountable user for re-verification (Shizuha ID). Defaults to the verifier on first verify.', null=True),
        ),
        migrations.AddField(
            model_name='page',
            name='verified_by_id',
            field=models.IntegerField(blank=True, help_text='User who performed the last verification (Shizuha ID).', null=True),
        ),
        migrations.AddField(
            model_name='page',
            name='verified_at',
            field=models.DateTimeField(blank=True, help_text='When the last verification happened. NULL = unverified.', null=True),
        ),
        migrations.AddField(
            model_name='space',
            name='priority',
            field=models.IntegerField(default=5, help_text='Weight for the freshness review queue ranking (space-admin settable)'),
        ),
    ]
