"""Crash-safe Wiki CAS snapshots for Pulse publication handoffs (PLS-482)."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from django.db import IntegrityError, transaction

from .models import Page, PublicationSnapshot
from .section_edit import list_markdown_sections


_DIGEST_RE = re.compile(r'^[0-9a-f]{64}$')
_RESULT_RE = re.compile(r'^[a-z][a-z0-9_.-]{0,99}$')


class PublicationSnapshotError(Exception):
    pass


class PublicationSnapshotInvalid(PublicationSnapshotError):
    pass


class PublicationSnapshotConflict(PublicationSnapshotError):
    pass


class PublicationSnapshotStale(PublicationSnapshotError):
    def __init__(self, message, *, current_pages):
        super().__init__(message)
        self.current_pages = current_pages


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')


def _digest(domain: str, value) -> str:
    return hashlib.sha256(domain.encode('utf-8') + b'\0' + _canonical(value)).hexdigest()


def _normalize_pages(pages) -> list[dict]:
    if not isinstance(pages, list) or not pages:
        raise PublicationSnapshotInvalid('pages must be a non-empty ordered list.')
    if len(pages) > 100:
        raise PublicationSnapshotInvalid('pages may contain at most 100 entries.')

    normalized = []
    seen_pages = set()
    for page_index, raw in enumerate(pages):
        if not isinstance(raw, dict) or set(raw) != {'page_id', 'version', 'anchors'}:
            raise PublicationSnapshotInvalid(
                f'pages[{page_index}] must contain exactly page_id, version, anchors.'
            )
        try:
            page_id = str(UUID(str(raw['page_id'])))
            version = int(raw['version'])
        except (TypeError, ValueError):
            raise PublicationSnapshotInvalid(
                f'pages[{page_index}] has an invalid page_id or version.'
            )
        if version < 1 or page_id in seen_pages:
            raise PublicationSnapshotInvalid(
                f'pages[{page_index}] has a duplicate page_id or version below 1.'
            )
        seen_pages.add(page_id)

        anchors = raw['anchors']
        if not isinstance(anchors, list) or not anchors:
            raise PublicationSnapshotInvalid(
                f'pages[{page_index}].anchors must be a non-empty ordered list.'
            )
        normalized_anchors = []
        seen_anchors = set()
        for anchor_index, anchor_raw in enumerate(anchors):
            if not isinstance(anchor_raw, dict) or set(anchor_raw) != {'anchor', 'section_hash'}:
                raise PublicationSnapshotInvalid(
                    f'pages[{page_index}].anchors[{anchor_index}] must contain exactly anchor and section_hash.'
                )
            anchor = str(anchor_raw['anchor']).strip()
            section_hash = str(anchor_raw['section_hash']).strip().lower()
            if not anchor or anchor in seen_anchors or not _DIGEST_RE.fullmatch(section_hash):
                raise PublicationSnapshotInvalid(
                    f'pages[{page_index}].anchors[{anchor_index}] has an invalid/duplicate anchor or hash.'
                )
            seen_anchors.add(anchor)
            normalized_anchors.append({'anchor': anchor, 'section_hash': section_hash})
        normalized.append({'page_id': page_id, 'version': version, 'anchors': normalized_anchors})
    return normalized


def create_publication_snapshot(*, operation_key, organization_id, publication_result,
                                pages, created_by_id):
    """CAS current page heads/sections and create or replay one snapshot.

    Page edits use the same ``select_for_update`` row lock, so the successful
    transaction is the linearization point relative to every full-page and
    section edit.  Locks are acquired in UUID order to avoid cross-request
    deadlocks while the published tuple retains the caller's semantic order.
    """
    operation_key = str(operation_key or '').strip()
    publication_result = str(publication_result or '').strip()
    if not operation_key or len(operation_key) > 128:
        raise PublicationSnapshotInvalid('operation_key is required and limited to 128 characters.')
    if not _RESULT_RE.fullmatch(publication_result):
        raise PublicationSnapshotInvalid('publication_result must be a lowercase typed result.')
    normalized_pages = _normalize_pages(pages)
    request_body = {
        'operation_key': operation_key,
        'organization_id': int(organization_id),
        'publication_result': publication_result,
        'pages': normalized_pages,
    }
    request_digest = _digest('io.shizuha.wiki-publication-request/v1', request_body)

    with transaction.atomic():
        existing = PublicationSnapshot.objects.select_for_update().filter(
            operation_key=operation_key,
        ).first()
        if existing:
            if existing.request_digest != request_digest:
                raise PublicationSnapshotConflict(
                    'operation_key was already used with a different publication tuple.'
                )
            return existing, True

        ids = sorted(page['page_id'] for page in normalized_pages)
        locked = {
            str(page.id): page
            for page in Page.objects.select_for_update().select_related('space').filter(id__in=ids).order_by('id')
        }
        current_pages = []
        stale = False
        for expected in normalized_pages:
            page = locked.get(expected['page_id'])
            if page is None or page.space.organization_id != int(organization_id):
                # Do not reveal whether a cross-org/missing UUID exists.
                raise PublicationSnapshotInvalid('One or more pages are unavailable in the requested organization.')
            current_anchors = [
                {'anchor': section.anchor, 'section_hash': section.section_hash}
                for section in list_markdown_sections(page.content_text or '')
            ]
            row = {'page_id': str(page.id), 'version': page.version}
            current_pages.append(row)
            if page.version != expected['version'] or current_anchors != expected['anchors']:
                stale = True
        if stale:
            raise PublicationSnapshotStale(
                'At least one page head/version/ordered section hash changed before snapshot CAS.',
                current_pages=current_pages,
            )

        snapshot_body = {
            'organization_id': int(organization_id),
            'publication_result': publication_result,
            'pages': normalized_pages,
        }
        snapshot_digest = _digest('io.shizuha.wiki-publication-snapshot/v1', snapshot_body)
        try:
            # Isolate a concurrent unique-key loser in a savepoint so the outer
            # transaction remains readable for the idempotent replay lookup.
            with transaction.atomic():
                snapshot = PublicationSnapshot.objects.create(
                    operation_key=operation_key,
                    request_digest=request_digest,
                    snapshot_digest=snapshot_digest,
                    organization_id=int(organization_id),
                    publication_result=publication_result,
                    page_tuples=normalized_pages,
                    created_by_id=int(created_by_id or 0),
                )
        except IntegrityError:
            # A concurrent identical operation may win after our initial read.
            snapshot = PublicationSnapshot.objects.get(operation_key=operation_key)
            if snapshot.request_digest != request_digest:
                raise PublicationSnapshotConflict(
                    'operation_key was concurrently used with a different publication tuple.'
                )
            return snapshot, True
        return snapshot, False
