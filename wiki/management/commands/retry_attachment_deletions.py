"""Retry durable attachment-object deletion obligations."""

from django.core.management.base import BaseCommand, CommandError

from wiki.attachment_deletion import (
    AttachmentStorageDeletionError,
    process_attachment_deletion_intents,
)


class Command(BaseCommand):
    help = 'Retry pending attachment object deletion intents.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        try:
            result = process_attachment_deletion_intents(limit=options['limit'])
        except AttachmentStorageDeletionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"attachment deletion retry selected={result['selected']} "
            f"completed={result['completed']} failed={result['failed']}"
        ))
