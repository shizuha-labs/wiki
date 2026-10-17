"""WIKI-19: authorization / tenant-isolation invariants.

THE THREAT: an external customer reading, modifying, or deleting another user's
data (especially an admin/internal user's) WITHOUT an explicitly granted
permission. Every read/write/search/attachment/comment path must enforce
owner/tenant scope server-side — client-side or filter-only scoping is not enough.

These tests set up two real (non-staff, non-superuser) users in DIFFERENT orgs
and assert that the org-B user cannot reach org-A's private space, its pages,
attachments, comments, or search results — and that a same-org non-member cannot
reach a private space either. Positive controls prove the endpoints DO work for
the legitimate member, so a green suite means "isolated", not "broken".

Auth model note (see wiki/views.py): cross-tenant denial is enforced by queryset
scoping, surfacing as HTTP 404 (never reveal another tenant's object exists). An
explicit X-Organization-ID for an org you don't belong to is rejected 400 by
_ensure_membership_for_read. Both are valid "denied" outcomes and are asserted
as such.
"""
import requests
from celery.exceptions import Retry

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.signals import post_delete, post_save
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from wiki.authentication import FederatedUser
from wiki.models import (
    Attachment, AttachmentDeletionIntent, AttachmentIntegrityTrustRoot,
    AttachmentUploadIntent, Page, PageComment, Space, SpaceMembership,
    PublicationSnapshot,
)
from wiki.attachment_deletion import process_attachment_deletion_intents
from wiki.attachment_integrity import (
    cleanup_expired_upload_intent,
    create_upload_intent,
    promote_legacy_attachment,
)
from wiki.section_edit import list_markdown_sections
from wiki.signals import update_search_vector
from wiki.tasks import cleanup_attachment_upload_intent

ORG_A = 1
ORG_B = 2

DENIED_READ = {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST}
DENIED_WRITE = {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST}


def _fed(user_id, org, role='member'):
    """A federated (JWT-derived) user in exactly one org — the prod request.user
    shape, unlike the staff Django users the other test modules use (which bypass
    every membership check)."""
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@org{org}.example',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={org: role},
    )


def _client(user, org):
    c = APIClient(HTTP_X_ORGANIZATION_ID=str(org))
    c.force_authenticate(user=user)
    return c


class WikiTenantIsolationTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Detach the Postgres FTS trigger so page saves run on any DB backend.
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        # --- Org A principals ---
        self.owner_a = _fed(101, ORG_A, role='admin')          # owns the private space
        self.member_a = _fed(102, ORG_A, role='member')        # explicit member of the private space
        self.nonmember_a = _fed(103, ORG_A, role='member')     # in org A but NOT a member of the private space
        # --- Org B principal (the attacker / external tenant) ---
        self.outsider_b = _fed(201, ORG_B, role='admin')

        self.c_owner = _client(self.owner_a, ORG_A)
        self.c_member = _client(self.member_a, ORG_A)
        self.c_nonmember = _client(self.nonmember_a, ORG_A)
        self.c_outsider = _client(self.outsider_b, ORG_B)

        # Private space in org A — the sensitive data under test.
        self.space = Space.objects.create(
            organization_id=ORG_A, key='SEC', name='Security Docs',
            visibility='private', owner_id=self.owner_a.id,
        )
        SpaceMembership.objects.create(space=self.space, user_id=self.member_a.id, role='viewer')

        self.page = Page.objects.create(
            space=self.space, title='Zephyrquux Credentials Runbook',
            content_text='Zephyrquux secret runbook body', content_json={},
            status='published', created_by_id=self.owner_a.id,
        )
        self.attachment = Attachment.objects.create(
            page=self.page, file='wiki_attachments/2026/07/secret.txt',
            filename='secret.txt', file_size=12, mime_type='text/plain',
            created_by_id=self.owner_a.id,
        )
        self.comment = PageComment.objects.create(
            page=self.page, content='internal note', created_by_id=self.owner_a.id,
        )

    # ------------------------------------------------------------------ #
    # Cross-org READ isolation                                            #
    # ------------------------------------------------------------------ #
    def test_outsider_cannot_get_page(self):
        resp = self.c_outsider.get(f'/api/pages/{self.page.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_outsider_cannot_list_org_a_page(self):
        resp = self.c_outsider.get('/api/pages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {row['id'] for row in (resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data)}
        self.assertNotIn(str(self.page.id), ids)

    def test_outsider_cannot_get_space(self):
        resp = self.c_outsider.get('/api/spaces/SEC/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_outsider_cannot_list_org_a_space(self):
        resp = self.c_outsider.get('/api/spaces/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        keys = {row['key'] for row in (resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data)}
        self.assertNotIn('SEC', keys)

    def test_outsider_org_id_spoof_is_rejected(self):
        """Setting X-Organization-ID to the victim's org must be rejected, not honored."""
        spoof = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG_A))
        spoof.force_authenticate(user=self.outsider_b)
        resp = spoof.get(f'/api/pages/{self.page.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_outsider_org_id_spoof_list_is_forbidden(self):
        """Wrong-org explicit list requests are denials, not 400 validation errors."""
        spoof = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG_A))
        spoof.force_authenticate(user=self.outsider_b)
        resp = spoof.get('/api/pages/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(CONNECT_SECURITY_EVENT_ORIGIN_SECRET='boundary-secret')
    @patch('wiki.security_events.record_boundary_event_outcome')
    @patch('wiki.security_events.requests.post')
    def test_wrong_org_denial_emits_one_sanitized_event_without_changing_403(self, post, record):
        post.return_value.status_code = status.HTTP_202_ACCEPTED
        spoof = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG_A))
        spoof.force_authenticate(user=self.outsider_b)

        resp = spoof.get('/api/pages/?q=secret-must-not-be-copied')

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        post.assert_called_once()
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['type'], 'platform.boundary_denial')
        self.assertEqual(payload['data']['reason'], 'cross_tenant_org_scope')
        self.assertEqual(payload['data']['source_org_ids'], [ORG_B])
        self.assertEqual(payload['data']['target_org_id'], ORG_A)
        self.assertNotIn('query', payload['data'])
        self.assertNotIn('authorization', payload['data'])
        record.assert_called_once_with('success')

    def test_boundary_producer_failures_are_counted_without_changing_403(self):
        cases = (
            ('disabled', {'CONNECT_SECURITY_EVENT_EMIT_ENABLED': False}, None, None),
            ('missing_secret', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': ''}, None, None),
            ('non_202', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, 503, None),
            ('timeout', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, None, requests.Timeout()),
            ('exception', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, None, RuntimeError('boom')),
        )
        for expected, setting_overrides, status_code, side_effect in cases:
            with self.subTest(expected=expected), override_settings(**setting_overrides), patch(
                'wiki.security_events.record_boundary_event_outcome',
            ) as record, patch('wiki.security_events.requests.post') as post:
                if status_code is not None:
                    post.return_value.status_code = status_code
                if side_effect is not None:
                    post.side_effect = side_effect
                spoof = APIClient(HTTP_X_ORGANIZATION_ID=str(ORG_A))
                spoof.force_authenticate(user=self.outsider_b)

                resp = spoof.get('/api/pages/?q=still-must-not-be-copied')

                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
                record.assert_called_once_with(expected)

    @patch('wiki.attachment_integrity.redis.Redis.from_url')
    @patch('wiki.security_events._metrics_redis_client')
    def test_boundary_metrics_endpoint_exposes_bounded_service_outcomes(
        self, client_factory, cleanup_client_factory,
    ):
        client = MagicMock()
        client.mget.return_value = ['2'] + ['0'] * 7
        client_factory.return_value = client
        cleanup_client = MagicMock()
        cleanup_client.mget.return_value = ['1', '0', '0', '0']
        cleanup_client_factory.return_value = cleanup_client

        resp = APIClient().get('/api/metrics/security-events/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        text = resp.content.decode('utf-8')
        self.assertIn(
            'platform_boundary_event_producer_total{service="wiki",outcome="success"} 2',
            text,
        )
        self.assertIn(
            'platform_boundary_event_producer_probe_errors{service="wiki"} 0',
            text,
        )
        self.assertIn(
            'wiki_attachment_cleanup_outcomes_total{outcome="success"} 1',
            text,
        )
        self.assertIn(
            'wiki_attachment_cleanup_intents{state="terminal_failure"} 0',
            text,
        )

    @patch('wiki.attachment_integrity.render_attachment_cleanup_metrics', return_value='')
    @patch('wiki.security_events._metrics_redis_client')
    def test_boundary_metrics_omit_unavailable_counters_without_resetting_recovery(
        self, client_factory, _cleanup_metrics,
    ):
        """Mirror the production N -> Redis error -> same N scrape order."""
        from wiki.security_events import render_boundary_event_metrics

        client = MagicMock()
        historical = ['4', '0', '0', '0', '0', '1', '0', '0']
        client.mget.side_effect = [historical, ConnectionError('redis down'), historical]
        client_factory.return_value = client

        before = render_boundary_event_metrics()
        with self.assertLogs('wiki.security_events', level='ERROR'):
            unavailable = render_boundary_event_metrics()
        recovered = render_boundary_event_metrics()

        before_counters = [
            line for line in before.splitlines()
            if line.startswith('platform_boundary_event_producer_total')
        ]
        recovered_counters = [
            line for line in recovered.splitlines()
            if line.startswith('platform_boundary_event_producer_total')
        ]
        self.assertEqual(recovered_counters, before_counters)
        self.assertIn(
            'platform_boundary_event_producer_total'
            '{service="wiki",outcome="non_202"} 1',
            before,
        )
        self.assertNotIn('platform_boundary_event_producer_total', unavailable)
        self.assertIn(
            'platform_boundary_event_producer_probe_errors{service="wiki"} 1',
            unavailable,
        )

    def test_outsider_org_id_query_param_spoof_list_is_forbidden(self):
        """?organization_id= is an explicit wrong-org scope and must deny."""
        spoof = APIClient()
        spoof.force_authenticate(user=self.outsider_b)
        resp = spoof.get(f'/api/pages/?organization_id={ORG_A}')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_reads_are_bearer_gated_scs239(self):
        """SCS-239 (QA target F0.1 / PLAT-7636): every data endpoint requires a
        bearer token; anonymous callers get a typed 401 — never data. The old
        anonymous public-read path leaked cross-org content (org-61 pages to
        unauthenticated callers, observed 2026-09-24..27)."""
        public_a = Space.objects.create(
            organization_id=ORG_A, key='PUBA', name='Public A',
            visibility='public', owner_id=self.owner_a.id,
        )
        Page.objects.create(
            space=public_a, title='Anonymous Alpha', content_text='alpha',
            content_json={}, status='published', created_by_id=self.owner_a.id,
        )
        anonymous = APIClient()

        for url in (
            '/api/pages/',
            '/api/spaces/',
            '/api/search/?q=alpha',
            f'/api/pages/?organization_id={ORG_A}',
            f'/api/spaces/?organization={ORG_A}',
        ):
            with self.subTest(url=url):
                resp = anonymous.get(url)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED, url)

    def test_health_stays_anonymous_allowed(self):
        """Health is the only anonymous-allowed endpoint (QA target F0.1)."""
        resp = APIClient().get('/api/health/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @skipUnless(connection.vendor == 'postgresql', 'search uses Postgres full-text search')
    def test_search_respects_organization_id_filter(self):
        """SCS-239: the anonymous variant of this test is superseded by
        test_anonymous_reads_are_bearer_gated_scs239 (search GET now 401s
        without a bearer token). Authenticated equivalent: an org-A member
        searching with organization_id=ORG_A gets only org-A results — no
        cross-org leak."""
        public_a = Space.objects.create(
            organization_id=ORG_A, key='SRCHA', name='Search A',
            visibility='public', owner_id=self.owner_a.id,
        )
        public_b = Space.objects.create(
            organization_id=ORG_B, key='SRCHB', name='Search B',
            visibility='public', owner_id=self.outsider_b.id,
        )
        page_a = Page.objects.create(
            space=public_a, title='Needlewidget Alpha', content_text='needlewidget alpha',
            content_json={}, status='published', created_by_id=self.owner_a.id,
        )
        page_b = Page.objects.create(
            space=public_b, title='Needlewidget Beta', content_text='needlewidget beta',
            content_json={}, status='published', created_by_id=self.outsider_b.id,
        )

        response = self.c_owner.get(
            f'/api/search/?q=Needlewidget&organization_id={ORG_A}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        ids = {row['id'] for row in rows}
        self.assertIn(str(page_a.id), ids)
        self.assertNotIn(str(page_b.id), ids)

    def test_outsider_cannot_get_attachment(self):
        resp = self.c_outsider.get(f'/api/attachments/{self.attachment.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_outsider_cannot_list_attachments_by_page_id(self):
        resp = self.c_outsider.get(f'/api/attachments/?page_id={self.page.id}')
        self.assertIn(resp.status_code, {status.HTTP_200_OK} | DENIED_READ)
        if resp.status_code == status.HTTP_200_OK:
            rows = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
            self.assertEqual(len(rows), 0)

    def test_outsider_cannot_list_comments_by_page_id(self):
        resp = self.c_outsider.get(f'/api/comments/?page_id={self.page.id}')
        self.assertIn(resp.status_code, {status.HTTP_200_OK} | DENIED_READ)
        if resp.status_code == status.HTTP_200_OK:
            rows = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
            self.assertEqual(len(rows), 0, "cross-org comment listing must not leak comments")

    # ------------------------------------------------------------------ #
    # Cross-org WRITE isolation                                           #
    # ------------------------------------------------------------------ #
    def test_outsider_cannot_update_page(self):
        resp = self.c_outsider.patch(f'/api/pages/{self.page.id}/', {'title': 'pwned'}, format='json')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Zephyrquux Credentials Runbook')

    def test_outsider_cannot_delete_page(self):
        resp = self.c_outsider.delete(f'/api/pages/{self.page.id}/')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertTrue(Page.objects.filter(pk=self.page.id).exists())

    def test_outsider_cannot_comment_on_page(self):
        resp = self.c_outsider.post(
            '/api/comments/', {'page': str(self.page.id), 'content': 'injected'}, format='json')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertFalse(
            PageComment.objects.filter(page=self.page, content='injected').exists(),
            "cross-org comment write must be rejected (IDOR)")

    def test_outsider_cannot_upload_attachment(self):
        from io import BytesIO
        f = BytesIO(b'malware'); f.name = 'x.txt'
        resp = self.c_outsider.post(
            '/api/attachments/', {'page': str(self.page.id), 'file': f}, format='multipart')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertEqual(self.page.attachments.count(), 1)  # only the original

    def test_outsider_cannot_update_space(self):
        resp = self.c_outsider.patch('/api/spaces/SEC/', {'name': 'pwned'}, format='json')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.space.refresh_from_db()
        self.assertEqual(self.space.name, 'Security Docs')

    def test_outsider_cannot_add_space_member(self):
        resp = self.c_outsider.post(
            '/api/spaces/SEC/members/', {'user_id': self.outsider_b.id, 'role': 'admin'}, format='json')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertFalse(SpaceMembership.objects.filter(space=self.space, user_id=self.outsider_b.id).exists())

    # ------------------------------------------------------------------ #
    # Same-org, non-member isolation (private space)                      #
    # ------------------------------------------------------------------ #
    def test_same_org_nonmember_cannot_get_private_space(self):
        resp = self.c_nonmember.get('/api/spaces/SEC/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_same_org_nonmember_cannot_get_private_page(self):
        resp = self.c_nonmember.get(f'/api/pages/{self.page.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_same_org_nonmember_cannot_comment_on_private_page(self):
        resp = self.c_nonmember.post(
            '/api/comments/', {'page': str(self.page.id), 'content': 'nope'}, format='json')
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertFalse(PageComment.objects.filter(page=self.page, content='nope').exists())

    # ------------------------------------------------------------------ #
    # Positive controls — the legitimate member CAN reach the data        #
    # (so the negatives above prove isolation, not a broken endpoint)     #
    # ------------------------------------------------------------------ #
    def test_member_can_get_private_page(self):
        resp = self.c_member.get(f'/api/pages/{self.page.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_member_can_get_private_space(self):
        resp = self.c_member.get('/api/spaces/SEC/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_member_can_comment_on_private_page(self):
        resp = self.c_member.post(
            '/api/comments/', {'page': str(self.page.id), 'content': 'legit'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(PageComment.objects.filter(page=self.page, content='legit').exists())

    def test_member_can_list_page_comments(self):
        resp = self.c_member.get(f'/api/comments/?page_id={self.page.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data.get('results', resp.data) if isinstance(resp.data, dict) else resp.data
        self.assertGreaterEqual(len(rows), 1)

    # ------------------------------------------------------------------ #
    # Search isolation — a page must not surface in another tenant's      #
    # search index. Postgres-only (FTS uses SearchQuery/SearchRank).      #
    # ------------------------------------------------------------------ #
    @skipUnless(connection.vendor == 'postgresql', 'search uses Postgres full-text search')
    def test_search_does_not_leak_across_tenant(self):
        term = 'Zephyrquux'
        outsider = self.c_outsider.get(f'/api/search/?q={term}')
        self.assertEqual(outsider.status_code, status.HTTP_200_OK)
        out_rows = outsider.data.get('results', outsider.data) if isinstance(outsider.data, dict) else outsider.data
        out_ids = {r.get('id') for r in out_rows}
        self.assertNotIn(str(self.page.id), out_ids, "org-A page must not surface in org-B search")

    @skipUnless(connection.vendor == 'postgresql', 'search uses Postgres full-text search')
    def test_search_finds_page_for_member(self):
        term = 'Zephyrquux'
        member = self.c_member.get(f'/api/search/?q={term}')
        self.assertEqual(member.status_code, status.HTTP_200_OK)
        rows = member.data.get('results', member.data) if isinstance(member.data, dict) else member.data
        ids = {r.get('id') for r in rows}
        self.assertIn(str(self.page.id), ids, "the member must be able to find the page (positive control)")


import tempfile
import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from io import StringIO
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class WikiOrgVisibleAttachmentAndCreateIDORTests(APITestCase):
    """WIKI-19 P1 regressions (ren review of PR #23): the earlier fixes closed the
    PRIVATE-space paths, but two ORG-VISIBLE paths still trusted a bare
    `visibility in ('org','public')` grant and leaked across orgs:

      P1.1  GET /api/attachments/<id>/view/ (and /download/) authorized ANY
            authenticated user to an org-A org-visible attachment by UUID.
      P1.2  POST /api/pages/ with NO explicit org header could create a page in an
            org-A org-visible space from an org-B caller.

    An 'org'-visible space must be reachable only by MEMBERS of its org.
    """
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.member_a = _fed(301, ORG_A, role='member')
        self.outsider_b = _fed(302, ORG_B, role='admin')

        # ORG-VISIBLE space in org A (the case the bare visibility grant leaked).
        self.org_space = Space.objects.create(
            organization_id=ORG_A, key='ORGV', name='Org-visible Docs',
            visibility='org', owner_id=self.member_a.id,
        )
        self.org_page = Page.objects.create(
            space=self.org_space, title='Org visible page',
            content_text='org visible body', content_json={},
            status='published', created_by_id=self.member_a.id,
        )
        # Store a REAL file so the member positive control proves a 200 (a missing
        # file 404s even for an authorized member, which would mask the auth result).
        org_visible_bytes = b'org visible file'
        self.org_attachment = Attachment.objects.create(
            page=self.org_page,
            file=ContentFile(org_visible_bytes, name='orgv.txt'),
            filename='orgv.txt',
            file_size=len(org_visible_bytes),
            mime_type='text/plain',
            created_by_id=self.member_a.id,
        )
        self.public_space = Space.objects.create(
            organization_id=ORG_A, key='PUBA', name='Org A Public Docs',
            visibility='public', owner_id=self.member_a.id,
        )

        self.c_member = _client(self.member_a, ORG_A)
        # The attacker: authenticated org-B user. Two variants — with an org-B header,
        # and with NO org header at all (the exact P1.2 "no explicit org" scenario).
        self.c_outsider = _client(self.outsider_b, ORG_B)
        self.c_outsider_noorg = APIClient()
        self.c_outsider_noorg.force_authenticate(user=self.outsider_b)

    # ---- P1.1: attachment view/download cross-org IDOR ---- #
    def test_outsider_cannot_view_org_visible_attachment(self):
        for client in (self.c_outsider, self.c_outsider_noorg):
            resp = client.get(f'/api/attachments/{self.org_attachment.id}/view/')
            self.assertIn(resp.status_code, DENIED_READ,
                          f'org-B must not view org-A org-visible attachment (got {resp.status_code})')

    def test_outsider_cannot_download_org_visible_attachment(self):
        for client in (self.c_outsider, self.c_outsider_noorg):
            resp = client.get(f'/api/attachments/{self.org_attachment.id}/download/')
            self.assertIn(resp.status_code, DENIED_READ,
                          f'org-B must not download org-A org-visible attachment (got {resp.status_code})')

    def test_member_can_view_and_download_org_visible_attachment(self):
        """Positive control — a member of the space's org still gets the file."""
        v = self.c_member.get(f'/api/attachments/{self.org_attachment.id}/view/')
        self.assertEqual(v.status_code, status.HTTP_200_OK)
        d = self.c_member.get(f'/api/attachments/{self.org_attachment.id}/download/')
        self.assertEqual(d.status_code, status.HTTP_200_OK)

    # ---- P1.2: cross-org page creation into an org-visible space ---- #
    def test_outsider_cannot_create_page_in_org_visible_space_no_org_header(self):
        before = self.org_space.pages.count()
        resp = self.c_outsider_noorg.post(
            '/api/pages/',
            {'space': str(self.org_space.id), 'title': 'evil', 'content_json': {}},
            format='json',
        )
        self.assertIn(resp.status_code, DENIED_WRITE,
                      f'org-B must not create a page in org-A org-visible space (got {resp.status_code})')
        self.assertEqual(self.org_space.pages.count(), before, 'no page may be created')

    def test_outsider_cannot_create_page_in_org_visible_space_with_org_b_header(self):
        before = self.org_space.pages.count()
        resp = self.c_outsider.post(
            '/api/pages/',
            {'space': str(self.org_space.id), 'title': 'evil2', 'content_json': {}},
            format='json',
        )
        self.assertIn(resp.status_code, DENIED_WRITE)
        self.assertEqual(self.org_space.pages.count(), before)

    def test_outsider_cannot_create_page_in_org_visible_space_with_wrong_org_header_is_forbidden(self):
        before = self.org_space.pages.count()
        resp = self.c_outsider.post(
            '/api/pages/',
            {'space': str(self.org_space.id), 'title': 'evil-header', 'content_json': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.org_space.pages.count(), before)

    def test_outsider_cannot_create_page_with_wrong_organization_id_query_is_forbidden(self):
        before = self.org_space.pages.count()
        outsider = APIClient()
        outsider.force_authenticate(user=self.outsider_b)
        resp = outsider.post(
            f'/api/pages/?organization_id={ORG_B}',
            {'space': str(self.org_space.id), 'title': 'evil-query', 'content_json': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.org_space.pages.count(), before)

    def test_member_can_create_page_in_org_visible_space(self):
        """Positive control — a member of the org can create the page."""
        before = self.org_space.pages.count()
        resp = self.c_member.post(
            '/api/pages/',
            {'space': str(self.org_space.id), 'title': 'legit', 'content_json': {}},
            format='json',
        )
        self.assertIn(resp.status_code, {status.HTTP_200_OK, status.HTTP_201_CREATED})
        self.assertEqual(self.org_space.pages.count(), before + 1)

    def test_outsider_cannot_create_page_in_public_space(self):
        before = self.public_space.pages.count()
        for client in (self.c_outsider, self.c_outsider_noorg):
            resp = client.post(
                '/api/pages/',
                {'space': str(self.public_space.id), 'title': 'public evil', 'content_json': {}},
                format='json',
            )
            self.assertIn(resp.status_code, DENIED_WRITE,
                          f'org-B must not create in org-A public space (got {resp.status_code})')
        self.assertEqual(self.public_space.pages.count(), before)

    def test_owner_can_create_page_in_public_space(self):
        before = self.public_space.pages.count()
        resp = self.c_member.post(
            '/api/pages/',
            {'space': str(self.public_space.id), 'title': 'public legit', 'content_json': {}},
            format='json',
        )
        self.assertIn(resp.status_code, {status.HTTP_200_OK, status.HTTP_201_CREATED})
        self.assertEqual(self.public_space.pages.count(), before + 1)


class WikiSharedAttachmentStorageTests(APITransactionTestCase):
    """WIKI-40: uploads commit only after durable shared storage succeeds."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.member = _fed(401, ORG_A, role='admin')
        self.client_a = _client(self.member, ORG_A)
        self.client_b = _client(self.member, ORG_A)
        self.space = Space.objects.create(
            organization_id=ORG_A,
            key='STORE',
            name='Storage Tests',
            visibility='org',
            owner_id=self.member.id,
        )
        self.page = Page.objects.create(
            space=self.space,
            title='Shared attachment target',
            content_text='',
            content_json={},
            status='published',
            created_by_id=self.member.id,
        )

    def test_storage_write_failure_leaves_no_attachment_metadata(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None), patch.object(
            Attachment._meta.get_field('file').storage,
            'save',
            side_effect=OSError('storage unavailable'),
        ):
            response = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('failure.txt', b'must-not-commit', content_type='text/plain'),
                },
                format='multipart',
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error'], 'storage_write_failed')
        self.assertEqual(Attachment.objects.count(), 0)

    def test_twenty_independent_clients_read_identical_uploaded_bytes(self):
        payload = b'WIKI-40 shared attachment bytes\x00\x01\xff' * 64
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('shared.bin', payload, content_type='application/octet-stream'),
                },
                format='multipart',
            )
            self.assertEqual(upload.status_code, status.HTTP_201_CREATED)
            attachment_id = upload.data['id']
            expected = hashlib.sha256(payload).hexdigest()

            observed = []
            for attempt in range(20):
                client = self.client_a if attempt % 2 == 0 else self.client_b
                response = client.get(f'/api/attachments/{attachment_id}/download/')
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                observed.append(hashlib.sha256(b''.join(response.streaming_content)).hexdigest())

        self.assertEqual(observed, [expected] * 20)

    def test_post_storage_metadata_failure_removes_staged_object(self):
        def fail_after_insert(sender, instance, created, **kwargs):
            if created and instance.filename == 'orphan.txt':
                raise RuntimeError('forced post-storage metadata failure')

        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            post_save.connect(
                fail_after_insert,
                sender=Attachment,
                dispatch_uid='wiki40-post-storage-failure',
            )
            try:
                response = self.client_a.post(
                    '/api/attachments/',
                    {
                        'page': str(self.page.id),
                        'file': SimpleUploadedFile('orphan.txt', b'orphan-bytes', content_type='text/plain'),
                    },
                    format='multipart',
                )
            finally:
                post_save.disconnect(
                    sender=Attachment,
                    dispatch_uid='wiki40-post-storage-failure',
                )

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data['error'], 'metadata_commit_failed')
            self.assertEqual(Attachment.objects.count(), 0)
            self.assertEqual([path for path in Path(target).rglob('*') if path.is_file()], [])

    def test_verified_upload_persists_digest_and_supports_bounded_ranges(self):
        payload = (b'0123456789abcdef' * 128) + b'\x00\xff'
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('verified.bin', payload, content_type='application/octet-stream'),
                },
                format='multipart',
            )

            self.assertEqual(upload.status_code, status.HTTP_201_CREATED)
            self.assertEqual(upload.data['file_size'], len(payload))
            self.assertEqual(upload.data['sha256'], expected)
            self.assertEqual(upload.data['integrity_state'], Attachment.INTEGRITY_VERIFIED)
            attachment = Attachment.objects.get(pk=upload.data['id'])
            self.assertEqual(attachment.file.name, f'wiki_attachments/{attachment.id}/verified.bin')
            intent = AttachmentUploadIntent.objects.get(attachment_id=attachment.id)
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_COMMITTED)
            self.assertEqual(intent.sha256, expected)

            full = self.client_a.get(f'/api/attachments/{attachment.id}/download/')
            self.assertEqual(full.status_code, status.HTTP_200_OK)
            self.assertEqual(b''.join(full.streaming_content), payload)
            self.assertEqual(full['X-Wiki-Integrity'], Attachment.INTEGRITY_VERIFIED)
            self.assertEqual(full['X-Wiki-Checksum-SHA256'], expected)
            self.assertEqual(full['Accept-Ranges'], 'bytes')

            partial = self.client_a.get(
                f'/api/attachments/{attachment.id}/download/',
                HTTP_RANGE='bytes=17-88',
            )
            self.assertEqual(partial.status_code, status.HTTP_206_PARTIAL_CONTENT)
            self.assertEqual(partial.content, payload[17:89])
            self.assertEqual(partial['Content-Range'], f'bytes 17-88/{len(payload)}')
            self.assertEqual(partial['X-Wiki-Integrity'], 'partial-range')
            self.assertEqual(partial['X-Wiki-Checksum-SHA256'], expected)

            reassembled = bytearray()
            for start in range(0, len(payload), 257):
                end = min(start + 256, len(payload) - 1)
                chunk = self.client_a.get(
                    f'/api/attachments/{attachment.id}/download/',
                    HTTP_RANGE=f'bytes={start}-{end}',
                )
                self.assertEqual(chunk.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEqual(chunk['X-Wiki-Integrity'], 'partial-range')
                self.assertEqual(chunk['X-Wiki-Checksum-SHA256'], expected)
                reassembled.extend(chunk.content)
            self.assertEqual(len(reassembled), len(payload))
            self.assertEqual(hashlib.sha256(reassembled).hexdigest(), expected)

    def test_storage_verify_failure_is_typed_and_cleans_staged_object(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None), patch(
            'wiki.attachment_integrity._read_storage',
            side_effect=OSError('readback unavailable'),
        ):
            response = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('verify.txt', b'verify-me', content_type='text/plain'),
                },
                format='multipart',
            )

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data['error'], 'storage_verify_failed')
            self.assertEqual(response.data['phase'], 'storage_verify')
            self.assertFalse(Attachment.objects.exists())
            intent = AttachmentUploadIntent.objects.get()
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_FAILED)
            self.assertEqual(intent.error_code, 'storage_verify_failed')
            self.assertEqual([path for path in Path(target).rglob('*') if path.is_file()], [])

    def test_verified_read_denies_same_size_checksum_mismatch(self):
        payload = b'expected-verified-bytes'
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('tamper.bin', payload, content_type='application/octet-stream'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            Path(target, attachment.file.name).write_bytes(b'X' * len(payload))

            response = self.client_a.get(f'/api/attachments/{attachment.id}/download/')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['error'], 'attachment_integrity_mismatch')

    def test_model_guard_rejects_committed_identity_mutation(self):
        attachment = Attachment.objects.create(
            page=self.page,
            file='wiki_attachments/legacy/model-guard.bin',
            filename='model-guard.bin',
            file_size=7,
            mime_type='application/octet-stream',
            created_by_id=self.member.id,
        )
        attachment.file_size = 8
        with self.assertRaises(DjangoValidationError):
            attachment.save(update_fields=['file_size'])
        attachment.refresh_from_db()
        self.assertEqual(attachment.file_size, 7)

    @skipUnless(connection.vendor == 'postgresql', 'DB-boundary immutability is PostgreSQL-specific')
    def test_database_trigger_rejects_queryset_and_raw_sql_mutation(self):
        digest = hashlib.sha256(b'identity').hexdigest()
        attachment = Attachment.objects.create(
            page=self.page,
            file='wiki_attachments/identity/immutable.bin',
            filename='immutable.bin',
            file_size=8,
            sha256=digest,
            integrity_state=Attachment.INTEGRITY_VERIFIED,
            mime_type='application/octet-stream',
            created_by_id=self.member.id,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Attachment.objects.filter(pk=attachment.pk).update(file_size=9)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'UPDATE wiki_attachment SET sha256 = %s WHERE id = %s',
                ['0' * 64, str(attachment.id)],
            )

        attachment.refresh_from_db()
        self.assertEqual(attachment.file_size, 8)
        self.assertEqual(attachment.sha256, digest)

    @skipUnless(connection.vendor == 'postgresql', 'DB-boundary promotion is PostgreSQL-specific')
    def test_database_trigger_rejects_self_derived_and_quarantine_promotion(self):
        digest = hashlib.sha256(b'untrusted-current-object').hexdigest()
        attachment = Attachment.objects.create(
            page=self.page,
            file='wiki_attachments/legacy/self-derived.bin',
            filename='self-derived.bin',
            file_size=24,
            mime_type='application/octet-stream',
            created_by_id=self.member.id,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Attachment.objects.filter(pk=attachment.pk).update(
                sha256=digest,
                storage_version_id='attacker-selected-version',
                integrity_state=Attachment.INTEGRITY_VERIFIED,
            )
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'UPDATE wiki_attachment SET sha256 = %s, storage_version_id = %s, '
                'integrity_state = %s WHERE id = %s',
                [digest, 'attacker-selected-version', Attachment.INTEGRITY_VERIFIED, str(attachment.id)],
            )

        Attachment.objects.filter(pk=attachment.pk).update(
            integrity_state=Attachment.INTEGRITY_QUARANTINED,
        )
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'UPDATE wiki_attachment SET sha256 = %s, storage_version_id = %s, '
                'integrity_state = %s WHERE id = %s',
                [digest, 'attacker-selected-version', Attachment.INTEGRITY_VERIFIED, str(attachment.id)],
            )

        attachment.refresh_from_db()
        self.assertEqual(attachment.integrity_state, Attachment.INTEGRITY_QUARANTINED)
        self.assertEqual(attachment.sha256, '')

    def test_expired_upload_cleanup_never_deletes_committed_object(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
            WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS=-1,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('committed.txt', b'committed', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            intent = AttachmentUploadIntent.objects.get(attachment_id=attachment.id)
            object_path = Path(target, attachment.file.name)

            result = cleanup_expired_upload_intent(intent.id)

            self.assertEqual(result, {'state': 'committed'})
            self.assertTrue(object_path.exists())
            self.assertTrue(Attachment.objects.filter(pk=attachment.id).exists())

    @skipUnless(connection.vendor == 'postgresql', 'row-lock ownership is PostgreSQL-specific')
    def test_cleanup_waits_for_inflight_metadata_commit_then_preserves_object(self):
        """Cleanup arriving after verification cannot outrun commit visibility."""
        from wiki.serializers import AttachmentSerializer

        attachment_inserted = threading.Event()
        allow_commit = threading.Event()
        cleanup_started = threading.Event()
        upload_result = {}
        cleanup_result = {}
        original_create = AttachmentSerializer.create

        def blocking_create(serializer, validated_data):
            attachment = original_create(serializer, validated_data)
            attachment_inserted.set()
            if not allow_commit.wait(timeout=10):
                raise TimeoutError('test did not release metadata commit')
            return attachment

        def upload():
            close_old_connections()
            try:
                client = _client(_fed(402, ORG_A, role='admin'), ORG_A)
                upload_result['response'] = client.post(
                    '/api/attachments/',
                    {
                        'page': str(self.page.id),
                        'file': SimpleUploadedFile(
                            'commit-race.bin',
                            b'verified-before-commit',
                            content_type='application/octet-stream',
                        ),
                    },
                    format='multipart',
                )
            finally:
                close_old_connections()

        def cleanup(intent_id):
            close_old_connections()
            cleanup_started.set()
            try:
                cleanup_result['value'] = cleanup_expired_upload_intent(intent_id)
            finally:
                close_old_connections()

        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
            WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS=-1,
        ), patch('wiki.views._get_storage_quota_client', return_value=None), patch.object(
            AttachmentSerializer,
            'create',
            blocking_create,
        ), patch('wiki.attachment_integrity._delete_storage_object') as delete_object:
            upload_thread = threading.Thread(target=upload)
            upload_thread.start()
            self.assertTrue(attachment_inserted.wait(timeout=10))
            intent = AttachmentUploadIntent.objects.get()

            cleanup_thread = threading.Thread(target=cleanup, args=(intent.id,))
            cleanup_thread.start()
            self.assertTrue(cleanup_started.wait(timeout=10))
            self.assertTrue(cleanup_thread.is_alive())

            allow_commit.set()
            upload_thread.join(timeout=10)
            cleanup_thread.join(timeout=10)
            self.assertFalse(upload_thread.is_alive())
            self.assertFalse(cleanup_thread.is_alive())

            response = upload_result['response']
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(cleanup_result['value'], {'state': 'committed'})
            delete_object.assert_not_called()
            attachment = Attachment.objects.get(pk=response.data['id'])
            self.assertTrue(Path(target, attachment.file.name).exists())
            intent.refresh_from_db()
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_COMMITTED)
            self.assertIsNotNone(intent.cleanup_completed_at)

    @skipUnless(connection.vendor == 'postgresql', 'cleanup ownership is PostgreSQL-specific')
    def test_cleanup_claim_between_verification_and_commit_prevents_metadata_row(self):
        """A cleanup claim won during readback cannot be overwritten by commit."""
        from wiki import attachment_integrity

        verification_read = threading.Event()
        allow_verification_return = threading.Event()
        upload_result = {}
        cleanup_result = {}
        original_read_storage = attachment_integrity._read_storage

        def blocking_read_storage(storage, object_name):
            result = original_read_storage(storage, object_name)
            verification_read.set()
            if not allow_verification_return.wait(timeout=10):
                result[0].close()
                raise TimeoutError('test did not release storage verification')
            return result

        def upload():
            close_old_connections()
            try:
                client = _client(_fed(403, ORG_A, role='admin'), ORG_A)
                upload_result['response'] = client.post(
                    '/api/attachments/',
                    {
                        'page': str(self.page.id),
                        'file': SimpleUploadedFile(
                            'cleanup-wins.bin',
                            b'cleanup-claims-after-verification',
                            content_type='application/octet-stream',
                        ),
                    },
                    format='multipart',
                )
            finally:
                close_old_connections()

        def cleanup(intent_id):
            close_old_connections()
            try:
                cleanup_result['value'] = cleanup_expired_upload_intent(intent_id)
            finally:
                close_old_connections()

        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
            WIKI_ATTACHMENT_UPLOAD_INTENT_TTL_SECONDS=-1,
        ), patch('wiki.views._get_storage_quota_client', return_value=None), patch(
            'wiki.attachment_integrity._read_storage',
            blocking_read_storage,
        ):
            upload_thread = threading.Thread(target=upload)
            upload_thread.start()
            self.assertTrue(verification_read.wait(timeout=10))
            intent = AttachmentUploadIntent.objects.get()
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_VERIFYING)

            cleanup_thread = threading.Thread(target=cleanup, args=(intent.id,))
            cleanup_thread.start()
            cleanup_thread.join(timeout=10)
            self.assertFalse(cleanup_thread.is_alive())
            self.assertEqual(cleanup_result['value'], {'state': 'cleaned'})

            allow_verification_return.set()
            upload_thread.join(timeout=10)
            self.assertFalse(upload_thread.is_alive())

            response = upload_result['response']
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data['error'], 'storage_verify_failed')
            self.assertFalse(Attachment.objects.exists())
            intent.refresh_from_db()
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_CLEANUP_CLAIMED)
            self.assertIsNotNone(intent.cleanup_completed_at)
            self.assertFalse(Path(target, intent.object_name).exists())

    @skipUnless(connection.vendor == 'postgresql', 'insert ownership guard is PostgreSQL-specific')
    def test_cleanup_claim_latch_blocks_legacy_state_overwrite_and_metadata_insert(self):
        """Pre-patch state writes and inserts both fail after cleanup wins."""
        with tempfile.TemporaryDirectory() as target, override_settings(MEDIA_ROOT=target):
            intent = create_upload_intent(page=self.page, filename='stale-uploader.bin')
            storage = Attachment._meta.get_field('file').storage
            storage.save(intent.object_name, ContentFile(b'stale-uploader-bytes'))
            AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                state=AttachmentUploadIntent.STATE_VERIFYING,
                expires_at=timezone.now() - timedelta(seconds=1),
            )

            self.assertEqual(cleanup_expired_upload_intent(intent.id), {'state': 'cleaned'})
            with self.assertRaises(IntegrityError), transaction.atomic():
                AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                    state=AttachmentUploadIntent.STATE_COMMITTING,
                )

            intent.refresh_from_db()
            self.assertEqual(intent.state, AttachmentUploadIntent.STATE_CLEANUP_CLAIMED)
            self.assertIsNotNone(intent.cleanup_claimed_at)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Attachment.objects.create(
                    id=intent.attachment_id,
                    page=self.page,
                    file=intent.object_name,
                    filename='stale-uploader.bin',
                    file_size=20,
                    sha256=hashlib.sha256(b'stale-uploader-bytes').hexdigest(),
                    integrity_state=Attachment.INTEGRITY_VERIFIED,
                    mime_type='application/octet-stream',
                    created_by_id=self.member.id,
                )

            self.assertFalse(Attachment.objects.filter(pk=intent.attachment_id).exists())

    @skipUnless(connection.vendor == 'postgresql', 'cleanup ownership is PostgreSQL-specific')
    def test_cleanup_completion_before_first_upload_cas_is_not_reopened(self):
        """A losing uploader cannot clear a cleanup already completed by its task."""
        from wiki import attachment_integrity

        original_stream_digest = attachment_integrity._stream_digest
        completed_at = {}

        def cleanup_before_first_cas(uploaded_file):
            intent = AttachmentUploadIntent.objects.get()
            AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1),
            )
            self.assertEqual(cleanup_expired_upload_intent(intent.id), {'state': 'cleaned'})
            intent.refresh_from_db()
            completed_at['value'] = intent.cleanup_completed_at
            return original_stream_digest(uploaded_file)

        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None), patch(
            'wiki.attachment_integrity._stream_digest',
            cleanup_before_first_cas,
        ):
            response = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile(
                        'cleanup-before-cas.bin',
                        b'cleanup-completes-before-first-cas',
                        content_type='application/octet-stream',
                    ),
                },
                format='multipart',
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error'], 'storage_write_failed')
        intent = AttachmentUploadIntent.objects.get()
        self.assertEqual(intent.state, AttachmentUploadIntent.STATE_CLEANUP_CLAIMED)
        self.assertEqual(intent.cleanup_completed_at, completed_at['value'])
        self.assertIsNotNone(intent.cleanup_completed_at)
        self.assertFalse(Attachment.objects.filter(pk=intent.attachment_id).exists())

    def test_crash_after_storage_write_leaves_intent_and_expiry_removes_only_orphan(self):
        with tempfile.TemporaryDirectory() as target, override_settings(MEDIA_ROOT=target):
            intent = create_upload_intent(page=self.page, filename='crash.bin')
            storage = Attachment._meta.get_field('file').storage
            stored_name = storage.save(intent.object_name, ContentFile(b'crash-window'))
            AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                state=AttachmentUploadIntent.STATE_COMMITTING,
                expires_at=timezone.now() - timedelta(seconds=1),
            )

            self.assertTrue(storage.exists(stored_name))
            self.assertFalse(Attachment.objects.filter(pk=intent.attachment_id).exists())
            result = cleanup_expired_upload_intent(intent.id)

            self.assertEqual(result, {'state': 'cleaned'})
            self.assertFalse(storage.exists(stored_name))
            intent.refresh_from_db()
            self.assertIsNotNone(intent.cleanup_completed_at)

    def test_cleanup_task_rearms_early_delivery_then_cleans_at_expiry(self):
        with tempfile.TemporaryDirectory() as target, override_settings(MEDIA_ROOT=target):
            intent = create_upload_intent(page=self.page, filename='early-task.bin')
            storage = Attachment._meta.get_field('file').storage
            storage.save(intent.object_name, ContentFile(b'early-task-bytes'))

            with patch('wiki.tasks._record_cleanup_metric'), patch.object(
                cleanup_attachment_upload_intent,
                'retry',
                side_effect=Retry(),
            ) as retry:
                with self.assertRaises(Retry):
                    cleanup_attachment_upload_intent.run(str(intent.id))
            self.assertGreaterEqual(retry.call_args.kwargs['countdown'], 1)

            AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1),
            )
            with patch('wiki.tasks._record_cleanup_metric') as metric:
                result = cleanup_attachment_upload_intent.run(str(intent.id))

            self.assertEqual(result, {'state': 'cleaned'})
            self.assertFalse(storage.exists(intent.object_name))
            intent.refresh_from_db()
            self.assertEqual(intent.cleanup_attempts, 2)
            self.assertIsNotNone(intent.cleanup_completed_at)
            metric.assert_called_once_with('success')

    def test_cleanup_task_terminal_attempt_persists_fail_loud_state(self):
        intent = create_upload_intent(page=self.page, filename='terminal-task.bin')
        AttachmentUploadIntent.objects.filter(pk=intent.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        cleanup_attachment_upload_intent.push_request(
            retries=cleanup_attachment_upload_intent.max_retries,
        )
        try:
            with patch(
                'wiki.tasks.cleanup_expired_upload_intent',
                side_effect=OSError('object store delete unavailable'),
            ), patch('wiki.tasks._record_cleanup_metric') as metric:
                with self.assertRaisesRegex(OSError, 'object store delete unavailable'):
                    cleanup_attachment_upload_intent.run(str(intent.id))
        finally:
            cleanup_attachment_upload_intent.pop_request()

        intent.refresh_from_db()
        self.assertEqual(intent.cleanup_attempts, 1)
        self.assertIsNotNone(intent.cleanup_last_attempt_at)
        self.assertIsNotNone(intent.cleanup_terminal_failure_at)
        self.assertIn('object store delete unavailable', intent.cleanup_last_error)
        metric.assert_called_once_with('terminal_failure')

    def test_legacy_promotion_accepts_only_enumerated_independent_trust_roots(self):
        payload = b'independently-attested-legacy-bytes'
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as target, override_settings(MEDIA_ROOT=target):
            storage = Attachment._meta.get_field('file').storage
            for index, trust_root_type in enumerate((
                'recovery_manifest', 'signed_upstream', 'operator_attestation',
            )):
                name = f'wiki_attachments/legacy/{index}.bin'
                storage.save(name, ContentFile(payload))
                attachment = Attachment.objects.create(
                    page=self.page,
                    file=name,
                    filename=f'{index}.bin',
                    file_size=len(payload),
                    mime_type='application/octet-stream',
                    created_by_id=self.member.id,
                )

                promoted = promote_legacy_attachment(
                    attachment,
                    expected_size=len(payload),
                    expected_sha256=digest,
                    trust_root_type=trust_root_type,
                    source_record=f'trusted-record-{index}',
                )

                self.assertEqual(promoted.integrity_state, Attachment.INTEGRITY_VERIFIED)
                self.assertEqual(promoted.sha256, digest)
                trust_root = AttachmentIntegrityTrustRoot.objects.get(attachment=promoted)
                self.assertEqual(trust_root.trust_root_type, trust_root_type)
                self.assertEqual(trust_root.source_record, f'trusted-record-{index}')
                self.assertEqual(trust_root.expected_size, len(payload))
                self.assertEqual(trust_root.expected_sha256, digest)
                self.assertEqual(trust_root.expected_storage_version_id, '')

            rejected = Attachment.objects.create(
                page=self.page,
                file='wiki_attachments/legacy/rejected.bin',
                filename='rejected.bin',
                file_size=len(payload),
                mime_type='application/octet-stream',
                created_by_id=self.member.id,
            )
            storage.save(rejected.file.name, ContentFile(payload))
            with self.assertRaisesRegex(ValueError, 'independently trusted'):
                promote_legacy_attachment(
                    rejected,
                    expected_size=len(payload),
                    expected_sha256=digest,
                    trust_root_type='current_storage',
                    source_record='self-derived hash',
                )

    def test_recovery_quarantines_predecessor_and_idempotently_creates_new_identity(self):
        substitute = b'substitute-v4-bytes'
        recovered = b'exact-v4.1-recovery-bytes' * 20
        recovered_sha256 = hashlib.sha256(recovered).hexdigest()
        with tempfile.TemporaryDirectory() as target, tempfile.TemporaryDirectory() as bundle, override_settings(
            MEDIA_ROOT=target,
        ):
            predecessor_name = 'wiki_attachments/legacy/substitute.bin'
            storage = Attachment._meta.get_field('file').storage
            storage.save(predecessor_name, ContentFile(substitute))
            predecessor = Attachment.objects.create(
                page=self.page,
                file=predecessor_name,
                filename='operation-proof-v4.1.json.gz',
                file_size=len(substitute),
                mime_type='application/gzip',
                created_by_id=self.member.id,
            )
            source = Path(bundle, 'operation-proof-v4.1.json.gz')
            source.write_bytes(recovered)
            manifest = Path(bundle, 'manifest.json')
            manifest.write_text(json.dumps({
                'trust_root_type': 'recovery_manifest',
                'source_record': 'WIKI-40 independently hashed recovery bundle',
                'recoveries': [{
                    'predecessor_id': str(predecessor.id),
                    'source': source.name,
                    'filename': source.name,
                    'mime_type': 'application/gzip',
                    'size': len(recovered),
                    'sha256': recovered_sha256,
                }],
            }))

            first_stdout = StringIO()
            call_command(
                'recover_attachment_integrity',
                '--manifest', str(manifest),
                stdout=first_stdout,
            )
            first = json.loads(first_stdout.getvalue())
            replacement_id = first['recoveries'][0]['attachment_id']
            replacement = Attachment.objects.get(pk=replacement_id)
            predecessor.refresh_from_db()

            self.assertNotEqual(replacement.id, predecessor.id)
            self.assertEqual(replacement.supersedes_attachment_id, predecessor.id)
            self.assertEqual(replacement.file_size, len(recovered))
            self.assertEqual(replacement.sha256, recovered_sha256)
            self.assertEqual(replacement.integrity_state, Attachment.INTEGRITY_VERIFIED)
            self.assertEqual(predecessor.integrity_state, Attachment.INTEGRITY_QUARANTINED)
            self.assertTrue(storage.exists(predecessor.file.name))

            second_stdout = StringIO()
            call_command(
                'recover_attachment_integrity',
                '--manifest', str(manifest),
                stdout=second_stdout,
            )
            second = json.loads(second_stdout.getvalue())
            self.assertEqual(second['recoveries'][0]['state'], 'existing')
            self.assertEqual(second['recoveries'][0]['attachment_id'], replacement_id)
            self.assertEqual(
                Attachment.objects.filter(supersedes_attachment=predecessor).count(),
                1,
            )

    def test_public_health_is_non_mutating_and_deep_route_is_absent(self):
        storage = Attachment._meta.get_field('file').storage
        with patch.object(storage, 'save', wraps=storage.save) as save:
            response = APIClient().get('/api/health/')
            deep = APIClient().get('/api/health/storage/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {'status': 'healthy'})
        self.assertEqual(deep.status_code, status.HTTP_404_NOT_FOUND)
        save.assert_not_called()

    def test_internal_storage_readiness_command_proves_write_read_delete(self):
        with tempfile.TemporaryDirectory() as target, override_settings(MEDIA_ROOT=target):
            call_command('check_attachment_storage', stdout=StringIO())
            self.assertEqual([path for path in Path(target).rglob('*') if path.is_file()], [])

    def test_internal_storage_readiness_command_fails_closed(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch.object(
            Attachment._meta.get_field('file').storage,
            'save',
            side_effect=OSError('storage unavailable'),
        ):
            with self.assertRaises(CommandError):
                call_command('check_attachment_storage', stdout=StringIO())

    def test_direct_delete_removes_durable_object(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('delete-me.txt', b'delete-me', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            object_path = Path(target, attachment.file.name)
            self.assertTrue(object_path.is_file())

            response = self.client_a.delete(f'/api/attachments/{attachment.id}/')

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertFalse(object_path.exists())
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())
            intent = AttachmentDeletionIntent.objects.get(attachment_id=attachment.id)
            self.assertIsNotNone(intent.completed_at)
            self.assertEqual(intent.attempts, 1)

    def test_page_cascade_delete_removes_durable_object(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('cascade.txt', b'cascade', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            object_path = Path(target, attachment.file.name)
            self.assertTrue(object_path.is_file())

            response = self.client_a.delete(f'/api/pages/{self.page.id}/')

            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertFalse(object_path.exists())
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())

    def test_storage_delete_failure_commits_outbox_and_never_returns_clean(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('retry.txt', b'retry', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            storage = attachment.file.storage
            with patch.object(storage, 'delete', side_effect=OSError('delete unavailable')):
                response = self.client_a.delete(f'/api/attachments/{attachment.id}/')

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())
            self.assertTrue(Path(target, attachment.file.name).is_file())
            intent = AttachmentDeletionIntent.objects.get(attachment_id=attachment.id)
            self.assertIsNone(intent.completed_at)
            self.assertEqual(intent.attempts, 1)
            self.assertIn('delete unavailable', intent.last_error)

            # The durable retry finishes idempotently after the backend recovers.
            result = process_attachment_deletion_intents()
            self.assertEqual(result, {'selected': 1, 'completed': 1, 'failed': 0})
            intent.refresh_from_db()
            self.assertIsNotNone(intent.completed_at)
            self.assertEqual(intent.attempts, 2)
            self.assertEqual(intent.last_error, '')
            self.assertFalse(Path(target, attachment.file.name).exists())
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())
            self.assertFalse(
                AttachmentDeletionIntent.objects.filter(completed_at__isnull=True).exists()
            )

    def test_two_attachment_cascade_records_partial_failure_and_retry_completes(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            uploads = []
            for filename, payload in (
                ('cascade-a.txt', b'cascade-a'),
                ('cascade-b.txt', b'cascade-b'),
            ):
                response = self.client_a.post(
                    '/api/attachments/',
                    {
                        'page': str(self.page.id),
                        'file': SimpleUploadedFile(filename, payload, content_type='text/plain'),
                    },
                    format='multipart',
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                uploads.append(Attachment.objects.get(pk=response.data['id']))

            first, second = uploads
            first_path = Path(target, first.file.name)
            second_path = Path(target, second.file.name)
            storage = first.file.storage
            real_delete = storage.delete

            def fail_second(name):
                if name == second.file.name:
                    raise OSError('second cascade deletion unavailable')
                return real_delete(name)

            with patch.object(storage, 'delete', side_effect=fail_second):
                response = self.client_a.delete(f'/api/pages/{self.page.id}/')

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertFalse(Page.objects.filter(pk=self.page.id).exists())
            self.assertFalse(Attachment.objects.filter(page_id=self.page.id).exists())
            self.assertFalse(first_path.exists())
            self.assertTrue(second_path.exists())

            intents = AttachmentDeletionIntent.objects.filter(
                attachment_id__in=[first.id, second.id],
            )
            self.assertEqual(intents.count(), 2)
            self.assertEqual(intents.values('batch_id').distinct().count(), 1)
            self.assertEqual(intents.filter(completed_at__isnull=True).count(), 1)
            self.assertEqual(intents.filter(completed_at__isnull=False).count(), 1)

            call_command('retry_attachment_deletions', stdout=StringIO())
            self.assertFalse(second_path.exists())
            self.assertFalse(intents.filter(completed_at__isnull=True).exists())
            self.assertFalse(Attachment.objects.filter(page_id=self.page.id).exists())

    def test_post_commit_completion_record_failure_stays_pending_and_retries(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('post-commit.txt', b'post-commit', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            object_path = Path(target, attachment.file.name)

            with patch(
                'wiki.attachment_deletion._mark_intent_complete',
                side_effect=RuntimeError('database unavailable after object delete'),
            ):
                response = self.client_a.delete(f'/api/attachments/{attachment.id}/')

            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())
            self.assertFalse(object_path.exists())
            intent = AttachmentDeletionIntent.objects.get(attachment_id=attachment.id)
            self.assertIsNone(intent.completed_at)
            self.assertEqual(intent.attempts, 0)

            result = process_attachment_deletion_intents()
            self.assertEqual(result, {'selected': 1, 'completed': 1, 'failed': 0})
            intent.refresh_from_db()
            self.assertIsNotNone(intent.completed_at)
            self.assertEqual(intent.attempts, 1)
            self.assertFalse(Attachment.objects.filter(pk=attachment.id).exists())

    def test_pending_delete_cannot_remove_later_same_filename_upload(self):
        old_payload = b'old attachment bytes'
        new_payload = b'new attachment bytes'
        filename = 'reused-name.txt'

        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            old_upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile(filename, old_payload, content_type='text/plain'),
                },
                format='multipart',
            )
            self.assertEqual(old_upload.status_code, status.HTTP_201_CREATED)
            old_attachment = Attachment.objects.get(pk=old_upload.data['id'])
            old_name = old_attachment.file.name

            with patch(
                'wiki.attachment_deletion._mark_intent_complete',
                side_effect=RuntimeError('database unavailable after object delete'),
            ):
                delete_response = self.client_a.delete(
                    f'/api/attachments/{old_attachment.id}/'
                )

            self.assertEqual(
                delete_response.status_code,
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            intent = AttachmentDeletionIntent.objects.get(
                attachment_id=old_attachment.id,
            )
            self.assertIsNone(intent.completed_at)
            self.assertFalse(Path(target, old_name).exists())

            new_upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile(filename, new_payload, content_type='text/plain'),
                },
                format='multipart',
            )
            self.assertEqual(new_upload.status_code, status.HTTP_201_CREATED)
            new_attachment = Attachment.objects.get(pk=new_upload.data['id'])
            new_name = new_attachment.file.name
            self.assertNotEqual(new_name, old_name)
            self.assertIn(str(new_attachment.id), new_name)
            self.assertEqual(Path(target, new_name).read_bytes(), new_payload)

            result = process_attachment_deletion_intents()

            self.assertEqual(result, {'selected': 1, 'completed': 1, 'failed': 0})
            intent.refresh_from_db()
            self.assertIsNotNone(intent.completed_at)
            self.assertTrue(Attachment.objects.filter(pk=new_attachment.id).exists())
            self.assertEqual(Path(target, new_name).read_bytes(), new_payload)

    def test_database_failure_after_metadata_delete_never_mutates_storage(self):
        with tempfile.TemporaryDirectory() as target, override_settings(
            MEDIA_ROOT=target,
        ), patch('wiki.views._get_storage_quota_client', return_value=None):
            upload = self.client_a.post(
                '/api/attachments/',
                {
                    'page': str(self.page.id),
                    'file': SimpleUploadedFile('rollback.txt', b'rollback', content_type='text/plain'),
                },
                format='multipart',
            )
            attachment = Attachment.objects.get(pk=upload.data['id'])
            attachment_id = attachment.id
            object_path = Path(target, attachment.file.name)

            def fail_after_metadata_delete(sender, instance, **kwargs):
                if instance.id == attachment_id:
                    raise RuntimeError('forced database commit-boundary failure')

            post_delete.connect(
                fail_after_metadata_delete,
                sender=Attachment,
                dispatch_uid='wiki40-delete-commit-boundary-failure',
            )
            try:
                with self.assertRaisesRegex(RuntimeError, 'commit-boundary failure'):
                    with transaction.atomic():
                        attachment.delete()
            finally:
                post_delete.disconnect(
                    sender=Attachment,
                    dispatch_uid='wiki40-delete-commit-boundary-failure',
                )

            self.assertTrue(Attachment.objects.filter(pk=attachment_id).exists())
            self.assertTrue(object_path.exists())
            self.assertFalse(
                AttachmentDeletionIntent.objects.filter(attachment_id=attachment_id).exists()
            )

    def test_reconcile_is_idempotent_and_preserves_attachment_id(self):
        payload = b'restored-proof-bytes' * 100
        name = 'wiki_attachments/2026/07/restored-proof.bin'
        attachment = Attachment.objects.create(
            page=self.page,
            file=name,
            filename='restored-proof.bin',
            file_size=len(payload),
            mime_type='application/octet-stream',
            created_by_id=self.member.id,
        )
        original_id = attachment.id

        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            source_path = Path(source, name)
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(payload)
            manifest_path = Path(target, 'manifest.json')
            storage_root = Path(target, 'objects')

            with override_settings(MEDIA_ROOT=str(storage_root)):
                call_command(
                    'reconcile_attachment_storage',
                    '--apply',
                    '--require-complete',
                    '--source-root', source,
                    '--manifest', str(manifest_path),
                    stdout=StringIO(),
                )
                first = json.loads(manifest_path.read_text())
                call_command(
                    'reconcile_attachment_storage',
                    '--apply',
                    '--require-complete',
                    '--source-root', source,
                    '--manifest', str(manifest_path),
                    stdout=StringIO(),
                )
                second = json.loads(manifest_path.read_text())

            self.assertEqual(first['counts'], {'copied': 1})
            self.assertEqual(second['counts'], {'verified': 1})
            self.assertEqual(Path(storage_root, name).read_bytes(), payload)

        attachment.refresh_from_db()
        self.assertEqual(attachment.id, original_id)
        self.assertEqual(attachment.file.name, name)

    def test_reconcile_unknown_requested_id_is_incomplete(self):
        missing_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            manifest_path = Path(target, 'manifest.json')
            with self.assertRaises(CommandError):
                call_command(
                    'reconcile_attachment_storage',
                    '--apply',
                    '--require-complete',
                    '--only', missing_id,
                    '--source-root', source,
                    '--manifest', str(manifest_path),
                    stdout=StringIO(),
                )
            manifest = json.loads(manifest_path.read_text())

        self.assertEqual(manifest['counts'], {'metadata_missing': 1})
        self.assertEqual(manifest['unresolved'], 1)
        self.assertEqual(manifest['attachments'][0]['id'], missing_id)

    def test_reconcile_rejects_same_size_wrong_hash_existing_object(self):
        expected = b'expected-proof-bytes'
        corrupt = b'X' * len(expected)
        name = 'wiki_attachments/2026/07/hash-proof.bin'
        attachment = Attachment.objects.create(
            page=self.page,
            file=name,
            filename='hash-proof.bin',
            file_size=len(expected),
            mime_type='application/octet-stream',
            created_by_id=self.member.id,
        )
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            source_path = Path(source, 'recovered.bin')
            source_path.write_bytes(expected)
            storage_path = Path(target, name)
            storage_path.parent.mkdir(parents=True)
            storage_path.write_bytes(corrupt)
            trusted_path = Path(source, 'trusted.json')
            trusted_path.write_text(json.dumps({
                'attachments': {
                    str(attachment.id): {
                        'source': 'recovered.bin',
                        'size': len(expected),
                        'sha256': hashlib.sha256(expected).hexdigest(),
                    },
                },
            }))
            manifest_path = Path(target, 'manifest.json')
            with override_settings(MEDIA_ROOT=target), self.assertRaises(CommandError):
                call_command(
                    'reconcile_attachment_storage',
                    '--apply',
                    '--require-complete',
                    '--only', str(attachment.id),
                    '--source-root', source,
                    '--trusted-manifest', str(trusted_path),
                    '--manifest', str(manifest_path),
                    stdout=StringIO(),
                )
            manifest = json.loads(manifest_path.read_text())

        self.assertEqual(manifest['counts'], {'target_hash_mismatch': 1})
        self.assertEqual(manifest['attachments'][0]['actual_size'], len(expected))
        self.assertNotEqual(
            manifest['attachments'][0]['sha256'],
            manifest['attachments'][0]['trusted_sha256'],
        )


@override_settings(SHIZUHA_WIKI_SERVICE_USER_ID=901)
class PublicationSnapshotCASTests(APITestCase):
    """PLS-482: Wiki is the atomic source-publication linearization point.

    P1 #4 (HLD v23 §17.4.6): the CAS endpoint is callable ONLY by the dedicated
    Pulse publication service principal (user 901 here via override) — ordinary
    same-org members and staff are rejected, and an unconfigured principal
    fails closed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.user = _fed(901, ORG_A, role='member')
        self.client = _client(self.user, ORG_A)
        self.space = Space.objects.create(
            organization_id=ORG_A, key='PUB', name='Publication',
            visibility='org', owner_id=self.user.id,
        )
        self.page = Page.objects.create(
            space=self.space, title='Contract', status='published', version=4,
            content_text='# Contract\nbody\n\n## Safety {#safety}\nnever stale\n',
            content_json={}, created_by_id=self.user.id,
        )

    def _payload(self, operation_key='op-1'):
        anchors = [
            {'anchor': section.anchor, 'section_hash': section.section_hash}
            for section in list_markdown_sections(self.page.content_text)
        ]
        return {
            'operation_key': operation_key,
            'organization_id': ORG_A,
            'publication_result': 'accepted',
            'pages': [{
                'page_id': str(self.page.id),
                'version': self.page.version,
                'anchors': anchors,
            }],
        }

    def test_exact_replay_returns_one_immutable_snapshot(self):
        payload = self._payload()
        first = self.client.post('/api/publication-snapshots/', payload, format='json')
        second = self.client.post('/api/publication-snapshots/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(first.data['replay'])
        self.assertTrue(second.data['replay'])
        self.assertEqual(first.data['publication_snapshot_id'], second.data['publication_snapshot_id'])
        self.assertEqual(PublicationSnapshot.objects.count(), 1)

    def test_concurrent_edit_or_changed_hash_yields_typed_stale_hold(self):
        payload = self._payload()
        self.page.content_text += '\nchanged\n'
        self.page.version += 1
        self.page.save(update_fields=['content_text', 'version'])

        response = self.client.post('/api/publication-snapshots/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['error'], 'stale_publication_hold')
        self.assertEqual(response.data['current_pages'][0]['version'], 5)
        self.assertEqual(PublicationSnapshot.objects.count(), 0)

    def test_operation_key_is_payload_bound_and_cross_org_is_hidden(self):
        payload = self._payload()
        self.assertEqual(
            self.client.post('/api/publication-snapshots/', payload, format='json').status_code,
            status.HTTP_201_CREATED,
        )
        changed = self._payload()
        changed['publication_result'] = 'rejected'
        conflict = self.client.post('/api/publication-snapshots/', changed, format='json')
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(conflict.data['error'], 'publication_operation_conflict')

        outsider = _client(_fed(902, ORG_B, role='admin'), ORG_B)
        forbidden = outsider.post('/api/publication-snapshots/', payload, format='json')
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_same_org_member_is_rejected_even_with_membership(self):
        """P1 #4: org membership is NOT sufficient — a same-org non-service
        member cannot create snapshots or read structural hashes."""
        member = _client(_fed(903, ORG_A, role='member'), ORG_A)
        response = member.post('/api/publication-snapshots/', self._payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PublicationSnapshot.objects.count(), 0)

    def test_staff_bypass_is_removed(self):
        """P1 #4: staff/superuser no longer bypasses the service-principal gate."""
        staff = FederatedUser(
            user_id=904,
            email=f'staff@org{ORG_A}.example',
            username='staff904',
            is_staff=True,
            is_superuser=True,
            enabled_services=['wiki'],
            organization_memberships={ORG_A: 'admin'},
        )
        response = _client(staff, ORG_A).post(
            '/api/publication-snapshots/', self._payload(), format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PublicationSnapshot.objects.count(), 0)

    @override_settings(SHIZUHA_WIKI_SERVICE_USER_ID=0)
    def test_unconfigured_service_principal_fails_closed(self):
        """P1 #4: with no configured principal, even the would-be service
        identity is rejected — the endpoint fails closed, never open."""
        response = self.client.post(
            '/api/publication-snapshots/', self._payload(), format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PublicationSnapshot.objects.count(), 0)

    def test_service_principal_wrong_org_scope_is_rejected(self):
        """The service token must still be scoped to the requested organization."""
        service_wrong_org = _client(_fed(901, ORG_B, role='member'), ORG_B)
        response = service_wrong_org.post(
            '/api/publication-snapshots/', self._payload(), format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PublicationSnapshot.objects.count(), 0)
