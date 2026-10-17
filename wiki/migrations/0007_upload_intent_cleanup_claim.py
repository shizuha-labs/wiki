from django.db import migrations, models


UPLOAD_INTENT_INSERT_GUARD_SQL = """
CREATE OR REPLACE FUNCTION wiki_guard_attachment_upload_intent_insert()
RETURNS trigger AS $$
DECLARE
    upload_cleanup_claimed_at timestamptz;
BEGIN
    SELECT cleanup_claimed_at INTO upload_cleanup_claimed_at
      FROM wiki_attachmentuploadintent
     WHERE attachment_id = NEW.id
     FOR UPDATE;

    IF upload_cleanup_claimed_at IS NOT NULL THEN
        RAISE EXCEPTION 'attachment upload intent cleanup owns staged object'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS wiki_guard_attachment_upload_intent_insert ON wiki_attachment;
CREATE TRIGGER wiki_guard_attachment_upload_intent_insert
BEFORE INSERT ON wiki_attachment
FOR EACH ROW EXECUTE FUNCTION wiki_guard_attachment_upload_intent_insert();

CREATE OR REPLACE FUNCTION wiki_guard_attachment_upload_intent_cleanup_latch()
RETURNS trigger AS $$
BEGIN
    IF OLD.cleanup_claimed_at IS NOT NULL THEN
        IF NEW.cleanup_claimed_at IS DISTINCT FROM OLD.cleanup_claimed_at THEN
            RAISE EXCEPTION 'attachment upload intent cleanup claim is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state IS DISTINCT FROM 'cleanup_claimed' THEN
            RAISE EXCEPTION 'attachment upload intent cleanup ownership is terminal'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.cleanup_claimed_at IS NOT NULL
          AND NEW.state IS DISTINCT FROM 'cleanup_claimed' THEN
        RAISE EXCEPTION 'attachment upload intent cleanup claim requires cleanup-owned state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS wiki_guard_attachment_upload_intent_cleanup_latch
    ON wiki_attachmentuploadintent;
CREATE TRIGGER wiki_guard_attachment_upload_intent_cleanup_latch
BEFORE UPDATE ON wiki_attachmentuploadintent
FOR EACH ROW EXECUTE FUNCTION wiki_guard_attachment_upload_intent_cleanup_latch();
"""

UPLOAD_INTENT_INSERT_GUARD_REVERSE_SQL = """
DROP TRIGGER IF EXISTS wiki_guard_attachment_upload_intent_insert ON wiki_attachment;
DROP FUNCTION IF EXISTS wiki_guard_attachment_upload_intent_insert();
DROP TRIGGER IF EXISTS wiki_guard_attachment_upload_intent_cleanup_latch
    ON wiki_attachmentuploadintent;
DROP FUNCTION IF EXISTS wiki_guard_attachment_upload_intent_cleanup_latch();
"""


class Migration(migrations.Migration):
    dependencies = [
        ('wiki', '0006_attachment_integrity'),
    ]

    operations = [
        migrations.AddField(
            model_name='attachmentuploadintent',
            name='cleanup_claimed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='attachmentuploadintent',
            name='state',
            field=models.CharField(
                choices=[
                    ('created', 'Created'),
                    ('writing', 'Writing'),
                    ('verifying', 'Verifying'),
                    ('committing', 'Committing'),
                    ('cleanup_claimed', 'Cleanup claimed'),
                    ('committed', 'Committed'),
                    ('failed', 'Failed'),
                ],
                db_index=True,
                default='created',
                max_length=16,
            ),
        ),
        migrations.RunSQL(
            UPLOAD_INTENT_INSERT_GUARD_SQL,
            reverse_sql=UPLOAD_INTENT_INSERT_GUARD_REVERSE_SQL,
        ),
    ]
