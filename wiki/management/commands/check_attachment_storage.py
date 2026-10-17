"""Kubelet-only deep readiness probe for the shared attachment backend."""
from __future__ import annotations

import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Write, read, and delete one private probe object on attachment storage.'

    def handle(self, *args, **options):
        probe = b'shizuha-wiki-storage-readiness-v1'
        name = f'_health/readiness/{uuid.uuid4().hex}'
        saved_name = None
        try:
            saved_name = default_storage.save(name, ContentFile(probe))
            if saved_name != name:
                raise RuntimeError(f'storage rewrote unique readiness key: {saved_name!r}')
            with default_storage.open(saved_name, 'rb') as handle:
                if handle.read() != probe:
                    raise RuntimeError('storage readiness read did not match written bytes')
            default_storage.delete(saved_name)
            if default_storage.exists(saved_name):
                raise RuntimeError('storage readiness could not delete its probe object')
            saved_name = None
        except Exception as exc:
            if saved_name:
                try:
                    default_storage.delete(saved_name)
                except Exception:
                    pass
            raise CommandError(f'attachment storage readiness failed: {exc}') from exc
        self.stdout.write('attachment storage healthy')
