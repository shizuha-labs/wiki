import uuid

from django.db import migrations, models
import django.db.models.deletion
import wiki.models


TRIGGER_FUNCTION = r"""
CREATE OR REPLACE FUNCTION wiki_enforce_attachment_identity_immutable()
RETURNS trigger AS $$
BEGIN
    IF OLD.integrity_state = 'unverified_legacy'
       AND OLD.sha256 = ''
       AND NEW.integrity_state = 'verified'
       AND NEW.sha256 ~ '^[0-9a-f]{64}$'
       AND EXISTS (
           SELECT 1
           FROM wiki_attachmentintegritytrustroot trust_root
           WHERE trust_root.attachment_id = OLD.id
             AND trust_root.trust_root_type IN (
                 'recovery_manifest', 'signed_upstream', 'operator_attestation'
             )
             AND trust_root.source_record <> ''
             AND trust_root.expected_size = OLD.file_size
             AND trust_root.expected_sha256 = NEW.sha256
             AND trust_root.expected_storage_version_id = NEW.storage_version_id
       )
       AND ROW(
           OLD.id, OLD.file, OLD.file_size, OLD.mime_type,
           OLD.supersedes_attachment_id
       ) IS NOT DISTINCT FROM ROW(
           NEW.id, NEW.file, NEW.file_size, NEW.mime_type,
           NEW.supersedes_attachment_id
       ) THEN
        RETURN NEW;
    END IF;
    IF OLD.integrity_state IS DISTINCT FROM NEW.integrity_state THEN
        IF NOT (
            NEW.integrity_state IN ('quarantined', 'missing')
            AND OLD.integrity_state IN ('verified', 'unverified_legacy')
        ) THEN
            RAISE EXCEPTION 'invalid attachment integrity state transition'
                USING ERRCODE = '23000';
        END IF;
    END IF;
    IF ROW(
        OLD.id,
        OLD.file,
        OLD.file_size,
        OLD.sha256,
        OLD.mime_type,
        OLD.storage_version_id,
        OLD.supersedes_attachment_id
    ) IS DISTINCT FROM ROW(
        NEW.id,
        NEW.file,
        NEW.file_size,
        NEW.sha256,
        NEW.mime_type,
        NEW.storage_version_id,
        NEW.supersedes_attachment_id
    ) THEN
        RAISE EXCEPTION 'committed attachment identity is immutable'
            USING ERRCODE = '23000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS wiki_attachment_identity_immutable ON wiki_attachment;
CREATE TRIGGER wiki_attachment_identity_immutable
BEFORE UPDATE OF id, file, file_size, sha256, mime_type,
    storage_version_id, supersedes_attachment_id, integrity_state
ON wiki_attachment
FOR EACH ROW EXECUTE FUNCTION wiki_enforce_attachment_identity_immutable();

CREATE OR REPLACE FUNCTION wiki_enforce_attachment_trust_root_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'attachment integrity trust root is immutable'
        USING ERRCODE = '23000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS wiki_attachment_trust_root_immutable
ON wiki_attachmentintegritytrustroot;
CREATE TRIGGER wiki_attachment_trust_root_immutable
BEFORE UPDATE ON wiki_attachmentintegritytrustroot
FOR EACH ROW EXECUTE FUNCTION wiki_enforce_attachment_trust_root_immutable();
"""

DROP_TRIGGER = r"""
DROP TRIGGER IF EXISTS wiki_attachment_identity_immutable ON wiki_attachment;
DROP FUNCTION IF EXISTS wiki_enforce_attachment_identity_immutable();
DROP TRIGGER IF EXISTS wiki_attachment_trust_root_immutable
ON wiki_attachmentintegritytrustroot;
DROP FUNCTION IF EXISTS wiki_enforce_attachment_trust_root_immutable();
"""


def create_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(TRIGGER_FUNCTION)


def drop_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(DROP_TRIGGER)


class Migration(migrations.Migration):

    dependencies = [
        ('wiki', '0005_publicationsnapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attachment',
            name='file',
            field=models.FileField(max_length=1024, upload_to=wiki.models.attachment_upload_to),
        ),
        migrations.AlterField(
            model_name='attachment',
            name='file_size',
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AddField(
            model_name='attachment',
            name='integrity_state',
            field=models.CharField(
                choices=[
                    ('verified', 'Verified'),
                    ('unverified_legacy', 'Unverified legacy'),
                    ('quarantined', 'Quarantined'),
                    ('missing', 'Missing'),
                ],
                db_index=True,
                default='unverified_legacy',
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='attachment',
            name='sha256',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='attachment',
            name='storage_version_id',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='attachment',
            name='supersedes_attachment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='replacement_attachments',
                to='wiki.attachment',
            ),
        ),
        migrations.CreateModel(
            name='AttachmentUploadIntent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('attachment_id', models.UUIDField(db_index=True, unique=True)),
                ('page_id', models.UUIDField(db_index=True)),
                ('object_name', models.CharField(max_length=1024, unique=True)),
                ('state', models.CharField(choices=[('created', 'Created'), ('writing', 'Writing'), ('verifying', 'Verifying'), ('committing', 'Committing'), ('committed', 'Committed'), ('failed', 'Failed')], db_index=True, default='created', max_length=16)),
                ('byte_size', models.PositiveBigIntegerField(blank=True, null=True)),
                ('sha256', models.CharField(blank=True, default='', max_length=64)),
                ('storage_version_id', models.CharField(blank=True, default='', max_length=255)),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('last_error', models.TextField(blank=True, default='')),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('cleanup_event_name', models.CharField(max_length=255, unique=True)),
                ('cleanup_completed_at', models.DateTimeField(blank=True, null=True)),
                ('cleanup_attempts', models.PositiveIntegerField(default=0)),
                ('cleanup_last_attempt_at', models.DateTimeField(blank=True, null=True)),
                ('cleanup_last_error', models.TextField(blank=True, default='')),
                ('cleanup_terminal_failure_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['state', 'expires_at'], name='wiki_attach_state_901ea0_idx')],
            },
        ),
        migrations.CreateModel(
            name='AttachmentIntegrityTrustRoot',
            fields=[
                ('attachment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='integrity_trust_root', serialize=False, to='wiki.attachment')),
                ('trust_root_type', models.CharField(choices=[('recovery_manifest', 'Recovery manifest'), ('signed_upstream', 'Signed upstream'), ('operator_attestation', 'Operator attestation')], max_length=32)),
                ('source_record', models.CharField(max_length=1024)),
                ('expected_size', models.PositiveBigIntegerField()),
                ('expected_sha256', models.CharField(max_length=64)),
                ('expected_storage_version_id', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(
                check=models.Q(('integrity_state__in', ['verified', 'unverified_legacy', 'quarantined', 'missing'])),
                name='wiki_attachment_integrity_state_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='attachment',
            constraint=models.CheckConstraint(
                check=models.Q(('integrity_state', 'verified'), _negated=True) | models.Q(('sha256__regex', '^[0-9a-f]{64}$')),
                name='wiki_verified_attachment_has_sha256',
            ),
        ),
        migrations.AddConstraint(
            model_name='attachmentintegritytrustroot',
            constraint=models.CheckConstraint(check=models.Q(('trust_root_type__in', ['recovery_manifest', 'signed_upstream', 'operator_attestation'])), name='wiki_attachment_trust_root_type_valid'),
        ),
        migrations.AddConstraint(
            model_name='attachmentintegritytrustroot',
            constraint=models.CheckConstraint(check=models.Q(('expected_sha256__regex', '^[0-9a-f]{64}$')), name='wiki_attachment_trust_root_sha256_valid'),
        ),
        migrations.AddConstraint(
            model_name='attachmentintegritytrustroot',
            constraint=models.CheckConstraint(check=models.Q(('source_record', ''), _negated=True), name='wiki_attachment_trust_root_source_present'),
        ),
        migrations.RunPython(create_immutability_trigger, drop_immutability_trigger),
    ]
