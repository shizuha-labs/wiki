"""Immutable attachment creation and verified byte serving (WIKI-45)."""

import hashlib
import json
import logging
import tempfile
import uuid
from datetime import timedelta
from pathlib import PurePosixPath

import redis
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django_celery_beat.models import ClockedSchedule, PeriodicTask
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import (
    Attachment,
    AttachmentIntegrityTrustRoot,
    AttachmentUploadIntent,
    attachment_upload_to,
)


logger = logging.getLogger(__name__)

MAX_HTTP_RANGE_BYTES = 16 * 1024 * 1024
_SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
TRUST_ROOT_TYPES = frozenset({
    'recovery_manifest',
    'signed_upstream',
    'operator_attestation',
})


class AttachmentUploadPhaseError(APIException):
    """Non-secret upload error whose stable code identifies the failed phase."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = 'attachment_upload_failed'

    def __init__(self, code, phase):
        super().__init__({
            'error': code,
            'phase': phase,
            'detail': f'Attachment {phase.replace("_", " ")} failed; upload was not committed.',
        })


class AttachmentIntegrityError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'attachment_integrity_failed'

    def __init__(self, code, detail):
        super().__init__({'error': code, 'detail': detail})


class AttachmentRangeError(APIException):
    status_code = status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
    default_code = 'invalid_attachment_range'

    def __init__(self, detail, size):
        super().__init__({'error': 'invalid_range', 'detail': detail, 'file_size': size})


def _record_metric(outcome):
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        client.incr(f'wiki:attachment_upload:{outcome}')
    except Exception:
        logger.debug('attachment_upload metric unavailable outcome=%s', outcome, exc_info=True)


def _record_cleanup_metric(outcome):
    """Persist a bounded cleanup outcome for Prometheus/alerting."""
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        client.incr(f'wiki:attachment_cleanup:{outcome}')
    except Exception:
        logger.exception('attachment_cleanup metric unavailable outcome=%s', outcome)


def render_attachment_cleanup_metrics():
    """Render durable cleanup liveness plus bounded attempt counters."""
    outcomes = ('success', 'retry', 'early_retry', 'terminal_failure')
    counts = {outcome: 0 for outcome in outcomes}
    probe_errors = 0
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        values = client.mget([
            f'wiki:attachment_cleanup:{outcome}' for outcome in outcomes
        ])
        counts.update({
            outcome: int(raw or 0)
            for outcome, raw in zip(outcomes, values)
        })
    except Exception:
        probe_errors = 1
        logger.exception('attachment_cleanup metrics backend unavailable')

    now = timezone.now()
    incomplete = AttachmentUploadIntent.objects.filter(cleanup_completed_at__isnull=True)
    overdue = incomplete.filter(
        expires_at__lte=now,
        cleanup_terminal_failure_at__isnull=True,
    ).count()
    terminal = incomplete.filter(cleanup_terminal_failure_at__isnull=False).count()
    completed = AttachmentUploadIntent.objects.filter(
        cleanup_completed_at__isnull=False,
    ).count()
    lines = [
        '# HELP wiki_attachment_cleanup_outcomes_total Upload-intent cleanup task outcomes.',
        '# TYPE wiki_attachment_cleanup_outcomes_total counter',
    ]
    lines.extend(
        f'wiki_attachment_cleanup_outcomes_total{{outcome="{outcome}"}} {counts[outcome]}'
        for outcome in outcomes
    )
    lines.extend([
        '# HELP wiki_attachment_cleanup_intents Durable upload-intent cleanup states.',
        '# TYPE wiki_attachment_cleanup_intents gauge',
        f'wiki_attachment_cleanup_intents{{state="completed"}} {completed}',
        f'wiki_attachment_cleanup_intents{{state="overdue"}} {overdue}',
        f'wiki_attachment_cleanup_intents{{state="terminal_failure"}} {terminal}',
        '# HELP wiki_attachment_cleanup_probe_errors Cleanup metric backend collection errors.',
        '# TYPE wiki_attachment_cleanup_probe_errors gauge',
        f'wiki_attachment_cleanup_probe_errors {probe_errors}',
    ])
    return '\n'.join(lines) + '\n'


def _stream_digest(file_object):
    digest = hashlib.sha256()
    size = 0
    chunks = file_object.chunks() if hasattr(file_object, 'chunks') else iter(lambda: file_object.read(1024 * 1024), b'')
    for chunk in chunks:
        digest.update(chunk)
        size += len(chunk)
    if hasattr(file_object, 'seek'):
        file_object.seek(0)
    return size, digest.hexdigest()


def _storage_version_id(storage, object_name):
    """Return an opaque S3 VersionId when the backend exposes one."""
    bucket_name = getattr(storage, 'bucket_name', '')
    connection = getattr(storage, 'connection', None)
    client = getattr(getattr(connection, 'meta', None), 'client', None)
    if not bucket_name or client is None:
        return ''
    key = object_name
    normalize = getattr(storage, '_normalize_name', None)
    clean = getattr(storage, '_clean_name', None)
    if clean:
        key = clean(key)
    if normalize:
        key = normalize(key)
    response = client.head_object(Bucket=bucket_name, Key=key)
    value = response.get('VersionId') or ''
    return '' if value == 'null' else str(value)


def _delete_storage_object(storage, object_name, version_id=''):
    """Delete the exact staged version when the backend exposes versioning."""
    bucket_name = getattr(storage, 'bucket_name', '')
    connection = getattr(storage, 'connection', None)
    client = getattr(getattr(connection, 'meta', None), 'client', None)
    if version_id and bucket_name and client is not None:
        key = object_name
        normalize = getattr(storage, '_normalize_name', None)
        clean = getattr(storage, '_clean_name', None)
        if clean:
            key = clean(key)
        if normalize:
            key = normalize(key)
        client.delete_object(Bucket=bucket_name, Key=key, VersionId=version_id)
        return
    storage.delete(object_name)


def _read_storage(storage, object_name):
    spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode='w+b')
    digest = hashlib.sha256()
    size = 0
    with storage.open(object_name, 'rb') as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            spool.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    spool.seek(0)
    return spool, size, digest.hexdigest(), _storage_version_id(storage, object_name)


def _ensure_upload_cleanup_scheduled(intent) -> bool:
    """Idempotently (re)arm the one-shot cleanup obligation for ``intent``.

    WIKI-57: an upload intent's ONLY cleanup delivery is its one-off clocked
    ``PeriodicTask``. If that row is missing (lost between intent commit and
    beat run, or pruned/never-created), nothing else re-arms it: the intent
    stays incomplete past ``expires_at`` and feeds ``WikiAttachmentCleanupOverdue``
    forever. Creation is keyed by the stable ``cleanup_event_name`` so a sweep
    (or a racing retry) never stacks duplicate one-offs.

    Returns True when a (re)arm was (re)created, False when one already exists.
    """
    from django_celery_beat.models import PeriodicTask
    if PeriodicTask.objects.filter(name=intent.cleanup_event_name).exists():
        return False
    schedule, _ = ClockedSchedule.objects.get_or_create(clocked_time=intent.expires_at)
    PeriodicTask.objects.create(
        name=intent.cleanup_event_name,
        task='wiki.tasks.cleanup_attachment_upload_intent',
        clocked=schedule,
        one_off=True,
        args=json.dumps([str(intent.id)]),
    )
    return True


def _schedule_upload_cleanup(intent):
    # New intents: guaranteed fresh name (intent UUID) — idempotent create is
    # still safe (first writer wins, one event either way).
    _ensure_upload_cleanup_scheduled(intent)


def create_upload_intent(*, page, filename):
    attachment_id = uuid.uuid4()
    safe_filename = PurePosixPath(str(filename).replace('\\', '/')).name
    object_name = attachment_upload_to(type('UploadTarget', (), {'id': attachment_id})(), safe_filename)
    expires_at = timezone.now() + timedelta(
        seconds=getattr(settings, 'WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS', 3600),
    )
    event_name = f'wiki-upload-intent-{attachment_id}'
    from django.db import transaction
    with transaction.atomic():
        intent = AttachmentUploadIntent.objects.create(
            attachment_id=attachment_id,
            page_id=page.id,
            object_name=object_name,
            expires_at=expires_at,
            cleanup_event_name=event_name,
        )
        _schedule_upload_cleanup(intent)
    return intent


def _best_effort_cleanup(storage, intent, stored_name, *, code, exc, version_id=''):
    cleaned = False
    if stored_name:
        try:
            if storage.exists(stored_name):
                _delete_storage_object(storage, stored_name, version_id)
            cleaned = not storage.exists(stored_name)
        except Exception:
            logger.exception(
                'attachment_upload cleanup_failed intent_id=%s object=%s',
                intent.id, stored_name,
            )
    try:
        update = {
            'error_code': code,
            'last_error': f'{type(exc).__name__}: {exc}'[:4000],
            'updated_at': timezone.now(),
        }
        if cleaned:
            update['cleanup_completed_at'] = timezone.now()
        claimed = AttachmentUploadIntent.objects.filter(
            pk=intent.pk,
            state=AttachmentUploadIntent.STATE_CLEANUP_CLAIMED,
        ).update(**update)
        if not claimed:
            AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                state=AttachmentUploadIntent.STATE_FAILED,
                **update,
            )
    except Exception:
        logger.exception('attachment_upload intent_failure_record_failed intent_id=%s', intent.id)


def _raise_phase_failure(
    storage, intent, stored_name, *, code, phase, exc, version_id='',
):
    _best_effort_cleanup(
        storage, intent, stored_name, code=code, exc=exc,
        version_id=version_id,
    )
    _record_metric(code)
    logger.exception(
        'attachment_upload failed phase=%s code=%s intent_id=%s attachment_id=%s object=%s',
        phase, code, intent.id, intent.attachment_id, intent.object_name,
        exc_info=exc,
    )
    raise AttachmentUploadPhaseError(code, phase) from exc


def commit_attachment_upload(
    *, serializer, request, uploaded_file, supersedes_attachment=None,
):
    """Create a verified attachment while preserving crash-safe intent state."""
    page = serializer.validated_data['page']
    display_filename = PurePosixPath(
        str(uploaded_file.name).replace('\\', '/'),
    ).name
    intent = create_upload_intent(page=page, filename=display_filename)
    storage = Attachment._meta.get_field('file').storage
    stored_name = None
    version_id = ''

    try:
        byte_size, sha256 = _stream_digest(uploaded_file)
        owned = AttachmentUploadIntent.objects.filter(
            pk=intent.pk,
            state=AttachmentUploadIntent.STATE_CREATED,
            cleanup_completed_at__isnull=True,
        ).update(
            state=AttachmentUploadIntent.STATE_WRITING,
            byte_size=byte_size,
            sha256=sha256,
            updated_at=timezone.now(),
        )
        if owned != 1:
            raise RuntimeError('upload intent lost ownership before storage write')
        if storage.exists(intent.object_name):
            raise FileExistsError('UUID-derived attachment object already exists')
        stored_name = storage.save(intent.object_name, uploaded_file)
        if stored_name != intent.object_name:
            raise RuntimeError('storage did not preserve the UUID-derived object key')
        if not storage.exists(stored_name):
            raise RuntimeError('attachment object is not durable on storage')
    except Exception as exc:
        _raise_phase_failure(
            storage, intent, stored_name,
            code='storage_write_failed', phase='storage_write', exc=exc,
        )

    try:
        owned = AttachmentUploadIntent.objects.filter(
            pk=intent.pk,
            state=AttachmentUploadIntent.STATE_WRITING,
            cleanup_completed_at__isnull=True,
        ).update(
            state=AttachmentUploadIntent.STATE_VERIFYING,
            updated_at=timezone.now(),
        )
        if owned != 1:
            raise RuntimeError('upload intent lost ownership before storage verification')
        spool, durable_size, durable_sha256, version_id = _read_storage(storage, stored_name)
        spool.close()
        if durable_size != byte_size or durable_sha256 != sha256:
            raise RuntimeError('durable storage readback did not match uploaded bytes')
        owned = AttachmentUploadIntent.objects.filter(
            pk=intent.pk,
            state=AttachmentUploadIntent.STATE_VERIFYING,
            cleanup_completed_at__isnull=True,
        ).update(
            storage_version_id=version_id,
            updated_at=timezone.now(),
        )
        if owned != 1:
            raise RuntimeError('upload intent lost ownership during storage verification')
    except Exception as exc:
        _raise_phase_failure(
            storage, intent, stored_name,
            code='storage_verify_failed', phase='storage_verify', exc=exc,
            version_id=version_id,
        )

    try:
        from django.db import transaction
        with transaction.atomic():
            locked_intent = AttachmentUploadIntent.objects.select_for_update().get(
                pk=intent.pk,
            )
            if (
                locked_intent.state != AttachmentUploadIntent.STATE_VERIFYING
                or locked_intent.cleanup_completed_at is not None
            ):
                raise RuntimeError('upload intent no longer owns the staged object')
            locked_intent.state = AttachmentUploadIntent.STATE_COMMITTING
            locked_intent.updated_at = timezone.now()
            locked_intent.save(update_fields=['state', 'updated_at'])
            attachment = serializer.save(
                id=intent.attachment_id,
                file=stored_name,
                filename=display_filename,
                file_size=byte_size,
                sha256=sha256,
                integrity_state=Attachment.INTEGRITY_VERIFIED,
                storage_version_id=version_id,
                supersedes_attachment=supersedes_attachment,
                mime_type=uploaded_file.content_type or 'application/octet-stream',
                created_by_id=request.user.id,
            )
            locked_intent.state = AttachmentUploadIntent.STATE_COMMITTED
            locked_intent.error_code = ''
            locked_intent.last_error = ''
            locked_intent.updated_at = timezone.now()
            locked_intent.save(
                update_fields=['state', 'error_code', 'last_error', 'updated_at'],
            )
    except Exception as exc:
        _raise_phase_failure(
            storage, intent, stored_name,
            code='metadata_commit_failed', phase='metadata_commit', exc=exc,
            version_id=version_id,
        )

    _record_metric('committed')
    logger.info(
        'attachment_upload committed intent_id=%s attachment_id=%s bytes=%s sha256=%s version=%s',
        intent.id, attachment.id, byte_size, sha256, version_id or '-',
    )
    return attachment


def promote_legacy_attachment(
    attachment,
    *,
    expected_size,
    expected_sha256,
    trust_root_type,
    source_record,
):
    """Promote legacy bytes only against an independently recorded trust root."""
    if trust_root_type not in TRUST_ROOT_TYPES:
        raise ValueError('trust_root_type is not an independently trusted class')
    if not source_record or not str(source_record).strip():
        raise ValueError('source_record is required for legacy promotion')
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('expected_sha256 must be lowercase hexadecimal SHA-256')
    if attachment.integrity_state != Attachment.INTEGRITY_UNVERIFIED_LEGACY:
        raise ValueError('only unverified_legacy attachments can be promoted')

    spool, actual_size, actual_sha256, version_id = _read_storage(
        attachment.file.storage, attachment.file.name,
    )
    spool.close()
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise AttachmentIntegrityError(
            'legacy_trust_root_mismatch',
            'Legacy attachment bytes do not match the independent trust root.',
        )

    from django.db import transaction
    with transaction.atomic():
        AttachmentIntegrityTrustRoot.objects.create(
            attachment=attachment,
            trust_root_type=trust_root_type,
            source_record=str(source_record).strip(),
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_storage_version_id=version_id,
        )
        updated = Attachment.objects.filter(
            pk=attachment.pk,
            integrity_state=Attachment.INTEGRITY_UNVERIFIED_LEGACY,
            sha256='',
        ).update(
            sha256=expected_sha256,
            storage_version_id=version_id,
            integrity_state=Attachment.INTEGRITY_VERIFIED,
        )
        if updated != 1:
            raise RuntimeError('legacy attachment changed concurrently during promotion')
    attachment.refresh_from_db()
    logger.info(
        'attachment_legacy promoted attachment_id=%s trust_root_type=%s source_record=%s',
        attachment.id, trust_root_type, source_record,
    )
    return attachment


def cleanup_expired_upload_intent(intent_id):
    """Idempotently delete only expired, uncommitted staging bytes."""
    from django.db import transaction

    with transaction.atomic():
        try:
            intent = AttachmentUploadIntent.objects.select_for_update().get(pk=intent_id)
        except AttachmentUploadIntent.DoesNotExist:
            return {'state': 'absent'}

        if intent.cleanup_completed_at:
            return {'state': 'already_complete'}
        if intent.expires_at > timezone.now():
            return {'state': 'not_expired', 'expires_at': intent.expires_at.isoformat()}
        if (
            intent.state == AttachmentUploadIntent.STATE_COMMITTED
            or Attachment.objects.filter(
                pk=intent.attachment_id,
                file=intent.object_name,
            ).exists()
        ):
            intent.cleanup_completed_at = timezone.now()
            intent.updated_at = timezone.now()
            intent.save(update_fields=['cleanup_completed_at', 'updated_at'])
            return {'state': 'committed'}

        if intent.state != AttachmentUploadIntent.STATE_CLEANUP_CLAIMED:
            intent.state = AttachmentUploadIntent.STATE_CLEANUP_CLAIMED
            intent.cleanup_claimed_at = timezone.now()
            intent.error_code = 'cleanup_claimed'
            intent.last_error = 'Expired upload intent claimed by durable cleanup.'
            intent.updated_at = timezone.now()
            intent.save(update_fields=[
                'state', 'cleanup_claimed_at', 'error_code', 'last_error', 'updated_at',
            ])

        object_name = intent.object_name
        version_id = intent.storage_version_id

    storage = Attachment._meta.get_field('file').storage
    if storage.exists(object_name):
        _delete_storage_object(storage, object_name, version_id)
    if storage.exists(object_name):
        raise RuntimeError('expired upload object still exists after cleanup')
    with transaction.atomic():
        intent = AttachmentUploadIntent.objects.select_for_update().get(pk=intent_id)
        if Attachment.objects.filter(
            pk=intent.attachment_id,
            file=intent.object_name,
        ).exists():
            raise RuntimeError('cleanup claim violated by a committed attachment')
        intent.cleanup_completed_at = timezone.now()
        intent.updated_at = timezone.now()
        intent.save(update_fields=['cleanup_completed_at', 'updated_at'])
    return {'state': 'cleaned'}


def _parse_range(header, size):
    if not header:
        return None
    if not header.startswith('bytes=') or ',' in header:
        raise AttachmentRangeError('Only one bytes range is supported.', size)
    spec = header[6:].strip()
    if '-' not in spec or size <= 0:
        raise AttachmentRangeError('Malformed or unsatisfiable bytes range.', size)
    start_text, end_text = spec.split('-', 1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = size - 1 if not end_text else int(end_text)
    except ValueError as exc:
        raise AttachmentRangeError('Malformed bytes range.', size) from exc
    if start < 0 or start >= size or end < start:
        raise AttachmentRangeError('Unsatisfiable bytes range.', size)
    end = min(end, size - 1)
    if end - start + 1 > MAX_HTTP_RANGE_BYTES:
        raise AttachmentRangeError(
            f'Range exceeds the {MAX_HTTP_RANGE_BYTES}-byte maximum.', size,
        )
    return start, end


def verified_attachment_response(attachment, *, range_header='', as_attachment=True):
    """Read, hash, and serve bytes only when the persisted identity still holds."""
    if attachment.integrity_state in (
        Attachment.INTEGRITY_QUARANTINED,
        Attachment.INTEGRITY_MISSING,
    ):
        raise AttachmentIntegrityError(
            f'attachment_{attachment.integrity_state}',
            f'Attachment bytes are {attachment.integrity_state} and cannot be served.',
        )
    if not attachment.file:
        raise AttachmentIntegrityError('attachment_missing', 'Attachment has no object key.')

    try:
        spool, actual_size, actual_sha256, actual_version = _read_storage(
            attachment.file.storage, attachment.file.name,
        )
    except Exception as exc:
        logger.exception('attachment_read failed attachment_id=%s', attachment.id)
        raise AttachmentIntegrityError(
            'attachment_storage_read_failed', 'Attachment bytes could not be read.',
        ) from exc

    mismatch = actual_size != attachment.file_size
    if attachment.integrity_state == Attachment.INTEGRITY_VERIFIED:
        mismatch = mismatch or actual_sha256 != attachment.sha256
        if attachment.storage_version_id:
            mismatch = mismatch or actual_version != attachment.storage_version_id
    if mismatch:
        spool.close()
        logger.error(
            'attachment_read integrity_mismatch attachment_id=%s expected_size=%s actual_size=%s '
            'expected_sha256=%s actual_sha256=%s expected_version=%s actual_version=%s',
            attachment.id, attachment.file_size, actual_size, attachment.sha256,
            actual_sha256, attachment.storage_version_id or '-', actual_version or '-',
        )
        raise AttachmentIntegrityError(
            'attachment_integrity_mismatch',
            'Attachment bytes do not match the committed identity.',
        )

    byte_range = _parse_range(range_header, actual_size)
    content_type = attachment.mime_type or 'application/octet-stream'
    if byte_range:
        start, end = byte_range
        spool.seek(start)
        response = HttpResponse(
            spool.read(end - start + 1),
            status=status.HTTP_206_PARTIAL_CONTENT,
            content_type=content_type,
        )
        spool.close()
        response['Content-Range'] = f'bytes {start}-{end}/{actual_size}'
        response['Content-Length'] = str(end - start + 1)
    else:
        response = FileResponse(
            spool,
            content_type=content_type,
            as_attachment=as_attachment,
            filename=attachment.filename,
        )
        response['Content-Length'] = str(actual_size)

    if byte_range:
        response['Content-Disposition'] = content_disposition_header(
            as_attachment, attachment.filename,
        )
    response['Accept-Ranges'] = 'bytes'
    response['X-Wiki-Integrity'] = (
        'partial-range' if byte_range else attachment.integrity_state
    )
    response['X-Wiki-Checksum-SHA256'] = (
        attachment.sha256 if attachment.integrity_state == Attachment.INTEGRITY_VERIFIED
        else actual_sha256
    )
    if attachment.storage_version_id:
        response['X-Wiki-Storage-Version'] = attachment.storage_version_id
    return response
