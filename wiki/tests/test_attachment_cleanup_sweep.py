"""WIKI-57: the overdue-cleanup sweep must rescue intents whose one-shot
delivery was lost, idempotently, and a completed cleanup must drain the
``overdue`` gauge that drives ``WikiAttachmentCleanupOverdue``.

An upload intent's ONLY cleanup delivery is its one-off clocked PeriodicTask.
When that row goes missing (lost between intent commit and beat run, beat
churn, DB-scheduler pruning), the intent stays incomplete past ``expires_at``
and the gauge feeds the alert forever. ``sweep_overdue_upload_intents``
(idempotent; in CELERY_BEAT_SCHEDULE every 5m) mirrors the alert's overdue
predicate and re-arms exactly those one-offs.
"""
import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from wiki import tasks as wiki_tasks
from wiki.attachment_integrity import render_attachment_cleanup_metrics
from wiki.models import Page, Space, AttachmentUploadIntent

User = get_user_model()


def _make_page():
    space = Space.objects.create(organization_id=1, key='TST', name='Test', owner_id=1)
    return Page.objects.create(space=space, title='Cleanup sweep page', created_by_id=1)


class AttachmentCleanupSweepTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The Postgres FTS search-vector post_save signal (to_tsvector) is
        # PG-only and orthogonal to this logic; disconnect it so the suite
        # runs on any backend.
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.page = _make_page()

    def _intent(self, *, expires_at, completed=None, terminal=None, state='verifying'):
        return AttachmentUploadIntent.objects.create(
            attachment_id=uuid.uuid4(),
            page_id=self.page.id,
            object_name=f"wiki_attachments/{uuid.uuid4()}/fixture.bin",
            expires_at=expires_at,
            cleanup_event_name=f"wiki-upload-intent-{uuid.uuid4()}",
            state=state,
            cleanup_completed_at=completed,
            cleanup_terminal_failure_at=terminal,
        )

    def test_sweep_rearms_lost_one_offs_for_overdue_intents(self):
        overdue = self._intent(expires_at=timezone.now() - timedelta(hours=2))
        rearmed = wiki_tasks.sweep_overdue_upload_intents()
        self.assertEqual(rearmed, 1)
        task = PeriodicTask.objects.get(name=overdue.cleanup_event_name)
        self.assertEqual(task.task, 'wiki.tasks.cleanup_attachment_upload_intent')
        self.assertTrue(task.one_off)
        self.assertEqual(json.loads(task.args), [str(overdue.id)])
        # Idempotent: a second sweep must not stack a duplicate one-off.
        self.assertEqual(wiki_tasks.sweep_overdue_upload_intents(), 0)
        self.assertEqual(
            PeriodicTask.objects.filter(name=overdue.cleanup_event_name).count(),
            1,
        )

    def test_sweep_ignores_healthy_terminal_and_completed_intents(self):
        future = self._intent(expires_at=timezone.now() + timedelta(hours=1))
        terminal = self._intent(
            expires_at=timezone.now() - timedelta(hours=2),
            terminal=timezone.now(),
        )
        completed = self._intent(
            expires_at=timezone.now() - timedelta(hours=2),
            completed=timezone.now(),
        )
        self.assertEqual(wiki_tasks.sweep_overdue_upload_intents(), 0)
        self.assertFalse(
            PeriodicTask.objects.filter(
                name__in=[future.cleanup_event_name,
                          terminal.cleanup_event_name,
                          completed.cleanup_event_name],
            ).exists(),
        )

    def test_sweep_does_not_duplicate_an_existing_one_off(self):
        overdue = self._intent(expires_at=timezone.now() - timedelta(hours=2))
        schedule, _ = ClockedSchedule.objects.get_or_create(clocked_time=overdue.expires_at)
        PeriodicTask.objects.create(
            name=overdue.cleanup_event_name,
            task='wiki.tasks.cleanup_attachment_upload_intent',
            clocked=schedule,
            one_off=True,
            args=json.dumps([str(overdue.id)]),
        )
        self.assertEqual(wiki_tasks.sweep_overdue_upload_intents(), 0)
        self.assertEqual(
            PeriodicTask.objects.filter(name=overdue.cleanup_event_name).count(),
            1,
        )

    def test_completed_cleanup_drains_the_overdue_gauge(self):
        overdue = self._intent(expires_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(
            PeriodicTask.objects.filter(name=overdue.cleanup_event_name).count(),
            0,
        )
        wiki_tasks.sweep_overdue_upload_intents()
        # Simulate the re-armed cleanup succeeding (the one-shot fires, the
        # staged bytes are reconciled, the intent completes).
        AttachmentUploadIntent.objects.filter(pk=overdue.pk).update(
            cleanup_completed_at=timezone.now(),
        )
        metrics = render_attachment_cleanup_metrics()
        self.assertIn(
            'wiki_attachment_cleanup_intents{state="overdue"} 0',
            metrics,
        )
        completed = next(
            line for line in metrics.splitlines()
            if line.startswith('wiki_attachment_cleanup_intents{state="completed"}')
        )
        self.assertEqual(int(completed.rsplit(' ', 1)[1]), 1)
