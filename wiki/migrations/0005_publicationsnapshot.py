import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wiki', '0004_attachment_uuid_object_keys')]

    operations = [
        migrations.CreateModel(
            name='PublicationSnapshot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('operation_key', models.CharField(max_length=128, unique=True)),
                ('request_digest', models.CharField(max_length=64)),
                ('snapshot_digest', models.CharField(db_index=True, max_length=64)),
                ('organization_id', models.IntegerField(db_index=True)),
                ('publication_result', models.CharField(max_length=100)),
                ('page_tuples', models.JSONField(default=list)),
                ('created_by_id', models.IntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'wiki_publication_snapshot',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['organization_id', '-created_at'], name='wiki_public_organiz_7e5668_idx')],
            },
        ),
    ]
