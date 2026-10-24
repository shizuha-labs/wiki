"""Views for Shizuha Wiki API"""
import copy
import logging
import time

from django.db import models, transaction
from django.db.models import Count, Q
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db.models.functions import Left
from rest_framework import viewsets, status, filters, permissions
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, APIException, NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination

from wiki.user_preferences import UserPreferenceView  # noqa: F401


class Conflict(APIException):
    """HTTP 409 — optimistic-concurrency version conflict (WIKI-7). DRF has no
    built-in 409; the detail dict is returned to the caller verbatim."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Resource changed since it was read; re-pull and retry.'
    default_code = 'conflict'


# WIKI-50: fields the page PATCH endpoint accepts OUTSIDE the serializer's
# writable set — optimistic-concurrency and version-metadata controls only.
# PLAT-8954: confirm_shrink joins as a control field — it arms/disarms the
# fail-closed shrink guard and is never persisted to the model.
PAGE_PATCH_CONTROL_FIELDS = frozenset({
    'expected_version',
    'base_version',
    'if_match',
    'change_message',
    'confirm_shrink',
})


def _reject_unknown_patch_fields(serializer, request):
    """WIKI-50: fail loud on any request field the page PATCH does not write.

    DRF silently drops unrecognized request fields, so a PATCH that carried only
    an unknown field (e.g. ``content`` instead of ``content_text``) used to
    return HTTP 200, bump ``version`` and store nothing — manufacturing a
    phantom no-diff revision with false optimistic-concurrency assurance. Raise
    400 naming each unknown field BEFORE any write or version change.
    """
    writable = {f.field_name for f in serializer._writable_fields}
    allowed = writable | PAGE_PATCH_CONTROL_FIELDS
    unknown = set(request.data.keys()) - allowed
    if unknown:
        raise ValidationError({
            field: [
                (
                    f'Unrecognized write field "{field}" on PATCH /api/pages/<id>/. '
                    f'Nothing was written and no version was consumed. Writable '
                    f'fields: {sorted(writable)}; control fields: {sorted(PAGE_PATCH_CONTROL_FIELDS)}.'
                )
            ]
            for field in sorted(unknown)
        })


def _page_write_would_change(page, validated_data):
    """WIKI-50: True iff the validated PATCH fields materially change the page.

    Lets a no-op write (field equal to current value, or an empty body) return
    200 without bumping ``version`` or manufacturing a PageVersion — a version
    number must only be consumed when stored content actually changes.
    """
    for key in validated_data:
        if key == 'space':
            # Space changes are rejected earlier (move endpoint) — not a write.
            continue
        if key == 'parent':
            new_pk = validated_data['parent'].pk if validated_data['parent'] is not None else None
            if new_pk != page.parent_id:
                return True
        elif key == 'labels':  # label_ids wire field, source='labels'
            new_ids = {label.pk for label in validated_data['labels']}
            if new_ids != set(page.labels.values_list('id', flat=True)):
                return True
        elif validated_data[key] != getattr(page, key, None):
            return True
    return False


class StorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Attachment metadata was deleted; durable object cleanup is pending retry.'
    default_code = 'storage_unavailable'

from .models import (
    Space, SpaceMembership, Label, Page, PageVersion,
    PageComment, Attachment, PageWatch, SpaceWatch, Template, PageLink
)
from .serializers import (
    SpaceListSerializer, SpaceDetailSerializer, SpaceCreateSerializer,
    SpaceMembershipSerializer, LabelSerializer, LabelUsageSerializer, PageListSerializer,
    PageDetailSerializer, PageCreateSerializer, PageVersionSerializer,
    PageCommentSerializer, AttachmentSerializer, TemplateSerializer,
    PageTreeSerializer, SearchResultSerializer, MovePageSerializer,
    ReorderSerializer, _can_create_page_in_space
)
from .permissions import (
    IsSpaceMember, IsSpaceAdmin, IsSpaceEditor,
    IsPageCreatorOrSpaceEditor, ServiceAccessPermission,
    WikiPermissionService, PagePermission, CommentPermission, AttachmentPermission,
    same_user_id,
    TemplatePermission,
)
from .section_edit import (
    find_section, hash_section, list_markdown_sections, splice_section,
    text_to_tiptap_json,
)
from .related import related_pages_for
from .security_events import emit_boundary_denial
from .attachment_deletion import AttachmentStorageDeletionError
from .attachment_integrity import commit_attachment_upload, verified_attachment_response
from .publication_snapshot import (
    PublicationSnapshotConflict,
    PublicationSnapshotInvalid,
    PublicationSnapshotStale,
    create_publication_snapshot,
)


logger = logging.getLogger(__name__)
ORIGIN_HLD_PAGE_ID = 'c0421715-2465-4156-9c91-41c918be27cf'


def _validate_origin_hld_candidate(page, *, title, content_text, content_json, status_value):
    """Reject a protected HLD mutation before any page/version row is written."""
    if str(page.id) != ORIGIN_HLD_PAGE_ID:
        return
    from .source_authority_contracts import (
        SourceAuthorityContractError,
        validate_source_authority_contract,
    )

    try:
        validate_source_authority_contract(
            'wiki.page_content',
            resource={
                'page_id': str(page.id),
                'space_id': str(page.space_id),
            },
            candidate={
                'title': title,
                'content_text': content_text,
                'content_json': content_json,
                'status': status_value,
            },
            expected_consumer='wiki.origin_hld',
        )
    except SourceAuthorityContractError as exc:
        raise ValidationError({
            'source_authority_contract': str(exc),
        }) from exc


class PublicationSnapshotCreateView(APIView):
    """Pulse-only CAS front door for immutable publication snapshots.

    Authentication is the normal Shizuha JWT path.  The service token must
    carry Wiki access and membership in the exact requested organization; the
    CAS service then proves every page belongs to that organization.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        try:
            organization_id = int(data.get('organization_id'))
        except (TypeError, ValueError):
            return Response(
                {'error': 'invalid_publication_snapshot', 'detail': 'organization_id must be an integer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        # PLS-482 P1 #4 / HLD v23 §17.4.6: this CAS endpoint is callable ONLY by
        # the dedicated Pulse publication service principal. Ordinary same-org
        # members and staff must be rejected — the service reads immutable
        # version/anchor-hash tuples across the whole organization, bypassing
        # page/space visibility, so org membership is NOT sufficient authority.
        # Fail closed when the principal is unconfigured.
        from django.conf import settings as django_settings
        service_user_id = int(
            getattr(django_settings, 'SHIZUHA_WIKI_SERVICE_USER_ID', 0) or 0
        )
        if service_user_id <= 0:
            raise PermissionDenied(
                'Publication snapshot service principal is not configured; failing closed.'
            )
        if int(getattr(user, 'id', 0) or 0) != service_user_id:
            raise PermissionDenied(
                'Publication snapshots may only be created by the Pulse publication service.'
            )
        memberships = {
            int(key): value
            for key, value in (getattr(user, 'organization_memberships', {}) or {}).items()
            if str(key).isdigit()
        }
        if organization_id not in memberships:
            raise PermissionDenied('Service token is not scoped to the requested organization.')

        try:
            snapshot, replay = create_publication_snapshot(
                operation_key=data.get('operation_key'),
                organization_id=organization_id,
                publication_result=data.get('publication_result'),
                pages=data.get('pages'),
                created_by_id=int(getattr(user, 'id', 0) or 0),
            )
        except PublicationSnapshotInvalid as exc:
            return Response(
                {'error': 'invalid_publication_snapshot', 'detail': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PublicationSnapshotStale as exc:
            return Response(
                {
                    'error': 'stale_publication_hold',
                    'detail': str(exc),
                    'current_pages': exc.current_pages,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except PublicationSnapshotConflict as exc:
            return Response(
                {'error': 'publication_operation_conflict', 'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                'publication_snapshot_id': str(snapshot.id),
                'snapshot_digest': snapshot.snapshot_digest,
                'organization_id': snapshot.organization_id,
                'publication_result': snapshot.publication_result,
                'pages': snapshot.page_tuples,
                'replay': replay,
            },
            status=status.HTTP_200_OK if replay else status.HTTP_201_CREATED,
        )


def _get_storage_quota_client():
    """Return the optional shared quota client without breaking core storage."""
    try:
        from shizuha_storage.mixins import get_quota_client
    except ModuleNotFoundError as exc:
        if exc.name != 'shizuha_storage':
            raise
        logger.warning('shizuha_storage is unavailable; continuing without quota reporting')
        return None
    return get_quota_client()


def _resolve_explicit_org_id(request):
    """
    Pull an explicit org from header (X-Organization-ID), `?organization=`,
    or `?organization_id=` query param. Returns None if none is set. Does NOT
    enforce membership here — that's the caller's job once they know whether
    the action is a read (membership-aware aggregation) or a write (must be a
    member).
    """
    org_id = getattr(request, 'organization_id', None)
    if org_id:
        try:
            return int(org_id)
        except (TypeError, ValueError):
            return None
    param = request.query_params.get('organization') or request.query_params.get('organization_id')
    if param:
        try:
            return int(param)
        except (TypeError, ValueError):
            return None
    return None


def _user_member_org_ids(request):
    """User's full set of org memberships (empty list = personal-only)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return []
    return list(getattr(user, 'organization_memberships', {}).keys() or [])


def get_org_filter_for_read(request):
    """
    Resolve the org scope for a READ endpoint.

    Returns:
      - int  → caller asked for a specific org; scope to it (caller still
               checks membership via _ensure_membership_for_read).
      - None → caller did not specify; aggregate across the user's orgs.
               Callers should filter `org_id IN _user_member_org_ids(request)`
               (or no filter at all for staff/superuser).

    Note this never raises. Reads are aggregate-by-default.
    """
    return _resolve_explicit_org_id(request)


def _ensure_membership_for_read(request, org_id):
    """Reject if the caller asked for an org they don't belong to."""
    user = request.user
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return
    if org_id in _user_member_org_ids(request):
        return
    # JWT organization_memberships is a snapshot (empty {} is common on
    # v4/June logins). Confirm live with Admin before 400/403 — same
    # identity-vs-authz split as the wiki product gate.
    from wiki.middleware import heal_request_org_membership
    if heal_request_org_membership(request, org_id):
        return
    emit_boundary_denial(
        request=request,
        service='wiki',
        operation='wiki.explicit_org_read',
        reason='cross_tenant_org_scope',
        target_org_id=org_id,
        source_org_ids=_user_member_org_ids(request),
    )
    raise PermissionDenied(
        f'You are not a member of organization {org_id}.'
    )


# WIKI-111: comment author identity surface.
#
# Identities are federated (shizuha-id) — the wiki persists only denormalized
# created_by_id integers and has no local user directory, so the comment
# payload carried no author identity and the UI fell back to "User #15"
# (the WIKI-53 surface stopped at author_id, which no consumer renders as a
# name). Resolve identities at READ time in one batched directory call
# (/api/internal/users/?ids=…, the same in-cluster trust + forwarded-caller
# pattern as SpaceViewSet.search_users), TTL-cached, fail-open: a directory
# outage degrades to the id-only payload and must never block the list.
AUTHOR_IDENTITY_TTL_S = 600
_author_identity_cache: dict = {}


def _resolve_author_identities(user_ids, request):
    """Best-effort {user_id: {'email': …, 'name': …}} for the requested ids."""
    now = time.monotonic()
    resolved = {}
    missing = []
    for uid in {int(u) for u in user_ids if u is not None}:
        hit = _author_identity_cache.get(uid)
        if hit and now - hit[0] < AUTHOR_IDENTITY_TTL_S:
            resolved[uid] = hit[1]
        else:
            missing.append(uid)
    if not missing:
        return resolved

    import requests as _req
    from django.conf import settings as _settings
    base = getattr(_settings, 'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
    headers = {}
    if 'Authorization' in request.headers:
        headers['Authorization'] = request.headers['Authorization']
    try:
        resp = _req.get(
            f'{base}/internal/users/',
            params={'ids': ','.join(str(u) for u in missing), 'limit': 100},
            headers=headers,
            timeout=3,
        )
        if resp.status_code == 200:
            for user in resp.json().get('results') or []:
                uid = user.get('id')
                if uid is None:
                    continue
                identity = {
                    'email': user.get('email') or '',
                    'name': (
                        ' '.join(
                            part for part in (user.get('first_name'), user.get('last_name'))
                            if part
                        ).strip()
                        or user.get('username')
                        or ''
                    ),
                }
                _author_identity_cache[uid] = (now, identity)
                resolved[uid] = identity
        else:
            logger.warning(
                f'WIKI-111 author directory returned {resp.status_code}; '
                'degrading to id-only author surface'
            )
    except _req.RequestException as exc:
        logger.warning(
            f'WIKI-111 author directory unreachable: {exc}; '
            'degrading to id-only author surface'
        )
    return resolved


def _enrich_comment_authors(payload, request):
    """Inject author_email/author_name into serialized comment dicts, in place.

    Recurses into nested ``replies`` so inline reply rows get the same surface.
    """
    if not isinstance(payload, list):
        return payload
    identities = _resolve_author_identities(
        [c.get('created_by_id') for c in payload if isinstance(c, dict)],
        request,
    )
    for comment in payload:
        if not isinstance(comment, dict):
            continue
        identity = identities.get(comment.get('created_by_id'))
        if identity:
            comment['author_email'] = identity['email']
            comment['author_name'] = identity['name']
        if isinstance(comment.get('replies'), list):
            _enrich_comment_authors(comment['replies'], request)
    return payload


def visible_pages_qs(request):
    """The single source of object-level READ visibility for pages (WIKI-21).

    Every cross-object fetch that trusts a client-supplied page id (comment
    list by page_id, etc.) must scope through this queryset instead of a bare
    ``Page.objects.get/filter(id=...)`` — otherwise an authenticated user who
    knows a restricted page's UUID reads/mutates another space/org's data
    without a grant. Mirrors ``PageViewSet.get_queryset``'s org-membership +
    space-visibility (public / org / owner / member) logic.
    """
    user = request.user
    # SCS-239: anonymous reads are bearer-gated at the permission layer — no
    # anonymous queryset branch (the old public-cross-org path leaked org-61
    # content to unauthenticated callers).
    org_id = get_org_filter_for_read(request)
    if org_id is not None:
        _ensure_membership_for_read(request, org_id)
        queryset = Page.objects.filter(space__organization_id=org_id)
    else:
        member_org_ids = _user_member_org_ids(request)
        if user.is_staff or user.is_superuser:
            queryset = Page.objects.all()
        elif member_org_ids:
            queryset = Page.objects.filter(space__organization_id__in=member_org_ids)
        else:
            queryset = Page.objects.filter(space__visibility='public')
    return queryset.filter(
        Q(space__visibility__in=('org', 'public')) |
        Q(space__owner_id=user.id) |
        Q(space__memberships__user_id=user.id)
    ).distinct()


def visible_templates_qs(request, *, organization_id=None):
    """Canonical tenant + space visibility boundary for templates.

    Availability filters such as ``?space=`` are intentionally *not* applied
    here: an object's UUID identity must not disappear merely because a list
    filter is absent. TemplateViewSet applies availability only to ``list``.
    """
    user = request.user
    if not user.is_authenticated:
        return Template.objects.none()

    org_id = organization_id
    if org_id is None:
        org_id = get_org_filter_for_read(request)
    if org_id is not None:
        _ensure_membership_for_read(request, org_id)
        queryset = Template.objects.filter(organization_id=org_id)
    elif user.is_staff or user.is_superuser:
        queryset = Template.objects.all()
    else:
        member_org_ids = _user_member_org_ids(request)
        if not member_org_ids:
            return Template.objects.none()
        queryset = Template.objects.filter(organization_id__in=member_org_ids)

    return queryset.filter(
        Q(is_global=True) |
        Q(space__isnull=True) |
        Q(space__visibility__in=('org', 'public')) |
        Q(space__owner_id=user.id) |
        Q(space__memberships__user_id=user.id)
    ).select_related('space').distinct()


def assert_page_writable(request, page):
    """Reject a WRITE that targets a page the caller cannot access (WIKI-19).

    WIKI-21 closed the object-level READ gaps (comment-list, page-move, reorder)
    via ``visible_pages_qs``; the sibling WRITE paths that take a ``page`` FK in
    the request body — comment-create and attachment-upload — were still
    unguarded, so a cross-org/cross-space caller could POST a comment or upload
    an attachment onto any page by UUID. Gate them on the SAME visibility
    queryset. Raises NotFound (404) to match the read-path never-reveal-existence
    pattern; a null page is left to serializer required-field validation.
    """
    if page is None:
        return
    from rest_framework.exceptions import NotFound
    if not visible_pages_qs(request).filter(pk=page.pk).exists():
        raise NotFound('No Page matches the given query.')


def get_required_org_id(request):
    """
    Resolve the org scope for a WRITE endpoint. Required.

    400s with a helpful message listing the caller's actual orgs so the
    agent (or human) knows what to pick. Also rejects orgs the caller
    isn't a member of.
    """
    org_id = _resolve_explicit_org_id(request)
    if org_id is None:
        member_orgs = _user_member_org_ids(request)
        if member_orgs:
            raise ValidationError({
                'organization': (
                    'organization_id is required for this action. '
                    f'You belong to: {member_orgs}. '
                    'Pass it as the X-Organization-ID header, ?organization=, '
                    'or ?organization_id= query param.'
                ),
            })
        raise ValidationError({
            'organization': (
                'organization_id is required for this action, but you do not '
                'belong to any organization.'
            ),
        })
    _ensure_membership_for_read(request, org_id)
    return org_id


class SpaceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Wiki Spaces"""
    permission_classes = [IsAuthenticated, ServiceAccessPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'key', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']
    lookup_field = 'key'  # Use space key for lookup instead of pk
    lookup_value_regex = '[^/]+'  # Allow any characters except /

    def get_permissions(self):
        if self.action == 'destroy':
            return [IsAuthenticated(), IsSpaceAdmin()]
        return super().get_permissions()

    def get_object(self):
        """Override to support case-insensitive key lookup."""
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        key = self.kwargs[lookup_url_kwarg]

        # Try to get by key (case-insensitive) first
        filter_kwargs = {'key__iexact': key}
        obj = queryset.filter(**filter_kwargs).first()

        # If not found, try by ID for backward compatibility
        if obj is None and key.isdigit():
            obj = queryset.filter(pk=int(key)).first()

        if obj is None:
            from rest_framework.exceptions import NotFound
            raise NotFound(detail=f"Space with key '{key}' not found")

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    def get_queryset(self):
        user = self.request.user

        # SCS-239: anonymous reads are bearer-gated at the permission layer.

        # Authenticated: org scope is optional. If specified, require
        # membership and narrow to that org. If not, aggregate across all
        # the user's org memberships (so an agent in multiple orgs sees
        # spaces from each one in a single list).
        org_id = get_org_filter_for_read(self.request)
        if org_id is not None:
            _ensure_membership_for_read(self.request, org_id)
            queryset = Space.objects.filter(organization_id=org_id)
        else:
            member_org_ids = _user_member_org_ids(self.request)
            if not member_org_ids and not (user.is_staff or user.is_superuser):
                # User is in zero orgs and didn't specify one — only public
                # spaces are visible.
                return Space.objects.filter(visibility='public', is_archived=False)
            if user.is_staff or user.is_superuser:
                queryset = Space.objects.all()
            else:
                queryset = Space.objects.filter(organization_id__in=member_org_ids)

        queryset = queryset.filter(
            Q(visibility__in=('org', 'public')) |
            Q(owner_id=user.id) |
            Q(memberships__user_id=user.id)
        ).distinct()

        # Filter archived
        show_archived = self.request.query_params.get('archived', 'false').lower() == 'true'
        if not show_archived:
            queryset = queryset.filter(is_archived=False)

        # WIKI-54: honor the visibility query param (private/org/public) so
        # wiki_list_spaces(visibility=...) returns only matching spaces. The
        # access filter above already narrows to what the caller can see; this
        # narrows further to the requested visibility. Unknown values simply
        # match nothing (consistent with a filter, not an error).
        visibility = self.request.query_params.get('visibility')
        if visibility:
            queryset = queryset.filter(visibility=visibility)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return SpaceListSerializer
        elif self.action == 'create':
            return SpaceCreateSerializer
        return SpaceDetailSerializer

    def perform_create(self, serializer):
        from django.db import IntegrityError

        org_id = get_required_org_id(self.request)
        try:
            space = serializer.save(
                organization_id=org_id,
                owner_id=self.request.user.id
            )
        except IntegrityError as e:
            if 'organization_id_key' in str(e) or 'duplicate key' in str(e).lower():
                raise ValidationError({'key': f"A space with key '{serializer.validated_data.get('key')}' already exists in this organization."})
            raise

        # Add owner as admin member
        SpaceMembership.objects.create(
            space=space,
            user_id=self.request.user.id,
            role='admin',
            created_by_id=self.request.user.id
        )

    @action(detail=True, methods=['post'])
    def archive(self, request, key=None):
        """Archive a space"""
        space = self.get_object()
        if space.owner_id != request.user.id:
            return Response({'error': 'Only owner can archive'}, status=status.HTTP_403_FORBIDDEN)
        space.is_archived = True
        space.save()
        return Response({'status': 'archived'})

    @action(detail=True, methods=['post'])
    def unarchive(self, request, key=None):
        """Unarchive a space"""
        space = self.get_object()
        if space.owner_id != request.user.id:
            return Response({'error': 'Only owner can unarchive'}, status=status.HTTP_403_FORBIDDEN)
        space.is_archived = False
        space.save()
        return Response({'status': 'unarchived'})

    @action(detail=True, methods=['get', 'post', 'patch', 'delete'])
    def members(self, request, key=None):
        """Manage space members"""
        space = self.get_object()

        if request.method == 'GET':
            memberships = space.memberships.all()
            serializer = SpaceMembershipSerializer(memberships, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            # Check if user is space admin, space owner, or org admin
            is_space_admin = space.memberships.filter(user_id=request.user.id, role='admin').exists()
            is_owner = space.owner_id == request.user.id
            org_role = getattr(request.user, 'organization_role', None)
            is_org_admin = org_role in ('admin', 'owner') and space.visibility in ('org', 'public')
            if not (is_space_admin or is_owner or is_org_admin or getattr(request.user, 'is_superuser', False)):
                return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

            serializer = SpaceMembershipSerializer(data={
                'space': space.id,
                'user_id': request.data.get('user_id'),
                'role': request.data.get('role', 'viewer')
            })
            if serializer.is_valid():
                serializer.save(created_by_id=request.user.id)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == 'PATCH':
            # Check if user is space admin, space owner, or org admin
            is_space_admin = space.memberships.filter(user_id=request.user.id, role='admin').exists()
            is_owner = space.owner_id == request.user.id
            org_role = getattr(request.user, 'organization_role', None)
            is_org_admin = org_role in ('admin', 'owner') and space.visibility in ('org', 'public')
            if not (is_space_admin or is_owner or is_org_admin or getattr(request.user, 'is_superuser', False)):
                return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

            user_id = request.data.get('user_id')
            role = request.data.get('role')

            if not user_id or not role:
                return Response({'error': 'user_id and role required'}, status=status.HTTP_400_BAD_REQUEST)

            if role not in ['admin', 'editor', 'viewer']:
                return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)

            membership = space.memberships.filter(user_id=user_id).first()
            if not membership:
                return Response({'error': 'Membership not found'}, status=status.HTTP_404_NOT_FOUND)

            membership.role = role
            membership.save()
            return Response(SpaceMembershipSerializer(membership).data)

        elif request.method == 'DELETE':
            # Admin/owner check for member removal
            if not WikiPermissionService.can_perform(request.user, 'space:manage_members', space=space):
                return Response(
                    {'error': 'You do not have permission to manage members.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            user_id = request.data.get('user_id')
            if not user_id:
                return Response({'error': 'user_id required'}, status=status.HTTP_400_BAD_REQUEST)
            space.memberships.filter(user_id=user_id).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def search_users(self, request, key=None):
        """Search users to add as space members (proxy to shizuha-id)"""
        import requests
        from django.conf import settings

        space = self.get_object()

        # Check if user is admin
        if not space.memberships.filter(user_id=request.user.id, role='admin').exists():
            if space.owner_id != request.user.id:
                return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        query = request.query_params.get('q', '')
        if len(query) < 2:
            return Response([])

        # Get existing member user_ids to exclude
        existing_member_ids = list(space.memberships.values_list('user_id', flat=True))

        try:
            # Call shizuha-id internal API
            id_api_url = getattr(settings, 'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
            # Forward the Authorization header from the request
            headers = {}
            if 'Authorization' in request.headers:
                headers['Authorization'] = request.headers['Authorization']

            response = requests.get(
                f'{id_api_url}/users/search/',
                params={'q': query},
                headers=headers,
                timeout=5
            )

            if response.status_code == 200:
                users = response.json()
                # Filter out existing members
                users = [u for u in users if u.get('id') not in existing_member_ids]
                return Response(users)
            else:
                return Response({'error': 'Failed to search users'}, status=status.HTTP_502_BAD_GATEWAY)

        except requests.RequestException as e:
            return Response({'error': f'Service unavailable: {str(e)}'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=True, methods=['get'])
    def tree(self, request, key=None):
        """Get page tree for space"""
        space = self.get_object()
        # Show published pages and the user's own drafts
        page_filter = Q(status='published')
        if request.user.is_authenticated:
            page_filter = page_filter | Q(created_by_id=request.user.id)

        # Limit depth to prevent massive responses (default 5 levels, max 10)
        try:
            max_depth = min(int(request.query_params.get('max_depth', 5)), 10)
        except (ValueError, TypeError):
            max_depth = 5

        # Prefetch children recursively to avoid N+1 queries
        root_pages = space.pages.filter(
            parent=None
        ).filter(page_filter).order_by('position', 'title')

        # Build tree with prefetching
        serializer = PageTreeSerializer(
            root_pages,
            many=True,
            context={'request': request, 'max_depth': max_depth, 'current_depth': 0}
        )
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def watch(self, request, key=None):
        """Watch/unwatch a space"""
        space = self.get_object()
        watch, created = SpaceWatch.objects.get_or_create(
            space=space, user_id=request.user.id
        )
        if not created:
            watch.delete()
            return Response({'watching': False})
        return Response({'watching': True})

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def permissions(self, request, key=None):
        """GET /spaces/{key}/permissions/ — returns user's role and action set."""
        space = self.get_object()
        return Response(WikiPermissionService.get_space_permissions(request.user, space))


class PageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Wiki Pages"""
    permission_classes = [IsAuthenticated, ServiceAccessPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'content_text']
    ordering_fields = ['title', 'created_at', 'updated_at', 'position']
    ordering = ['position', 'title']

    def perform_destroy(self, instance):
        try:
            with transaction.atomic():
                page = Page.objects.select_for_update().get(pk=instance.pk)
                _validate_origin_hld_candidate(
                    page,
                    title='',
                    content_text='',
                    content_json={},
                    status_value='deleted',
                )
                page.delete()
        except AttachmentStorageDeletionError as exc:
            raise StorageUnavailable() from exc

    def get_permissions(self):
        if self.action == 'sections' and self.request.method not in permissions.SAFE_METHODS:
            return [IsAuthenticated(), PagePermission()]
        if self.action in ('destroy', 'update', 'partial_update', 'restore_version', 'move', 'verify'):
            return [IsAuthenticated(), PagePermission()]
        return super().get_permissions()

    def get_queryset(self):
        # WIKI-21: object-level read visibility now lives in the shared
        # visible_pages_qs() helper (single source of truth), reused by
        # CommentViewSet and any other cross-object fetch.
        queryset = visible_pages_qs(self.request)

        # Filter by space
        space_id = self.request.query_params.get('space')
        if space_id:
            queryset = queryset.filter(space_id=space_id)

        # Filter by space key
        space_key = self.request.query_params.get('space_key')
        if space_key:
            queryset = queryset.filter(space__key=space_key.upper())

        # Filter by parent
        parent_id = self.request.query_params.get('parent')
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)
        elif self.request.query_params.get('root_only', 'false').lower() == 'true':
            queryset = queryset.filter(parent=None)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by label
        label_id = self.request.query_params.get('label')
        if label_id:
            queryset = queryset.filter(labels__id=label_id)

        # Filter by slug
        slug = self.request.query_params.get('slug')
        if slug:
            queryset = queryset.filter(slug=slug)

        # WIKI-85: server-side partial-ID prefix resolution. The MCP client
        # previously walked every paginated /pages/ page in Python (1400+ pages
        # at 20/page) to resolve a partial UUID — exceeding the 30s MCP timeout.
        # Resolve the prefix in ONE indexed query here instead. Cast the UUID to
        # text so a prefix LIKE can match (UUIDField has no native startswith).
        prefix = self.request.query_params.get('prefix')
        if prefix and len(prefix) >= 4:
            from django.db.models import CharField
            from django.db.models.functions import Cast
            queryset = queryset.annotate(
                _id_str=Cast('id', output_field=CharField()),
            ).filter(_id_str__startswith=prefix.lower())

        return queryset.select_related('space').prefetch_related('labels')

    def get_serializer_class(self):
        if self.action == 'list':
            return PageListSerializer
        elif self.action == 'create':
            return PageCreateSerializer
        return PageDetailSerializer

    def create(self, request, *args, **kwargs):
        # HIVE-433: explicit wrong-org writes must fail as authz denials before
        # serializer validation can turn the request into a non-contract 400.
        explicit_org = _resolve_explicit_org_id(request)
        space_id = request.data.get('space')
        if explicit_org is not None and space_id:
            target_org = (
                Space.objects.filter(pk=space_id)
                .values_list('organization_id', flat=True)
                .first()
            )
            if target_org is not None and int(target_org) != int(explicit_org):
                raise PermissionDenied(
                    f'organization_id={explicit_org} does not match the target '
                    f'space (org={target_org}).'
                )
        # WIKI-11: surface cross-link resolution warnings (dangling targets)
        # in the create response — additive, non-blocking (save still succeeds).
        self._link_warnings = []
        response = super().create(request, *args, **kwargs)
        if isinstance(response.data, dict):
            response.data['link_warnings'] = getattr(self, '_link_warnings', [])
        return response

    def update(self, request, *args, **kwargs):
        # WIKI-11: same for full/partial page updates.
        self._link_warnings = []
        response = super().update(request, *args, **kwargs)
        if isinstance(response.data, dict):
            response.data['link_warnings'] = getattr(self, '_link_warnings', [])
        return response

    @action(detail=True, methods=['patch'])
    def verify(self, request, pk=None):
        """WIKI-125: mark this page verified — PATCH /pages/{pk}/verify/.

        Body (optional): {"owner": <Shizuha user id>}. Sets verified_at=now,
        verified_by=caller; verify_owner defaults to the verifier on first
        verify and is preserved on re-verify unless an explicit owner is
        passed. Gate: editor-or-admin on the page's space (same as content
        edit, via PagePermission's ACTION_MAP).

        Conflict safety (WIKI-123 S-B): the verification is bound to the
        content bytes and version read at transaction start. A concurrent
        content write wins the race and the caller gets 409 — verification
        never resurrects a state that a content write just cleared, and it
        never attests content the verifier did not see.
        """
        from django.utils import timezone

        owner_raw = request.data.get('owner') if isinstance(request.data, dict) else None
        if owner_raw is not None and not isinstance(owner_raw, int):
            if isinstance(owner_raw, str) and owner_raw.isdigit():
                owner_raw = int(owner_raw)
            else:
                return Response(
                    {'error': 'invalid owner',
                     'detail': 'owner must be a Shizuha user id (integer). '
                               'Use wiki_get_my_identity / the identity API to resolve one.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        page = self.get_object()  # visibility + editor-or-admin object gate
        pre_version = page.version
        pre_content = page.content_text
        pre_json = page.content_json

        with transaction.atomic():
            locked = Page.objects.select_for_update().get(pk=page.pk)
            # Version covers normal content writes (they bump version and clear
            # verification in the same transaction). content_text/content_json
            # cover a WIKI-93 shape change that cleared verification without a
            # version the caller still matches — never resurrect that clear.
            if (
                locked.version != pre_version
                or locked.content_text != pre_content
                or locked.content_json != pre_json
            ):
                return Response(
                    {'error': 'verify_conflict',
                     'detail': 'Page content changed while verifying; verification '
                               'was not applied. Re-read the page and retry.',
                     'current_version': locked.version},
                    status=status.HTTP_409_CONFLICT,
                )
            locked.verified_at = timezone.now()
            locked.verified_by_id = request.user.id
            if owner_raw is not None:
                locked.verify_owner_id = owner_raw
            elif locked.verify_owner_id is None:
                locked.verify_owner_id = request.user.id
            locked.save(update_fields=['verified_at', 'verified_by_id', 'verify_owner_id'])

        return Response({
            'page_id': str(locked.id),
            'verified_at': locked.verified_at,
            'verified_by_id': locked.verified_by_id,
            'verify_owner_id': locked.verify_owner_id,
            'version': locked.version,
        })

    @action(detail=True, methods=['get'])
    def link_markup(self, request, pk=None):
        """WIKI-11 insert helper: a correctly-formatted `[[...]]` wikilink to
        this page (optional `?alias=` for a display label)."""
        from .links import format_page_link
        page = self.get_object()
        alias = request.query_params.get('alias') or None
        return Response({
            'markup': format_page_link(page, alias=alias),
            'page_id': str(page.id),
            'slug': page.slug,
        })

    def perform_create(self, serializer):
        # Defense-in-depth: if the caller passed X-Organization-ID, it must
        # match the target space's org. Otherwise the agent might think it
        # created the page in org A while it actually landed in org B.
        explicit_org = _resolve_explicit_org_id(self.request)
        space = serializer.validated_data.get('space')
        if explicit_org is not None and space is not None and space.organization_id != explicit_org:
            raise PermissionDenied(
                f'organization_id={explicit_org} does not match the target '
                f'space (org={space.organization_id}).'
            )
        # Authoritative server-side write-scope gate (WIKI-19 P1): even with NO
        # explicit org header, public/org-visible spaces are not writable by an
        # arbitrary authenticated cross-org caller. Backstops the serializer check;
        # 404 (NotFound), never revealing the space's existence to a non-member.
        user = self.request.user
        if space is not None and not _can_create_page_in_space(user, space):
            raise NotFound('No Space matches the given query.')
        template_id = getattr(serializer, '_template_id', None)
        if template_id is not None:
            template = visible_templates_qs(self.request).filter(pk=template_id).first()
            if template is None:
                raise NotFound('No Template matches the given query.')
            if template.organization_id != space.organization_id:
                raise NotFound('No Template matches the given query.')
            if not template.is_global and template.space_id is not None and template.space_id != space.id:
                raise ValidationError({
                    'template_id': 'This space-scoped template is not available in the target space.'
                })
            serializer.validated_data['content_json'] = copy.deepcopy(template.content_json)
            serializer.validated_data['content_text'] = template.content_text

        with transaction.atomic():
            # Serialize page creation with a concurrent cross-space move of its
            # parent. After waiting for the parent row, revalidate the live space
            # so a stale request cannot create a cross-space hierarchy edge.
            parent = serializer.validated_data.get('parent')
            if parent is not None:
                parent = Page.objects.select_for_update().get(pk=parent.pk)
                if parent.space_id != space.id:
                    raise ValidationError({
                        'parent': 'Parent page moved to another space; re-pull and retry.'
                    })
                serializer.validated_data['parent'] = parent

            page = serializer.save(created_by_id=self.request.user.id)
            # Create initial version
            PageVersion.objects.create(
                page=page,
                version_number=1,
                title=page.title,
                content_json=page.content_json,
                content_text=page.content_text,
                change_message='Initial version',
                created_by_id=self.request.user.id
            )
            # WIKI-11: resolve [[...]]/id cross-links, sync the PageLink backlink
            # index, and stash dangling targets to surface as a non-blocking warning.
            from .links import sync_page_links
            self._link_warnings = sync_page_links(page)

    def perform_update(self, serializer):
        # WIKI-50: fail loud on unknown write fields BEFORE anything else — DRF
        # silently drops them, so `content` used to return 200 + bump version
        # while storing nothing (phantom no-diff revision).
        _reject_unknown_patch_fields(serializer, self.request)

        # WIKI-7: optimistic concurrency. The page-update API is a full-page
        # replace; without a base-version check, two concurrent editors silently
        # last-write-wins (real loss on co-edited HLD pages). When the caller
        # supplies the base version it read (`expected_version`/`base_version`/
        # `if_match`), REJECT with 409 if the page advanced since — instead of
        # clobbering — and tell the caller to re-pull + retry. Back-compat: when
        # no base version is supplied, behavior is unchanged (last-write-wins).
        expected_version = (
            self.request.data.get('expected_version')
            if self.request.data.get('expected_version') is not None
            else self.request.data.get('base_version', self.request.data.get('if_match'))
        )

        with transaction.atomic():
            page = (
                Page.objects.select_for_update().select_related('space')
                .get(pk=serializer.instance.pk)
            )
            serializer.instance = page
            if 'space' in serializer.validated_data and serializer.validated_data['space'].id != page.space_id:
                raise ValidationError({'space': 'Use the move endpoint to change page space.'})
            parent = serializer.validated_data.get('parent', page.parent)
            if parent is not None:
                parent = Page.objects.select_for_update().get(pk=parent.pk)
                if parent.space_id != page.space_id:
                    raise ValidationError({'parent': 'Parent page must belong to the same space.'})
                serializer.validated_data['parent'] = parent
            if expected_version is not None:
                try:
                    expected_int = int(expected_version)
                except (TypeError, ValueError):
                    raise ValidationError({
                        'expected_version': 'Must be an integer (the page version you read).'
                    })
                # Lock the row so concurrent saves serialize through the check —
                # re-read the authoritative version under the lock (avoids the
                # read-then-save TOCTOU where two writers both pass the check).
                current = page.version
                if current != expected_int:
                    raise Conflict({
                        'error': 'version_conflict',
                        'detail': (
                            f'Page has changed since you read it (you based your edit on '
                            f'v{expected_int}, but it is now v{current}). Re-pull the page '
                            f'and re-apply your changes to avoid overwriting another edit.'
                        ),
                        'expected_version': expected_int,
                        'current_version': current,
                    })

            # PLAT-8954: fail closed on dramatic content shrink. The CON-429 v7
            # loss shape: a client (web editor or truncated tool arg) submitted
            # only the verdict block of an 18K design SoT and the server stored
            # it — §1–§10 destroyed silently. The server cannot distinguish a
            # truncated submission from intent, so a whole-page replace that
            # drops >50% of stored content (when >= 2000 chars are stored) is
            # REJECTED unless the caller explicitly passes confirm_shrink=true.
            _new_text = serializer.validated_data.get('content_text')
            if _new_text is not None:
                _confirm = self.request.data.get('confirm_shrink')
                _old_len = len(page.content_text or '')
                _new_len = len(_new_text)
                _confirmed = _confirm is True or str(_confirm).strip().lower() == 'true'
                if _old_len >= 2000 and _new_len < _old_len / 2 and not _confirmed:
                    raise ValidationError({
                        'confirm_shrink': (
                            f'This save would drop {_old_len - _new_len} of {_old_len} '
                            f'stored characters ({_new_len} would remain). Dramatic '
                            'shrinks are usually truncated submissions (client-side '
                            'payload loss), not intent — re-pull the page and submit '
                            'the full document, or pass confirm_shrink=true to '
                            'acknowledge the loss.'
                        ),
                        'stored_chars': _old_len,
                        'submitted_chars': _new_len,
                    })

            _validate_origin_hld_candidate(
                page,
                title=serializer.validated_data.get('title', page.title),
                content_text=serializer.validated_data.get(
                    'content_text', page.content_text
                ),
                content_json=serializer.validated_data.get(
                    'content_json', page.content_json
                ),
                status_value=serializer.validated_data.get('status', page.status),
            )

            # WIKI-50: a write that leaves stored content byte-identical must not
            # consume a version nor manufacture a phantom revision. The serializer
            # instance is the freshly locked row, so DRF returns it unchanged (200)
            # without saving or creating a PageVersion.
            if not _page_write_would_change(page, serializer.validated_data):
                return

            old_version = page.version
            # WIKI-124: same-transaction verification auto-clear. Any byte
            # change to content clears verification; WIKI-50 no-diff and
            # title-only edits preserve it; WIKI-93 json shape changes clear
            # (stored-bytes comparison).
            _clear_kwargs = Page.verification_auto_clear_kwargs(
                serializer.validated_data.get('content_text', page.content_text),
                serializer.validated_data.get('content_json', page.content_json),
                page.content_text,
                page.content_json,
            )
            page = serializer.save(
                updated_by_id=self.request.user.id,
                version=old_version + 1,
                **_clear_kwargs,
            )

            # Create version record
            change_message = self.request.data.get('change_message', '')
            PageVersion.objects.create(
                page=page,
                version_number=page.version,
                title=page.title,
                content_json=page.content_json,
                content_text=page.content_text,
                change_message=change_message,
                created_by_id=self.request.user.id
            )
            # WIKI-11: resolve cross-links + sync the PageLink backlink index;
            # stash dangling targets for a non-blocking save warning.
            from .links import sync_page_links
            self._link_warnings = sync_page_links(page)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Increment view count
        Page.objects.filter(pk=instance.pk).update(view_count=instance.view_count + 1)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'post'])
    def sections(self, request, pk=None):
        """List or update Markdown heading sections for a page (WIKI-8).

        GET returns deterministic section hashes. POST splices only the target
        section if `base_section_hash` still matches the current section text;
        concurrent edits to other sections can therefore land independently.
        """
        if request.method == 'GET':
            page = self.get_object()
            sections = list_markdown_sections(page.content_text or '')
            return Response({
                'page_id': str(page.id),
                'version': page.version,
                'sections': [
                    {
                        'heading': section.heading,
                        'anchor': section.anchor,
                        'level': section.level,
                        'start_line': section.start_line,
                        'end_line': section.end_line,
                        'section_hash': section.section_hash,
                    }
                    for section in sections
                ],
            })

        heading_or_anchor = request.data.get('heading_or_anchor') or request.data.get('anchor') or request.data.get('heading')
        base_section_hash = request.data.get('base_section_hash')
        content = request.data.get('content')
        if not heading_or_anchor:
            raise ValidationError({'heading_or_anchor': 'This field is required.'})
        if not base_section_hash:
            raise ValidationError({'base_section_hash': 'This field is required.'})
        if content is None:
            raise ValidationError({'content': 'This field is required.'})

        with transaction.atomic():
            page = Page.objects.select_for_update().get(pk=self.get_object().pk)
            self.check_object_permissions(request, page)
            try:
                section = find_section(page.content_text or '', heading_or_anchor)
            except LookupError as exc:
                return Response({'error': 'section_not_found', 'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
            except ValueError as exc:
                raise ValidationError({'heading_or_anchor': str(exc)})

            current_hash = hash_section(section.content)
            if current_hash != str(base_section_hash):
                raise Conflict({
                    'error': 'section_conflict',
                    'detail': (
                        f'Section {section.heading!r} changed since you read it. '
                        'Re-pull that section and retry with the current hash.'
                    ),
                    'heading_or_anchor': heading_or_anchor,
                    'expected_section_hash': str(base_section_hash),
                    'current_section_hash': current_hash,
                    'current_version': page.version,
                })

            _old_content_text = page.content_text
            _old_content_json = page.content_json
            new_text = splice_section(page.content_text or '', section, str(content))
            # PLAT-8954 (defense in depth): the section path is hash-guarded,
            # but a splice-base anomaly (e.g. content_text diverged from the
            # rendered doc) would silently drop the rest of the document. Same
            # fail-closed shrink rule as the whole-page path.
            _confirm = request.data.get('confirm_shrink')
            _old_len = len(page.content_text or '')
            _new_len = len(new_text)
            _confirmed = _confirm is True or str(_confirm).strip().lower() == 'true'
            if _old_len >= 2000 and _new_len < _old_len / 2 and not _confirmed:
                raise ValidationError({
                    'confirm_shrink': (
                        f'This section edit would drop {_old_len - _new_len} of '
                        f'{_old_len} stored characters ({_new_len} would remain). '
                        'Re-pull the page sections and retry with the current hash, '
                        'or pass confirm_shrink=true to acknowledge the loss.'
                    ),
                    'stored_chars': _old_len,
                    'submitted_chars': _new_len,
                })
            new_json = text_to_tiptap_json(new_text)
            _validate_origin_hld_candidate(
                page,
                title=page.title,
                content_text=new_text,
                content_json=new_json,
                status_value=page.status,
            )
            page.content_text = new_text
            page.content_json = new_json
            page.version += 1
            page.updated_by_id = request.user.id
            # WIKI-124: same-transaction verification auto-clear (bytes changed).
            for _field, _value in Page.verification_auto_clear_kwargs(
                page.content_text, page.content_json,
                _old_content_text, _old_content_json,
            ).items():
                setattr(page, _field, _value)
            page.save()

            updated_sections = list_markdown_sections(page.content_text or '')
            updated_section = next(
                (candidate for candidate in updated_sections if candidate.start_offset == section.start_offset),
                None,
            )
            if updated_section is None:
                updated_section = find_section(page.content_text or '', heading_or_anchor)
            PageVersion.objects.create(
                page=page,
                version_number=page.version,
                title=page.title,
                content_json=page.content_json,
                content_text=page.content_text,
                change_message=request.data.get('change_message') or f'Section edit: {updated_section.heading}',
                created_by_id=request.user.id,
            )

        serializer = PageDetailSerializer(page, context={'request': request})
        data = serializer.data
        data['section'] = {
            'heading': updated_section.heading,
            'anchor': updated_section.anchor,
            'section_hash': updated_section.section_hash,
        }
        return Response(data)

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Get version history for a page"""
        page = self.get_object()
        versions = page.versions.all()
        serializer = PageVersionSerializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def restore_version(self, request, pk=None):
        """Restore page to a specific version"""
        version_number = request.data.get('version')
        with transaction.atomic():
            page = Page.objects.select_for_update().get(pk=self.get_object().pk)
            self.check_object_permissions(request, page)
            try:
                version = page.versions.get(version_number=version_number)
            except PageVersion.DoesNotExist:
                return Response(
                    {'error': 'Version not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            _validate_origin_hld_candidate(
                page,
                title=version.title,
                content_text=version.content_text,
                content_json=version.content_json,
                status_value=page.status,
            )
            page.title = version.title
            page.content_json = version.content_json
            page.content_text = version.content_text
            page.version += 1
            page.updated_by_id = request.user.id
            page.save()

            PageVersion.objects.create(
                page=page,
                version_number=page.version,
                title=page.title,
                content_json=page.content_json,
                content_text=page.content_text,
                change_message=f'Restored from version {version_number}',
                created_by_id=request.user.id
            )

        serializer = PageDetailSerializer(page, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'post'])
    def comments(self, request, pk=None):
        """Get or add comments on a page"""
        page = self.get_object()

        if request.method == 'GET':
            comments = page.comments.filter(parent=None)
            serializer = PageCommentSerializer(comments, many=True)
            # WIKI-121: the page-scoped comment list is the Comments UI's own
            # read path and must carry the same WIKI-111 author-identity
            # surface as CommentViewSet list/retrieve — this action was the
            # drift site where the enrichment was never applied, so
            # MCP-authored comments rendered the "User #<id>" fallback here
            # while the per-comment view resolved. Fail-open semantics are
            # unchanged (directory outage degrades to the id-only payload).
            return Response(_enrich_comment_authors(serializer.data, request))

        elif request.method == 'POST':
            serializer = PageCommentSerializer(data={
                'page': page.id,
                'parent': request.data.get('parent'),
                'content': request.data.get('content'),
                'is_inline': request.data.get('is_inline', False),
                'selection_start': request.data.get('selection_start'),
                'selection_end': request.data.get('selection_end'),
            })
            if serializer.is_valid():
                serializer.save(created_by_id=request.user.id)
                # WIKI-121: same author surface on the create response — the
                # MCP add-comment tool renders this payload directly.
                return Response(_enrich_comment_authors([serializer.data], request)[0],
                                status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def watch(self, request, pk=None):
        """Watch/unwatch a page"""
        page = self.get_object()
        watch, created = PageWatch.objects.get_or_create(
            page=page, user_id=request.user.id
        )
        if not created:
            watch.delete()
            return Response({'watching': False})
        return Response({'watching': True})

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """Get child pages"""
        page = self.get_object()
        children = page.children.filter(status='published').order_by('position', 'title')
        serializer = PageListSerializer(children, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def backlinks(self, request, pk=None):
        """Get pages that link to this page"""
        page = self.get_object()
        linking_pages = Page.objects.filter(
            outgoing_links__target_page=page
        ).distinct()
        serializer = PageListSerializer(linking_pages, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def related(self, request, pk=None):
        """Get related pages using labels, link graph, and text similarity."""
        page = self.get_object()
        try:
            limit = int(request.query_params.get('limit', 6))
        except (TypeError, ValueError):
            limit = 6
        related = related_pages_for(page, visible_pages=self.get_queryset(), limit=limit)
        pages = [item['page'] for item in related]
        serialized = PageListSerializer(pages, many=True, context={'request': request}).data
        by_id = {str(item['page'].id): item for item in related}
        for row in serialized:
            meta = by_id.get(str(row.get('id')))
            if meta:
                row['related_score'] = meta['score']
                row['related_reasons'] = meta['reasons']
        return Response(serialized)

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        """Move a page (and its subtree) to a parent and/or another space."""
        page = self.get_object()
        serializer = MovePageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_space_id = serializer.validated_data.get('space')
        new_position = serializer.validated_data.get('position', 0)

        with transaction.atomic():
            # The root lock is the hierarchy-mutation mutex: create/reparent
            # paths also lock their destination parent and revalidate its live
            # space after waiting. Enumeration, collision/parent validation and
            # updates therefore share one PostgreSQL transaction and lock set.
            page = (
                Page.objects.select_for_update().select_related('space')
                .get(pk=page.pk)
            )
            if not WikiPermissionService.can_perform(request.user, 'page:move', resource=page):
                raise PermissionDenied('You do not have permission to move this page.')

            target_space = page.space
            if target_space_id and target_space_id != page.space_id:
                try:
                    target_space = Space.objects.get(id=target_space_id)
                except Space.DoesNotExist:
                    raise NotFound('No Space matches the given query.')
                if target_space.organization_id != page.space.organization_id:
                    raise PermissionDenied('Pages cannot be moved across organizations.')
                if not _can_create_page_in_space(request.user, target_space):
                    raise NotFound('No Space matches the given query.')

            new_parent_id = serializer.validated_data.get('parent')
            if target_space.id != page.space_id and 'parent' not in request.data:
                new_parent_id = None

            subtree = self._locked_subtree(page)
            subtree_ids = [item.id for item in subtree]

            if new_parent_id:
                try:
                    parent = (
                        Page.objects.select_for_update()
                        .get(id=new_parent_id, space_id=target_space.id)
                    )
                except Page.DoesNotExist:
                    return Response({'error': 'Parent page not found'}, status=status.HTTP_404_NOT_FOUND)
                if parent.id in subtree_ids:
                    return Response(
                        {'error': 'Cannot move page under itself'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if target_space.id != page.space_id:
                slugs = [item.slug for item in subtree]
                collisions = list(
                    Page.objects.select_for_update()
                    .filter(space=target_space, slug__in=slugs)
                    .exclude(id__in=subtree_ids)
                )
                if collisions:
                    raise Conflict({
                        'detail': 'Destination space already contains one or more page slugs.',
                        'slugs': [item.slug for item in collisions],
                    })
                Page.objects.filter(id__in=subtree_ids).update(space=target_space)
                Page.objects.filter(id=page.id).update(parent_id=new_parent_id, position=new_position)
            else:
                page.parent_id = new_parent_id
                page.position = new_position
                page.save(update_fields=['parent', 'position', 'updated_at'])

            page.refresh_from_db()
        return Response(PageDetailSerializer(page, context={'request': request}).data)

    @staticmethod
    def _locked_subtree(root):
        """Enumerate and row-lock one hierarchy subtree inside an atomic block."""
        subtree = []
        pending = [root]
        while pending:
            current = pending.pop(0)
            subtree.append(current)
            pending.extend(list(
                Page.objects.select_for_update().filter(parent_id=current.id)
            ))
        return subtree

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def reorder(self, request):
        """Bulk reorder sibling pages under a parent."""
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        page_ids = serializer.validated_data['page_ids']
        if not page_ids:
            return Response({'status': 'ok'})

        # WIKI-21 F2 (authz bypass): the old code checked page:move on page_ids[0]
        # ONLY, then update()'d ALL page_ids — so a caller could smuggle pages
        # from spaces they can't move into the list and reorder them. Every page
        # must exist, share ONE space, and pass page:move.
        pages = list(Page.objects.filter(id__in=page_ids).select_related('space'))
        if len(pages) != len(set(page_ids)):
            return Response(
                {'error': 'One or more pages not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        if len({p.space_id for p in pages}) != 1:
            return Response(
                {'error': 'All pages must belong to the same space.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        for p in pages:
            if not WikiPermissionService.can_perform(request.user, 'page:move', resource=p):
                return Response(
                    {'error': 'You do not have permission to reorder pages in this space.'},
                    status=status.HTTP_403_FORBIDDEN
                )

        position_by_id = {pid: i for i, pid in enumerate(page_ids)}
        for p in pages:
            Page.objects.filter(id=p.id).update(position=position_by_id[p.id])

        return Response({'status': 'ok'})


class LabelViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Labels"""
    serializer_class = LabelSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None  # Labels are a small set, return all
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def get_queryset(self):
        org_id = get_org_filter_for_read(self.request)
        if org_id is not None:
            _ensure_membership_for_read(self.request, org_id)
            return Label.objects.filter(organization_id=org_id).order_by('name')
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Label.objects.all().order_by('name')
        member_org_ids = _user_member_org_ids(self.request)
        if not member_org_ids:
            return Label.objects.none()
        return Label.objects.filter(organization_id__in=member_org_ids).order_by('name')

    def perform_create(self, serializer):
        from django.db import IntegrityError
        org_id = get_required_org_id(self.request)
        try:
            serializer.save(organization_id=org_id)
        except IntegrityError:
            raise ValidationError(
                {'name': 'A label with this name already exists.'}
            )

    @action(detail=False, methods=['get'])
    def cloud(self, request):
        """Label cloud/index weighted by published page usage."""
        space_key = request.query_params.get('space_key')
        queryset = self.get_queryset()
        page_filter = Q(pages__status='published')
        if space_key:
            page_filter &= Q(pages__space__key=space_key.upper())
        labels = queryset.annotate(pages_count=Count('pages', filter=page_filter, distinct=True)).filter(
            pages_count__gt=0
        ).order_by('-pages_count', 'name')
        return Response(LabelUsageSerializer(labels, many=True).data)

    @action(detail=True, methods=['get'])
    def pages(self, request, pk=None):
        """Paginated list of pages carrying this label."""
        label = self.get_object()
        page_queryset = PageViewSet()
        page_queryset.request = request
        pages = page_queryset.get_queryset().filter(labels=label, status='published')
        space_key = request.query_params.get('space_key')
        if space_key:
            pages = pages.filter(space__key=space_key.upper())
        pages = pages.order_by('title')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(pages, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(PageListSerializer(page, many=True, context={'request': request}).data)
        return Response(PageListSerializer(pages, many=True, context={'request': request}).data)


class TemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Page Templates"""
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), TemplatePermission()]
        return super().get_permissions()

    def get_queryset(self):
        write_action = self.action in ('update', 'partial_update', 'destroy')
        org_id = get_required_org_id(self.request) if write_action else get_org_filter_for_read(self.request)
        queryset = visible_templates_qs(self.request, organization_id=org_id)

        # ``space`` is an availability filter for list only. Applying it to
        # retrieve/update/delete caused WIKI-55's list-visible/detail-404 bug.
        if self.action != 'list':
            return queryset

        space_id = self.request.query_params.get('space')
        user = self.request.user
        if space_id:
            spaces = Space.objects.filter(pk=space_id, is_archived=False)
            if org_id is not None:
                spaces = spaces.filter(organization_id=org_id)
            elif not (user.is_staff or user.is_superuser):
                spaces = spaces.filter(organization_id__in=_user_member_org_ids(self.request))
            space = spaces.filter(
                Q(visibility__in=('org', 'public')) |
                Q(owner_id=user.id) |
                Q(memberships__user_id=user.id)
            ).distinct().first()
            if space is None:
                return Template.objects.none()
            return queryset.filter(organization_id=space.organization_id).filter(
                Q(is_global=True) | Q(space__isnull=True) | Q(space_id=space.id)
            )
        return queryset.filter(Q(is_global=True) | Q(space__isnull=True))

    def perform_create(self, serializer):
        org_id = get_required_org_id(self.request)
        space = serializer.validated_data.get('space')
        if space is not None:
            if space.organization_id != org_id:
                raise PermissionDenied(
                    f'organization_id={org_id} does not match the target '
                    f'space (org={space.organization_id}).'
                )
            if not _can_create_page_in_space(self.request.user, space):
                raise NotFound('No Space matches the given query.')
        serializer.save(
            organization_id=org_id,
            created_by_id=self.request.user.id
        )

    def perform_update(self, serializer):
        instance = serializer.instance
        space = serializer.validated_data.get('space', instance.space)
        if space is not None:
            if space.organization_id != instance.organization_id:
                raise PermissionDenied(
                    'A template cannot be moved across organization boundaries.'
                )
            if not _can_create_page_in_space(self.request.user, space):
                raise NotFound('No Space matches the given query.')
        serializer.save()


class AttachmentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Attachments"""
    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated, ServiceAccessPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        """Allow unauthenticated access to view action (for img tags)."""
        if self.action == 'view':
            return [permissions.AllowAny()]
        if self.action == 'destroy':
            return [IsAuthenticated(), AttachmentPermission()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user

        # SCS-239: anonymous reads are bearer-gated at the permission layer.
        org_id = get_org_filter_for_read(self.request)
        if org_id is not None:
            _ensure_membership_for_read(self.request, org_id)
            base_qs = Attachment.objects.filter(page__space__organization_id=org_id)
        else:
            member_org_ids = _user_member_org_ids(self.request)
            if user.is_staff or user.is_superuser:
                base_qs = Attachment.objects.all()
            elif member_org_ids:
                base_qs = Attachment.objects.filter(
                    page__space__organization_id__in=member_org_ids
                )
            else:
                base_qs = Attachment.objects.filter(page__space__visibility='public')
        base_qs = base_qs.filter(
            Q(page__space__visibility__in=('org', 'public')) |
            Q(page__space__owner_id=user.id) |
            Q(page__space__memberships__user_id=user.id)
        ).distinct()

        # For list views, require page_id filter
        # Use page_id to avoid conflict with DRF pagination's 'page' param
        if self.action == 'list':
            page_id = self.request.query_params.get('page_id') or self.request.query_params.get('page')
            if page_id:
                return base_qs.filter(page_id=page_id)
            return Attachment.objects.none()

        # For detail views (retrieve, download, view, destroy), return full queryset
        return base_qs

    def perform_create(self, serializer):
        # WIKI-19: an attachment must not be uploadable to a page the caller can't
        # reach (cross-org/cross-space IDOR — write sibling of WIKI-21's read fixes).
        assert_page_writable(self.request, serializer.validated_data.get('page'))
        file = self.request.FILES.get('file')
        if not file:
            raise ValidationError({'file': ['No file was uploaded.']})

        # Check storage quota before upload
        client = _get_storage_quota_client()
        if client and not client.can_upload_from_request(self.request, file.size):
            raise ValidationError({'file': ['Storage quota exceeded. Please free up space or upgrade your plan.']})

        commit_attachment_upload(
            serializer=serializer,
            request=self.request,
            uploaded_file=file,
        )

        # Report updated usage to Drive
        if client:
            usage = Attachment.objects.aggregate(
                total_bytes=models.Sum('file_size'),
                total_count=models.Count('id'),
            )
            client.report_usage_from_request(
                self.request,
                used_bytes=usage['total_bytes'] or 0,
                file_count=usage['total_count'] or 0,
            )

    def perform_destroy(self, instance):
        try:
            with transaction.atomic():
                instance.delete()
        except AttachmentStorageDeletionError as exc:
            raise StorageUnavailable() from exc

        # Report updated usage to Drive after deletion
        client = _get_storage_quota_client()
        if client:
            usage = Attachment.objects.aggregate(
                total_bytes=models.Sum('file_size'),
                total_count=models.Count('id'),
            )
            client.report_usage_from_request(
                self.request,
                used_bytes=usage['total_bytes'] or 0,
                file_count=usage['total_count'] or 0,
            )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        Download an attachment file.
        Returns the file with proper Content-Disposition header.
        """
        from django.http import Http404

        attachment = self.get_object()

        # get_object() already scopes via get_queryset, but the previous hand-rolled
        # `visibility in ('org','public')` grant here was the same cross-org IDOR as
        # view() (WIKI-19 P1). Gate on the SINGLE source of read-visibility truth.
        page = attachment.page
        if not visible_pages_qs(request).filter(pk=page.pk).exists():
            from django.http import Http404
            raise Http404("Attachment not found")

        return verified_attachment_response(
            attachment,
            range_header=request.headers.get('Range', ''),
            as_attachment=True,
        )

    @action(detail=True, methods=['get'])
    def view(self, request, pk=None):
        """
        View an attachment file inline (for images, PDFs, etc.).
        Returns the file with Content-Disposition: inline.
        Allows unauthenticated access for public spaces (needed for img tags).
        """
        from django.http import Http404

        # Get attachment directly (bypass get_object, which requires auth) so public
        # img tags render unauthenticated. Access is then scoped through the SINGLE
        # source of read-visibility truth (visible_pages_qs) — NOT a hand-rolled
        # `visibility in ('org','public')` grant, which authorized ANY authenticated
        # user (incl. a cross-org caller) to an org-visible space's attachment by
        # UUID (WIKI-19 P1: attachment-view IDOR). visible_pages_qs enforces
        # org-membership + space-visibility for authed users, and public-only for anon.
        try:
            attachment = Attachment.objects.get(pk=pk)
        except Attachment.DoesNotExist:
            raise Http404("Attachment not found")

        page = attachment.page
        if not visible_pages_qs(request).filter(pk=page.pk).exists():
            # 404, not 403 — never reveal the existence of an out-of-scope object.
            raise Http404("Attachment not found")

        return verified_attachment_response(
            attachment,
            range_header=request.headers.get('Range', ''),
            as_attachment=False,
        )


class CommentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing Comments"""
    serializer_class = PageCommentSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        # WIKI-111: inject the federated author surface into the paginated page.
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results') if isinstance(response.data, dict) else response.data
        if isinstance(results, list):
            _enrich_comment_authors(results, request)
        return response

    def retrieve(self, request, *args, **kwargs):
        # WIKI-111: same author surface on the single-comment read.
        response = super().retrieve(request, *args, **kwargs)
        if isinstance(response.data, dict):
            _enrich_comment_authors([response.data], request)
        return response

    def get_permissions(self):
        if self.action in ('destroy', 'resolve', 'unresolve'):
            return [IsAuthenticated(), CommentPermission()]
        return super().get_permissions()

    def get_queryset(self):
        # Detail actions must retain the visible-page scope without requiring a
        # list-only page_id query parameter. Returning none here made every
        # retrieve/update/delete/resolve request 404 immediately after a
        # successful create (KOT-93).
        visible_comments = PageComment.objects.filter(
            page__in=visible_pages_qs(self.request)
        )
        if self.action == 'list':
            # Use page_id to avoid conflict with DRF pagination's 'page' param.
            page_id = self.request.query_params.get('page_id') or self.request.query_params.get('page')
            if page_id:
                return visible_comments.filter(page_id=page_id)
            return PageComment.objects.none()
        return visible_comments

    def perform_create(self, serializer):
        # WIKI-19: a comment must not be writable on a page the caller can't reach
        # (cross-org/cross-space IDOR — the write sibling of WIKI-21's F3 read fix).
        assert_page_writable(self.request, serializer.validated_data.get('page'))
        serializer.save(created_by_id=self.request.user.id)

    def perform_update(self, serializer):
        # Comment text is author-owned. Space editors can moderate through
        # resolve/delete permissions, but must not rewrite another author's words.
        # WIKI-81: compare type-safely — a federated user.id can be a str JWT
        # claim while created_by_id is an int, and `141 != "141"` wrongly denies
        # the owner.
        if not same_user_id(serializer.instance.created_by_id, self.request.user.id):
            raise PermissionDenied('Only the comment author can edit this comment.')
        serializer.save()

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolve a comment"""
        from django.utils import timezone
        comment = self.get_object()
        comment.is_resolved = True
        comment.resolved_by_id = request.user.id
        comment.resolved_at = timezone.now()
        comment.save()
        return Response({'status': 'resolved'})

    @action(detail=True, methods=['post'])
    def unresolve(self, request, pk=None):
        """Unresolve a comment"""
        comment = self.get_object()
        comment.is_resolved = False
        comment.resolved_by_id = None
        comment.resolved_at = None
        comment.save()
        return Response({'status': 'unresolved'})


class SearchViewSet(viewsets.ViewSet):
    """ViewSet for searching wiki content"""
    permission_classes = [IsAuthenticated, ServiceAccessPermission]

    def list(self, request):
        query = request.query_params.get('q', '')
        space_id = request.query_params.get('space')
        label_id = request.query_params.get('label')

        if not query or len(query) < 2:
            return Response([])
        # WIKI-42: bound the request BEFORE any work. An over-long or
        # many-term query is rejected safely instead of amplifying DB and
        # app-side allocation.
        if len(query) > self.MAX_QUERY_CHARS or len(query.split()) > self.MAX_QUERY_TERMS:
            return Response(
                {'detail': f'query too large (max {self.MAX_QUERY_CHARS} chars / '
                           f'{self.MAX_QUERY_TERMS} terms)'},
                status=400,
            )

        # WIKI-42: bound concurrent search work across all replicas. Excess
        # load sheds
        # with 429 instead of stacking headline/row allocations until the
        # kernel OOMKills the pod. The counter is TTL'd so a worker dying
        # mid-request self-heals instead of leaking a slot forever.
        slot = self._acquire_search_slot()
        if slot is False:
            return Response(
                {'detail': 'search is at capacity, retry shortly'},
                status=429, headers={'Retry-After': '2'},
            )
        started = time.monotonic()
        try:
            return self._search(request, query, space_id, label_id, started)
        finally:
            if slot:
                self._release_search_slot()

    def _search(self, request, query, space_id, label_id, started):
        user = request.user

        # Base queryset with access control
        # SCS-239: anonymous reads are bearer-gated at the permission layer.
        org_id = get_org_filter_for_read(request)
        if org_id is not None:
            _ensure_membership_for_read(request, org_id)
            queryset = Page.objects.filter(
                status__in=('published', 'draft'),
                space__organization_id=org_id,
            )
        else:
            member_org_ids = _user_member_org_ids(request)
            if user.is_staff or user.is_superuser:
                queryset = Page.objects.filter(status__in=('published', 'draft'))
            elif member_org_ids:
                queryset = Page.objects.filter(
                    status__in=('published', 'draft'),
                    space__organization_id__in=member_org_ids,
                )
            else:
                queryset = Page.objects.filter(
                    status='published',
                    space__visibility='public',
                )
            queryset = queryset.filter(
                Q(space__visibility__in=('org', 'public')) |
                Q(space__owner_id=user.id) |
                Q(space__memberships__user_id=user.id)
            ).distinct()

        # Apply filters
        if space_id:
            queryset = queryset.filter(space_id=space_id)

        if label_id:
            queryset = queryset.filter(labels__id=label_id)

        # Full-text search.
        #
        # WIKI-42 (prod OOM 2026-07-16, pod exit 137): the old path fetched the
        # FULL content_text AND search_vector for every hit and cut a 300-char
        # excerpt in Python — with multi-megabyte pages and concurrent audit
        # searches that materialized hundreds of MB per burst in the replica.
        # The rewrite keeps every allocation bounded:
        #   - excerpts are built DB-side (ts_headline over a bounded slice of
        #     the document) and only the bounded headline crosses the wire;
        #   - the row fetch is column-restricted via values() — content_text
        #     and search_vector NEVER enter the app process;
        #   - space fields come from the same row (no N+1); labels are batch-
        #     fetched once for the ≤MAX_RESULTS hits.
        search_query = SearchQuery(query)
        queryset = (
            queryset
            .annotate(
                rank=SearchRank('search_vector', search_query),
                excerpt_db=SearchHeadline(
                    Left('content_text', self.MAX_HEADLINE_SOURCE_CHARS),
                    search_query,
                    max_words=40, min_words=15,
                    start_sel='', stop_sel='',
                ),
                content_head=Left('content_text', self.EXCERPT_FALLBACK_CHARS),
            )
            .filter(Q(search_vector=search_query) | Q(title__icontains=query))
            .order_by('-rank', '-updated_at')
            .values(
                'id', 'title', 'slug', 'updated_at', 'rank',
                'excerpt_db', 'content_head',
                'space__key', 'space__name', 'space__organization_id',
                'verified_at',
            )[: self.MAX_RESULTS]
        )

        rows = list(queryset)
        labels_by_page = self._labels_for_pages([row['id'] for row in rows])
        results = []
        for row in rows:
            excerpt = (row['excerpt_db'] or '').strip()
            if not excerpt:
                # Title-only hits (icontains branch) have no vector match for
                # ts_headline: fall back to a BOUNDED document prefix.
                head = row['content_head'] or ''
                excerpt = self._generate_search_excerpt(head, query)
            results.append({
                'id': row['id'],
                'title': row['title'],
                'slug': row['slug'],
                'excerpt': excerpt[: self.MAX_EXCERPT_CHARS],
                'space_key': row['space__key'],
                'space_name': row['space__name'],
                'organization_id': row['space__organization_id'],
                'labels': labels_by_page.get(row['id'], []),
                'updated_at': row['updated_at'],
                'rank': row['rank'] or 0,
            })
            # WIKI-126 / SCS-239: verification badge fields on search rows —
            # populated here, OMITTED for unauthenticated callers by the
            # serializer's server-side guard (never SPA-side hiding).
            results[-1]['verified'] = row['verified_at'] is not None
            results[-1]['verified_at'] = row['verified_at']

        logger.info(
            'wiki.search terms=%d results=%d elapsed_ms=%d bounded=1',
            len(query.split()), len(results),
            int((time.monotonic() - started) * 1000),
        )
        serializer = SearchResultSerializer(results, many=True, context={'request': request})
        return Response(serializer.data)

    # WIKI-42 request bounds — every per-request allocation is capped by these.
    MAX_QUERY_CHARS = 200
    MAX_QUERY_TERMS = 12
    MAX_RESULTS = 50
    MAX_HEADLINE_SOURCE_CHARS = 60_000   # ts_headline input slice (DB-side bound)
    EXCERPT_FALLBACK_CHARS = 2_000       # bounded prefix for title-only hits
    MAX_EXCERPT_CHARS = 500
    # Keep the expensive-search cap below the request-handler capacity of ONE
    # replica (2 gthread workers x 4 threads = 8).  Otherwise connections can
    # queue in Gunicorn before Django runs this gate, turning overload into
    # client timeouts rather than prompt 429s.
    MAX_CONCURRENT_SEARCHES = 4          # shared across all replicas; excess sheds with 429
    _SEARCH_SLOT_KEY = 'wiki-search-concurrency'
    # Must exceed Gunicorn's 120s request timeout.  If the key expired while a
    # valid request was still running, its eventual release could decrement a
    # newer generation of the counter.  A dead worker still self-heals.
    _SEARCH_SLOT_TTL = 180
    _SEARCH_REDIS_URL = None             # resolved lazily from CELERY_BROKER_URL
    _search_redis_client = None

    @classmethod
    def _search_redis(cls):
        """Redis client for the shared search-slot gate.

        Deliberately uses the CELERY_BROKER_URL Redis (already a hard runtime
        dependency — celery requires it) rather than Django's cache backend,
        which defaults to process-local LocMemCache: with N gunicorn sync
        workers there would be N independent counters and the cap could never
        shed real cross-worker concurrency (revi P1 #3). Redis INCR/DECR are
        atomic, so this is a genuine shared, process-spanning semaphore.
        """
        if cls._search_redis_client is None:
            from django.conf import settings
            url = cls._SEARCH_REDIS_URL or getattr(
                settings, 'CELERY_BROKER_URL', 'redis://redis:6379/5',
            )
            import redis as redis_lib
            cls._search_redis_client = redis_lib.Redis.from_url(
                url,
                socket_connect_timeout=1.0, socket_timeout=1.0,
                decode_responses=False,
            )
        return cls._search_redis_client

    @classmethod
    def _reset_search_redis_for_tests(cls):
        cls._search_redis_client = None
        cls._SEARCH_REDIS_URL = None

    def _acquire_search_slot(self):
        """True when acquired; False when saturated or the shared gate is unavailable."""
        try:
            r = self._search_redis()
            key = self._SEARCH_SLOT_KEY
            count = r.incr(key)
            r.expire(key, self._SEARCH_SLOT_TTL)
            if count > self.MAX_CONCURRENT_SEARCHES:
                r.decr(key)
                r.expire(key, self._SEARCH_SLOT_TTL)
                logger.warning(
                    'wiki.search rejected=capacity observed_count=%d limit=%d bounded=1',
                    count, self.MAX_CONCURRENT_SEARCHES,
                )
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — reject safely; never amplify an outage
            # Once Gunicorn has enough threads to expose overload to this gate,
            # fail-open would admit every waiting FTS query during a Redis
            # outage and recreate the OOM/DB-contention class WIKI-42 fixes.
            logger.error(
                'wiki.search rejected=slot_backend_unavailable error_type=%s bounded=1',
                type(exc).__name__,
            )
            return False

    def _release_search_slot(self):
        try:
            r = self._search_redis()
            r.decr(self._SEARCH_SLOT_KEY)
            r.expire(self._SEARCH_SLOT_KEY, self._SEARCH_SLOT_TTL)
        except Exception:  # noqa: BLE001
            pass

    def _labels_for_pages(self, page_ids):
        """Batch labels for ≤MAX_RESULTS pages in ONE query (no N+1)."""
        if not page_ids:
            return {}
        from .models import Label

        by_page = {}
        for label in Label.objects.filter(pages__id__in=page_ids).values(
            'id', 'name', 'color', 'pages__id',
        ):
            by_page.setdefault(label['pages__id'], []).append(
                {'id': label['id'], 'name': label['name'], 'color': label.get('color')}
            )
        return by_page

    def _generate_search_excerpt(self, content_text, query, max_length=300):
        """Generate excerpt with context around search terms"""
        if not content_text:
            return ''

        # Normalize query for matching
        query_lower = query.lower()
        content_lower = content_text.lower()

        # Find first occurrence of any query term
        query_terms = query_lower.split()
        best_pos = -1
        for term in query_terms:
            pos = content_lower.find(term)
            if pos != -1 and (best_pos == -1 or pos < best_pos):
                best_pos = pos

        if best_pos == -1:
            # No match found, return first N chars
            return content_text[:max_length] + '...' if len(content_text) > max_length else content_text

        # Extract context around the match (150 chars before and after)
        start = max(0, best_pos - 150)
        end = min(len(content_text), best_pos + len(query) + 150)

        excerpt = content_text[start:end]

        # Add ellipsis if we truncated
        if start > 0:
            excerpt = '...' + excerpt
        if end < len(content_text):
            excerpt = excerpt + '...'

        return excerpt
