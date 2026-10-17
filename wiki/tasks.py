"""Background maintenance tasks for Wiki."""

import logging
import math

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db.models import F
from django.utils import timezone

from .attachment_deletion import process_attachment_deletion_intents
from .attachment_integrity import (
    _ensure_upload_cleanup_scheduled,
    _record_cleanup_metric,
    cleanup_expired_upload_intent,
)
from .models import AttachmentUploadIntent


logger = logging.getLogger(__name__)


@shared_task(name='wiki.tasks.retry_attachment_deletions')
def retry_attachment_deletions():
    """Retry the durable outbox; failures remain visible in Celery and the DB."""
    return process_attachment_deletion_intents(limit=100)


@shared_task(name='wiki.tasks.sweep_overdue_upload_intents')
def sweep_overdue_upload_intents():
    """Rescue upload intents whose one-shot cleanup delivery was lost.

    WIKI-57: each upload intent's only cleanup delivery is its one-off clocked
    ``PeriodicTask``. When that row is missing (beat churn, DB-scheduler
    pruning, delivery lost before its first tick), the intent has no second
    chance: it remains incomplete past ``expires_at`` and the ``overdue``
    cleanup gauge feeds ``WikiAttachmentCleanupOverdue`` indefinitely.

    This task mirrors the alert's own overdue predicate and idempotently
    (re)creates the missing one-off, so the next beat tick runs the cleanup,
    ``cleanup_completed_at`` advances and the gauge drains to zero. Running it
    again is a no-op for healthy intents and never duplicates an existing
    one-off.
    """
    now = timezone.now()
    overdue = AttachmentUploadIntent.objects.filter(
        cleanup_completed_at__isnull=True,
        expires_at__lte=now,
        cleanup_terminal_failure_at__isnull=True,
    )
    rearmed = 0
    for intent in overdue.iterator(chunk_size=200):
        if _ensure_upload_cleanup_scheduled(intent):
            rearmed += 1
    if rearmed:
        logger.warning('attachment_cleanup sweep re-armed %d overdue intent(s)', rearmed)
    return rearmed


@shared_task(
    name='wiki.tasks.cleanup_attachment_upload_intent',
    bind=True,
    max_retries=12,
)
def cleanup_attachment_upload_intent(self, intent_id):
    """Run, re-arm, and fail-loud the durable orphan-cleanup obligation."""
    now = timezone.now()
    AttachmentUploadIntent.objects.filter(pk=intent_id).update(
        cleanup_attempts=F('cleanup_attempts') + 1,
        cleanup_last_attempt_at=now,
        updated_at=now,
    )
    try:
        result = cleanup_expired_upload_intent(intent_id)
    except Exception as exc:
        terminal = int(self.request.retries or 0) >= int(self.max_retries or 0)
        failure_update = {
            'cleanup_last_error': f'{type(exc).__name__}: {exc}'[:4000],
            'updated_at': now,
        }
        if terminal:
            failure_update['cleanup_terminal_failure_at'] = now
        AttachmentUploadIntent.objects.filter(pk=intent_id).update(
            **failure_update,
        )
        if terminal:
            _record_cleanup_metric('terminal_failure')
            logger.critical(
                'attachment_cleanup terminal_failure intent_id=%s retries=%s',
                intent_id, self.request.retries, exc_info=exc,
            )
            raise
        _record_cleanup_metric('retry')
        raise self.retry(exc=exc, countdown=min(3600, 2 ** int(self.request.retries or 0)))

    if result.get('state') == 'not_expired':
        intent = AttachmentUploadIntent.objects.get(pk=intent_id)
        countdown = max(1, math.ceil((intent.expires_at - timezone.now()).total_seconds()))
        _record_cleanup_metric('early_retry')
        try:
            raise self.retry(countdown=countdown)
        except MaxRetriesExceededError as exc:
            AttachmentUploadIntent.objects.filter(pk=intent_id).update(
                cleanup_last_error='Cleanup event exhausted retries before expiry.',
                cleanup_terminal_failure_at=timezone.now(),
                updated_at=timezone.now(),
            )
            _record_cleanup_metric('terminal_failure')
            logger.critical(
                'attachment_cleanup terminal_failure_early intent_id=%s retries=%s',
                intent_id, self.request.retries, exc_info=exc,
            )
            raise

    _record_cleanup_metric('success')
    return result
