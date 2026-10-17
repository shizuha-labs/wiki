"""Custom permissions for Shizuha Wiki"""
import logging
import os

from rest_framework import permissions

logger = logging.getLogger(__name__)


def same_user_id(a, b):
    """Type-safe identity comparison for user/creator IDs.

    Federated user IDs can arrive as int (local Django User PK, or the
    int-coerced FederatedUser.id) or as str (JWT user_id claim when the
    deployed shizuha_auth does not coerce). created_by_id is always an int
    (IntegerField). Comparing them directly (`141 != "141"`) wrongly denies
    the comment owner (WIKI-81). Coerce both sides before comparing; None
    never equals anything.
    """
    if a is None or b is None:
        return False
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


class WikiPermissionService:
    """
    Centralized permission service for wiki resources.
    Role hierarchy: owner > admin > editor > viewer.
    Page creators can always edit/delete/move their own pages.
    """

    # Org-visibility spaces are org-WRITABLE by default (any org member -> editor).
    # Governance/critical spaces listed here stay org-READABLE but not org-writable
    # (org members -> 'org_member'); write needs an explicit editor membership.
    # Add a space key here to protect it without touching the rest of the model.
    ORG_READONLY_SPACE_KEYS = {'HANDBOOK'}

    # What each role can do (cumulative is NOT implied — each role lists its own actions)
    ROLE_PERMISSIONS = {
        'owner': {
            'page': ['create', 'update', 'delete', 'move'],
            'comment': ['create', 'delete'],
            'attachment': ['upload', 'delete'],
            'space': ['update', 'delete', 'manage_members'],
            'label': ['create', 'delete'],
        },
        'admin': {
            'page': ['create', 'update', 'delete', 'move'],
            'comment': ['create', 'delete'],
            'attachment': ['upload', 'delete'],
            'space': ['update', 'manage_members'],
            'label': ['create', 'delete'],
        },
        'editor': {
            'page': ['create', 'update', 'move'],
            'comment': ['create'],
            'attachment': ['upload'],
            'label': ['create'],
        },
        'viewer': {
            'comment': ['create'],
        },
    }

    # Actions that page/comment/attachment creators can perform on their own resources
    CREATOR_ACTIONS = {
        'page': ['update', 'delete', 'move'],
        'comment': ['delete'],
        'attachment': ['delete'],
    }

    JIT_ROLE_PRIORITY = {'viewer': 1, 'member': 2, 'editor': 3, 'admin': 3, 'owner': 4}

    @staticmethod
    def _jit_role_priority(role):
        return WikiPermissionService.JIT_ROLE_PRIORITY.get((role or '').lower(), 0)

    @staticmethod
    def _fetch_live_jit_scoped_grants(user):
        """
        Fetch active Admin JIT grants for this user from the source of truth.

        JIT grants are action-scoped authorisations, not org roles. They must be
        checked by the target service at request time so an already-approved
        grant works even when the caller's JWT/role projection is stale.
        """
        user_id = getattr(user, 'id', None)
        if user_id is None:
            return []
        try:
            int(user_id)
        except (TypeError, ValueError):
            return []

        try:
            import requests

            base = os.environ.get('SHIZUHA_ADMIN_API_URL') or 'http://shizuha-admin:8003/api'
            url = f"{base.rstrip('/')}/internal/users/{user_id}/memberships/"
            params = {}
            email = getattr(user, 'email', '') or ''
            if email:
                params['email'] = email
            resp = requests.get(url, params=params, timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                grants = data.get('jit_scoped_grants') or []
                return grants if isinstance(grants, list) else []
            logger.warning(
                "Admin JIT grant lookup for wiki user %s returned HTTP %s",
                user_id,
                resp.status_code,
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Admin JIT grant lookup for wiki user %s failed: %s", user_id, exc)
        return []

    @classmethod
    def _get_jit_scoped_grants(cls, user):
        cached = getattr(user, '_wiki_live_jit_scoped_grants', None)
        if cached is not None:
            return cached

        token_grants = getattr(user, 'jit_scoped_grants', None)
        if isinstance(token_grants, list):
            grants = token_grants
        else:
            grants = cls._fetch_live_jit_scoped_grants(user)

        setattr(user, '_wiki_live_jit_scoped_grants', grants)
        return grants

    @classmethod
    def _jit_scope_matches(cls, grant_scope, *, space, resource=None, resource_type=None, action_name=None):
        key = (space.key or '').upper()
        exact_space_scope = f'wiki.{resource_type}s.{action_name}:{key}'
        if grant_scope == exact_space_scope:
            return True

        if resource_type == 'page':
            page_id = getattr(resource, 'id', None)
            if page_id is not None and grant_scope == f'{exact_space_scope}:{page_id}':
                return True
        return False

    @classmethod
    def _jit_scope_applies_to_space_permissions(cls, grant_scope, *, space, resource_type, action_name):
        key = (space.key or '').upper()
        exact_space_scope = f'wiki.{resource_type}s.{action_name}:{key}'
        return grant_scope == exact_space_scope or grant_scope.startswith(f'{exact_space_scope}:')

    @classmethod
    def _has_jit_grant(cls, user, *, space, resource=None, resource_type=None, action_name=None, min_role='editor'):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        min_priority = cls._jit_role_priority(min_role)
        org_id = str(space.organization_id)
        for grant in cls._get_jit_scoped_grants(user):
            if str(grant.get('org_id')) != org_id:
                continue
            if cls._jit_role_priority(grant.get('role')) < min_priority:
                continue
            if cls._jit_scope_matches(
                grant.get('scope'),
                space=space,
                resource=resource,
                resource_type=resource_type,
                action_name=action_name,
            ):
                return True
        return False

    @staticmethod
    def get_user_role(user, space):
        """
        Returns the user's effective role in a space.
        Returns: 'owner', 'admin', 'editor', 'viewer', 'org_member', or None.
        """
        if not user or not user.is_authenticated:
            return None

        # Superusers always get owner-level access
        if getattr(user, 'is_superuser', False):
            return 'owner'

        # Space owner is always 'owner'
        if space.owner_id == user.id:
            return 'owner'

        # Org admins/owners get admin access to all org-visible spaces
        org_role = getattr(user, 'organization_role', None)
        if org_role in ('admin', 'owner') and space.visibility in ('org', 'public'):
            return 'admin'

        # Check explicit membership
        membership = space.memberships.filter(user_id=user.id).first()
        if membership:
            return membership.role

        # Org spaces: org members get implicit access. DEFAULT is WRITE (editor) —
        # any member of the space's org may edit an org-visibility space. Critical
        # spaces (governance) are listed in ORG_READONLY_SPACE_KEYS and drop org
        # members back to read-only ('org_member'); write there then requires an
        # explicit editor membership. Public spaces stay read-only for non-members.
        if space.visibility == 'org':
            readonly = (space.key or '').upper() in WikiPermissionService.ORG_READONLY_SPACE_KEYS
            return 'org_member' if readonly else 'editor'
        if space.visibility == 'public':
            return 'org_member'

        return None

    @classmethod
    def can_perform(cls, user, action, resource=None, space=None):
        """
        Check if user can perform an action like 'page:delete'.

        Args:
            user: The authenticated user
            action: String like 'page:delete', 'comment:create', etc.
            resource: The target object (Page, Comment, Attachment) — needed for creator checks
            space: The Space object (inferred from resource if not provided)
        """
        if not user or not user.is_authenticated:
            return False

        resource_type, action_name = action.split(':')

        # Resolve the space from the resource if not provided
        if space is None and resource is not None:
            if hasattr(resource, 'space'):
                space = resource.space
            elif hasattr(resource, 'page'):
                space = resource.page.space
            else:
                space = resource

        if space is None:
            return False

        role = cls.get_user_role(user, space)
        if role is None:
            return False

        # Check creator-owns-resource: creators can always edit/delete their own
        if resource is not None and resource_type in cls.CREATOR_ACTIONS:
            if action_name in cls.CREATOR_ACTIONS[resource_type]:
                created_by = getattr(resource, 'created_by_id', None)
                if created_by is not None and same_user_id(created_by, user.id):
                    return True

        # Check role-based permissions
        role_perms = cls.ROLE_PERMISSIONS.get(role, {})
        allowed_actions = role_perms.get(resource_type, [])
        if action_name in allowed_actions:
            return True

        return cls._has_jit_grant(
            user,
            space=space,
            resource=resource,
            resource_type=resource_type,
            action_name=action_name,
            min_role='editor',
        )

    @classmethod
    def get_space_permissions(cls, user, space):
        """
        Returns the user's role and full permission set for a space.
        Used by the GET /spaces/{key}/permissions/ endpoint.
        """
        role = cls.get_user_role(user, space)
        if role is None:
            return {'role': None, 'permissions': {}}

        perms = {kind: list(actions) for kind, actions in cls.ROLE_PERMISSIONS.get(role, {}).items()}
        org_id = str(space.organization_id)
        for grant in cls._get_jit_scoped_grants(user):
            if str(grant.get('org_id')) != org_id:
                continue
            if cls._jit_role_priority(grant.get('role')) < cls._jit_role_priority('editor'):
                continue
            for resource_type in ('page', 'comment', 'attachment', 'space', 'label'):
                for action_name in cls.ROLE_PERMISSIONS['owner'].get(resource_type, []):
                    if cls._jit_scope_applies_to_space_permissions(
                        grant.get('scope'),
                        space=space,
                        resource_type=resource_type,
                        action_name=action_name,
                    ):
                        perms.setdefault(resource_type, [])
                        if action_name not in perms[resource_type]:
                            perms[resource_type].append(action_name)
        return {
            'role': role,
            'permissions': perms,
        }


class WikiResourcePermission(permissions.BasePermission):
    """
    DRF permission class that delegates to WikiPermissionService.
    Maps DRF ViewSet actions to wiki permission actions.
    Subclass and set RESOURCE_TYPE to 'page', 'comment', or 'attachment'.
    """
    RESOURCE_TYPE = None
    ACTION_MAP = {
        'destroy': 'delete',
        'partial_update': 'update',
        'update': 'update',
        'create': 'create',
        'restore_version': 'update',   # restoring = modifying page content
        'sections': 'update',          # WIKI-8 section-scoped page edit
        'move': 'move',
        'reorder': 'move',
        'resolve': 'delete',           # resolve/unresolve is admin-level
        'unresolve': 'delete',
    }

    def has_object_permission(self, request, view, obj):
        action_name = self.ACTION_MAP.get(view.action)
        if action_name is None:
            return True  # Actions not in the map are allowed (list, retrieve, etc.)

        resource_type = self.RESOURCE_TYPE
        if resource_type is None:
            return True

        perm_string = f'{resource_type}:{action_name}'
        allowed = WikiPermissionService.can_perform(
            request.user, perm_string, resource=obj
        )
        if not allowed:
            role = WikiPermissionService.get_user_role(
                request.user,
                obj.space if hasattr(obj, 'space') else (obj.page.space if hasattr(obj, 'page') else obj)
            )
            self.message = (
                f"You don't have permission to {action_name} this {resource_type}. "
                f"Your role in this space: {role or 'none'}."
            )
        return allowed


class PagePermission(WikiResourcePermission):
    RESOURCE_TYPE = 'page'
    ACTION_MAP = dict(WikiResourcePermission.ACTION_MAP, **{
        # WIKI-125: verification is a content-trust write — same editor-or-admin
        # gate as editing the page itself.
        'verify': 'update',
    })


class CommentPermission(WikiResourcePermission):
    RESOURCE_TYPE = 'comment'


class AttachmentPermission(WikiResourcePermission):
    RESOURCE_TYPE = 'attachment'


class TemplatePermission(permissions.BasePermission):
    """Object-level mutation policy for templates.

    A creator may maintain their own template. Space-scoped templates otherwise
    follow the Wiki editor/admin hierarchy; org-wide/global templates require an
    org admin/owner because they affect every space in the organization.
    """

    ACTION_MAP = {
        'partial_update': 'update',
        'update': 'update',
        'destroy': 'delete',
    }

    def has_object_permission(self, request, view, obj):
        action = self.ACTION_MAP.get(view.action)
        if action is None:
            return True

        user = request.user
        if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
            return True
        if obj.created_by_id == getattr(user, 'id', None):
            return True

        memberships = getattr(user, 'organization_memberships', {}) or {}
        org_role = memberships.get(obj.organization_id) or memberships.get(str(obj.organization_id))
        if obj.space_id is None or obj.is_global:
            return org_role in ('admin', 'owner')

        role = WikiPermissionService.get_user_role(user, obj.space)
        if action == 'update':
            return role in ('owner', 'admin', 'editor')
        return role in ('owner', 'admin')


class ServiceAccessPermission(permissions.BasePermission):
    SERVICE_SLUG = 'wiki'
    message = 'You do not have access to this service.'

    def has_permission(self, request, view):
        user = request.user
        if not hasattr(user, 'enabled_services'):
            return True  # Not a federated user (e.g., Django admin)
        if user.enabled_services is None:
            return True  # Unrestricted (staff/superuser)
        return self.SERVICE_SLUG in user.enabled_services


# SCS-239: the former IsAuthenticatedOrPublicReadOnly was REMOVED — it
# allowed anonymous reads and its "public-only" queryset filtering could not
# be org-scoped for unauthenticated callers (cross-org leak, org-61 content
# served to anonymous GETs). QA target F0.1 (PLAT-7636): every data endpoint
# requires a bearer token; health only is anonymous-allowed.


def _resolve_space(obj):
    """Extract the Space from an object (Space, Page, Comment, Attachment)."""
    if hasattr(obj, 'space'):
        return obj.space
    elif hasattr(obj, 'page'):
        return obj.page.space
    return obj


def _is_superuser(user):
    """Check if user is a superuser (works for both Django User and FederatedUser)."""
    return getattr(user, 'is_superuser', False)


class IsSpaceMember(permissions.BasePermission):
    """Check if user is a member of the space"""

    def has_object_permission(self, request, view, obj):
        if _is_superuser(request.user):
            return True

        space = _resolve_space(obj)

        # Org-visible and public spaces are open to authenticated users
        if space.visibility in ('org', 'public'):
            return True

        # Owner or explicit member
        if space.owner_id == request.user.id:
            return True

        return space.memberships.filter(user_id=request.user.id).exists()


class IsSpaceAdmin(permissions.BasePermission):
    """Check if user is an admin of the space"""

    def has_object_permission(self, request, view, obj):
        if _is_superuser(request.user):
            return True

        space = _resolve_space(obj)

        if space.owner_id == request.user.id:
            return True

        # Org admins/owners get admin access to org-visible spaces
        org_role = getattr(request.user, 'organization_role', None)
        if org_role in ('admin', 'owner') and space.visibility in ('org', 'public'):
            return True

        return space.memberships.filter(user_id=request.user.id, role='admin').exists()


class IsSpaceEditor(permissions.BasePermission):
    """Check if user can edit in the space"""

    def has_object_permission(self, request, view, obj):
        if _is_superuser(request.user):
            return True

        space = _resolve_space(obj)

        if space.owner_id == request.user.id:
            return True

        # Org admins/owners get admin access (which implies editor) to org-visible spaces
        org_role = getattr(request.user, 'organization_role', None)
        if org_role in ('admin', 'owner') and space.visibility in ('org', 'public'):
            return True

        membership = space.memberships.filter(user_id=request.user.id).first()
        if membership:
            return membership.role in ['admin', 'editor']
        return False


class IsPageCreatorOrSpaceEditor(permissions.BasePermission):
    """Check if user is the page creator or a space editor"""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        if _is_superuser(request.user):
            return True

        if obj.created_by_id is not None and same_user_id(obj.created_by_id, request.user.id):
            return True

        space = _resolve_space(obj)

        if space.owner_id == request.user.id:
            return True

        # Org admins/owners get admin access (which implies editor) to org-visible spaces
        org_role = getattr(request.user, 'organization_role', None)
        if org_role in ('admin', 'owner') and space.visibility in ('org', 'public'):
            return True

        membership = space.memberships.filter(user_id=request.user.id).first()
        if membership:
            return membership.role in ['admin', 'editor']
        return False
