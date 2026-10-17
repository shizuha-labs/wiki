"""Transactional attachment-object deletion outbox (WIKI-40)."""

import logging
import uuid
from functools import partial

from django.db import models, transaction
from django.utils import timezone

from .models import Attachment, AttachmentDeletionIntent


logger = logging.getLogger(__name__)


class AttachmentStorageDeletionError(RuntimeError):
    """Metadata committed, but one or more durable deletion intents remain."""


def enqueue_attachment_deletions(attachments):
    """Persist every object obligation together and run it only after commit.

    ``attachments`` may be a queryset or an iterable of Attachment instances.
    ``bulk_create`` makes a cascade's complete key set one database operation.
    The partial unique constraint deduplicates nested Page/Attachment signals.
    """
    rows = list(attachments)
    candidates = []
    batch_id = uuid.uuid4()
    for attachment in rows:
        object_name = (attachment.file.name or '').lstrip('/')
        if not object_name:
            logger.info(
                'attachment_delete no_object attachment_id=%s',
                attachment.id,
            )
            continue
        candidates.append(AttachmentDeletionIntent(
            batch_id=batch_id,
            attachment_id=attachment.id,
            page_id=attachment.page_id,
            object_name=object_name,
        ))

    if not candidates:
        return []

    AttachmentDeletionIntent.objects.bulk_create(candidates, ignore_conflicts=True)
    # Include an already-pending matching row as well as newly inserted rows.
    # A repeated delete must not report success while an earlier obligation for
    # the same durable object is still incomplete.
    pending_ids = list(
        AttachmentDeletionIntent.objects.filter(
            object_name__in=[candidate.object_name for candidate in candidates],
            completed_at__isnull=True,
        ).values_list('id', flat=True)
    )
    if pending_ids:
        transaction.on_commit(
            partial(process_attachment_deletion_intents, intent_ids=pending_ids),
            robust=False,
        )
    return pending_ids


def _mark_intent_complete(intent):
    """Record completion after object-store absence has been verified."""
    AttachmentDeletionIntent.objects.filter(
        pk=intent.pk,
        completed_at__isnull=True,
    ).update(
        attempts=models.F('attempts') + 1,
        last_error='',
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def process_attachment_deletion_intents(*, intent_ids=None, limit=100):
    """Try pending object deletions and retain durable retry/audit state.

    The object-store delete is idempotent: an already-absent object completes
    its obligation.  Every selected intent is attempted even if an earlier one
    fails, so a multi-object cascade records a precise partial outcome.
    """
    queryset = AttachmentDeletionIntent.objects.filter(completed_at__isnull=True)
    if intent_ids is not None:
        queryset = queryset.filter(id__in=intent_ids)
    ordered = queryset.order_by('created_at')
    # A synchronous on-commit batch must drain its complete cascade key set;
    # only the periodic global sweep is deliberately bounded.
    intents = list(ordered if intent_ids is not None else ordered[:limit])
    storage = Attachment._meta.get_field('file').storage
    failed = []

    for intent in intents:
        try:
            if storage.exists(intent.object_name):
                storage.delete(intent.object_name)
            if storage.exists(intent.object_name):
                raise RuntimeError('object still exists after storage.delete')
        except Exception as exc:
            message = f'{type(exc).__name__}: {exc}'[:4000]
            AttachmentDeletionIntent.objects.filter(
                pk=intent.pk,
                completed_at__isnull=True,
            ).update(
                attempts=models.F('attempts') + 1,
                last_error=message,
                updated_at=timezone.now(),
            )
            logger.exception(
                'attachment_delete failed intent_id=%s attachment_id=%s object=%s',
                intent.id,
                intent.attachment_id,
                intent.object_name,
            )
            failed.append((intent.id, intent.object_name))
            continue

        try:
            _mark_intent_complete(intent)
        except Exception:
            # The object is already absent but the durable obligation is still
            # pending.  Fail the request/task; a later retry will observe absence
            # idempotently and finish the outbox row.
            logger.exception(
                'attachment_delete completion record failed intent_id=%s '
                'attachment_id=%s object=%s',
                intent.id,
                intent.attachment_id,
                intent.object_name,
            )
            failed.append((intent.id, intent.object_name))
            continue
        logger.info(
            'attachment_delete complete intent_id=%s attachment_id=%s object=%s',
            intent.id,
            intent.attachment_id,
            intent.object_name,
        )

    if failed:
        raise AttachmentStorageDeletionError(
            f'{len(failed)} attachment object deletion obligation(s) remain pending'
        )
    return {'selected': len(intents), 'completed': len(intents), 'failed': 0}
