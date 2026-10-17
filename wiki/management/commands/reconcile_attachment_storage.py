"""Idempotently reconcile Wiki attachment rows with shared object storage."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from wiki.models import Attachment


def _sha256(handle) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


class Command(BaseCommand):
    help = (
        'Reconcile Attachment metadata with shared storage. Existing objects are '
        'hash-verified; missing objects are copied from --source-root only with --apply.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Copy verified local sources (default: audit only).')
        parser.add_argument('--source-root', default=str(settings.MEDIA_ROOT))
        parser.add_argument('--manifest', default='', help='Atomically write the JSON reconciliation manifest here.')
        parser.add_argument(
            '--trusted-manifest',
            default='',
            help=(
                'JSON manifest whose attachments map is keyed by Attachment UUID; '
                'each entry must contain source, size, and sha256.'
            ),
        )
        parser.add_argument('--only', default='', help='Comma-separated Attachment UUIDs to reconcile.')
        parser.add_argument('--require-complete', action='store_true', help='Exit non-zero when any row is unresolved.')

    def handle(self, *args, **options):
        source_root = Path(options['source_root']).resolve()
        requested = list(dict.fromkeys(
            value.strip() for value in options['only'].split(',') if value.strip()
        ))
        requested_valid = []
        for value in requested:
            try:
                requested_valid.append(str(uuid.UUID(value)))
            except ValueError:
                # Keep malformed requested IDs as explicit unresolved obligations.
                pass
        trusted = self._load_trusted_manifest(options['trusted_manifest'])
        queryset = Attachment.objects.order_by('created_at', 'id')
        if requested:
            queryset = queryset.filter(id__in=requested_valid)

        results = []
        found = set()
        for attachment in queryset.iterator():
            attachment_id = str(attachment.id)
            found.add(attachment_id)
            results.append(self._reconcile_one(
                attachment,
                source_root,
                options['apply'],
                trusted.get(attachment_id) if trusted is not None else None,
                trusted is not None,
            ))
        for attachment_id in requested:
            try:
                normalized = str(uuid.UUID(attachment_id))
            except ValueError:
                normalized = attachment_id
            if normalized not in found:
                results.append({'id': attachment_id, 'status': 'metadata_missing'})

        counts = {}
        for result in results:
            counts[result['status']] = counts.get(result['status'], 0) + 1
        unresolved = sum(
            count for status, count in counts.items()
            if status not in ('verified', 'copied')
        )
        manifest = {
            'version': 1,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'apply': bool(options['apply']),
            'source_root': str(source_root),
            'trusted_manifest': options['trusted_manifest'] or None,
            'storage_backend': default_storage.__class__.__name__,
            'counts': counts,
            'unresolved': unresolved,
            'attachments': results,
        }
        rendered = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
        if options['manifest']:
            self._write_manifest(Path(options['manifest']), rendered)
            self.stdout.write(f"manifest={options['manifest']}")
        self.stdout.write(rendered)
        if options['require_complete'] and unresolved:
            raise CommandError(f'{unresolved} attachment(s) remain unresolved')

    @staticmethod
    def _load_trusted_manifest(path: str) -> dict | None:
        if not path:
            return None
        manifest_path = Path(path)
        try:
            payload = json.loads(manifest_path.read_text())
            attachments = payload['attachments']
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CommandError(f'Invalid trusted manifest {manifest_path}: {exc}') from exc
        if not isinstance(attachments, dict):
            raise CommandError('Trusted manifest attachments must be an object keyed by UUID')
        normalized = {}
        for raw_id, entry in attachments.items():
            try:
                attachment_id = str(uuid.UUID(raw_id))
                source = entry['source']
                size = int(entry['size'])
                digest = entry['sha256'].lower()
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise CommandError(f'Invalid trusted manifest entry {raw_id!r}: {exc}') from exc
            if not isinstance(source, str) or not source:
                raise CommandError(f'Trusted manifest entry {raw_id!r} has no source')
            if size < 0 or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise CommandError(f'Trusted manifest entry {raw_id!r} has invalid size/sha256')
            normalized[attachment_id] = {
                'source': source,
                'size': size,
                'sha256': digest,
            }
        return normalized

    def _reconcile_one(
        self,
        attachment,
        source_root: Path,
        apply: bool,
        trusted: dict | None,
        trusted_manifest_supplied: bool,
    ) -> dict:
        name = (attachment.file.name or '').lstrip('/')
        result = {
            'id': str(attachment.id),
            'name': name,
            'expected_size': attachment.file_size,
        }
        if not name or '..' in PurePosixPath(name).parts:
            return {**result, 'status': 'invalid_name'}

        if trusted_manifest_supplied and trusted is None:
            return {**result, 'status': 'trusted_manifest_entry_missing'}

        expected_size = trusted['size'] if trusted else None
        expected_digest = trusted['sha256'] if trusted else None
        if expected_size is not None and expected_size != attachment.file_size:
            return {
                **result,
                'status': 'metadata_size_mismatch',
                'trusted_size': expected_size,
                'trusted_sha256': expected_digest,
            }

        source_name = trusted['source'] if trusted else name
        source_parts = PurePosixPath(source_name).parts
        if not source_name or '..' in source_parts:
            return {**result, 'status': 'invalid_source_name'}
        source = (source_root / Path(*source_parts)).resolve()
        try:
            source.relative_to(source_root)
        except ValueError:
            return {**result, 'status': 'invalid_source_name'}

        if default_storage.exists(name):
            with default_storage.open(name, 'rb') as handle:
                size, digest = _sha256(handle)
            if expected_size is None:
                if not source.is_file():
                    return {
                        **result,
                        'status': 'trusted_source_missing',
                        'actual_size': size,
                        'sha256': digest,
                    }
                with source.open('rb') as handle:
                    expected_size, expected_digest = _sha256(handle)
            if expected_size != attachment.file_size:
                return {
                    **result,
                    'status': 'metadata_size_mismatch',
                    'actual_size': size,
                    'sha256': digest,
                    'trusted_size': expected_size,
                    'trusted_sha256': expected_digest,
                }
            status = 'verified' if (size, digest) == (expected_size, expected_digest) else 'target_hash_mismatch'
            return {
                **result,
                'status': status,
                'actual_size': size,
                'sha256': digest,
                'trusted_size': expected_size,
                'trusted_sha256': expected_digest,
            }

        if not source.is_file():
            return {**result, 'status': 'source_missing'}

        with source.open('rb') as handle:
            source_size, source_digest = _sha256(handle)
        result.update(source_size=source_size, source_sha256=source_digest)
        if trusted and (source_size, source_digest) != (expected_size, expected_digest):
            return {
                **result,
                'status': 'source_manifest_mismatch',
                'trusted_size': expected_size,
                'trusted_sha256': expected_digest,
            }
        expected_size = source_size if expected_size is None else expected_size
        expected_digest = source_digest if expected_digest is None else expected_digest
        if expected_size != attachment.file_size:
            return {**result, 'status': 'source_size_mismatch'}
        if not apply:
            return {**result, 'status': 'copy_pending'}

        with source.open('rb') as handle:
            saved_name = default_storage.save(name, File(handle, name=source.name))
        if saved_name != name:
            default_storage.delete(saved_name)
            return {**result, 'status': 'target_name_conflict', 'saved_name': saved_name}
        with default_storage.open(name, 'rb') as handle:
            target_size, target_digest = _sha256(handle)
        if (target_size, target_digest) != (expected_size, expected_digest):
            default_storage.delete(name)
            return {
                **result,
                'status': 'target_hash_mismatch',
                'actual_size': target_size,
                'sha256': target_digest,
            }
        return {
            **result,
            'status': 'copied',
            'actual_size': target_size,
            'sha256': target_digest,
        }

    @staticmethod
    def _write_manifest(path: Path, rendered: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
