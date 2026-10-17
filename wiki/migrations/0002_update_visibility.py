"""
Migration to update Space visibility choices.

- 'public' (old org-visible) → 'org'
- 'restricted' (redundant with private) → 'private'
- Then AlterField with new choices and default='org'
"""
from django.db import migrations, models


def migrate_visibility_forward(apps, schema_editor):
    Space = apps.get_model('wiki', 'Space')
    # Old 'public' meant org-visible, rename to 'org'
    Space.objects.filter(visibility='public').update(visibility='org')
    # 'restricted' was functionally identical to 'private'
    Space.objects.filter(visibility='restricted').update(visibility='private')


def migrate_visibility_reverse(apps, schema_editor):
    Space = apps.get_model('wiki', 'Space')
    # Reverse: 'org' back to 'public'
    Space.objects.filter(visibility='org').update(visibility='public')
    # No good reverse for restricted, leave as private


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0001_initial'),
    ]

    operations = [
        # First migrate the data
        migrations.RunPython(
            migrate_visibility_forward,
            migrate_visibility_reverse,
        ),
        # Then alter the field with new choices + default
        migrations.AlterField(
            model_name='space',
            name='visibility',
            field=models.CharField(
                choices=[
                    ('private', 'Private'),
                    ('org', 'Organization'),
                    ('public', 'Public'),
                ],
                default='org',
                max_length=20,
            ),
        ),
    ]
