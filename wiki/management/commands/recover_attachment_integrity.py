"""Recover exact trusted bytes as new immutable attachment identities."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wiki.attachment_integrity import TRUST_ROOT_TYPES, commit_attachment_upload
from wiki.models import Attachment
from wiki.serializers import AttachmentSerializer


class Command(BaseCommand):
    help = (
        'Quarantine predecessor attachments and upload independently trusted '
        'recovery bytes as new immutable IDs.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--created-by-id', type=int)

    def handle(self, *args, **options):
        manifest_path = Path(options['manifest']).resolve()
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'cannot read recovery manifest: {exc}') from exc

        trust_root_type = manifest.get('trust_root_type')
        source_record = str(manifest.get('source_record') or '').strip()
        if trust_root_type not in TRUST_ROOT_TYPES or not source_record:
            raise CommandError(
                'manifest requires an independent trust_root_type and source_record',
            )
        recoveries = manifest.get('recoveries')
        if not isinstance(recoveries, list) or not recoveries:
            raise CommandError('manifest recoveries must be a non-empty list')

        results = []
        for entry in recoveries:
            predecessor_id = entry.get('predecessor_id')
            try:
                predecessor = Attachment.objects.select_related('page').get(pk=predecessor_id)
            except Attachment.DoesNotExist as exc:
                raise CommandError(f'predecessor not found: {predecessor_id}') from exc

            expected_size = int(entry.get('size'))
            expected_sha256 = str(entry.get('sha256') or '')
            if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
                raise CommandError(f'invalid trusted SHA-256 for {predecessor_id}')

            existing = Attachment.objects.filter(
                supersedes_attachment=predecessor,
                file_size=expected_size,
                sha256=expected_sha256,
                integrity_state=Attachment.INTEGRITY_VERIFIED,
            ).first()
            if existing:
                Attachment.objects.filter(pk=predecessor.pk).update(
                    integrity_state=Attachment.INTEGRITY_QUARANTINED,
                )
                results.append({'predecessor_id': str(predecessor.id), 'attachment_id': str(existing.id), 'state': 'existing'})
                continue

            source_path = (manifest_path.parent / str(entry.get('source') or '')).resolve()
            try:
                stat_size = source_path.stat().st_size
                hasher = hashlib.sha256()
                with source_path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
            except OSError as exc:
                raise CommandError(f'cannot read recovery source {source_path}: {exc}') from exc
            if stat_size != expected_size or digest != expected_sha256:
                raise CommandError(
                    f'trusted recovery mismatch for {predecessor_id}: '
                    f'expected {expected_size}/{expected_sha256}, got {stat_size}/{digest}',
                )

            with source_path.open('rb') as raw:
                uploaded = File(raw, name=entry.get('filename') or source_path.name)
                uploaded.content_type = entry.get('mime_type') or predecessor.mime_type
                serializer = AttachmentSerializer(data={
                    'page': str(predecessor.page_id),
                    'file': uploaded,
                })
                serializer.is_valid(raise_exception=True)
                replacement = commit_attachment_upload(
                    serializer=serializer,
                    request=SimpleNamespace(user=SimpleNamespace(
                        id=options['created_by_id'] or predecessor.created_by_id,
                    )),
                    uploaded_file=uploaded,
                    supersedes_attachment=predecessor,
                )

            with transaction.atomic():
                Attachment.objects.filter(pk=predecessor.pk).update(
                    integrity_state=Attachment.INTEGRITY_QUARANTINED,
                )
            results.append({'predecessor_id': str(predecessor.id), 'attachment_id': str(replacement.id), 'state': 'created'})

        self.stdout.write(json.dumps({
            'trust_root_type': trust_root_type,
            'source_record': source_record,
            'recoveries': results,
        }, sort_keys=True))
