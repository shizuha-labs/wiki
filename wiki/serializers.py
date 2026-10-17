"""Serializers for Shizuha Wiki API"""
from rest_framework import serializers
from .models import (
    Space, SpaceMembership, Label, Page, PageVersion,
    PageComment, Attachment, PageWatch, SpaceWatch, Template
)


def _org_membership_role(user, org_id):
    memberships = getattr(user, 'organization_memberships', {}) or {}
    return memberships.get(org_id) or memberships.get(str(org_id))


def _can_create_page_in_space(user, space):
    # Staff and the space owner can always create (privileged fast-path kept).
    if user.is_staff or user.is_superuser or space.owner_id == user.id:
        return True

    # Explicit space membership admin/editor can create.
    explicit = space.memberships.filter(user_id=user.id, role__in=('admin', 'editor')).exists()
    if explicit:
        return True

    # Cross-org outsiders (no membership in the space's org) are denied — the
    # org-membership check below must not be bypassed.
    org_role = _org_membership_role(user, space.organization_id)
    if org_role in ('admin', 'owner'):
        return space.visibility in ('org', 'public')

    if space.visibility == 'org' and org_role:
        # PLAT-5027: gate create by the SAME space ACL as update/delete.
        # Previously ANY org member could create in an org-visible space, so a
        # principal with permissions:{} (org_member in an ORG_READONLY space like
        # HANDBOOK) could create pages it could never edit or delete — degrading
        # the mandated UPSERT to insert-only. Delegate to the canonical
        # permission service so create/update/delete agree on the space
        # permission map (role-based perms + JIT grants).
        from .permissions import WikiPermissionService
        return WikiPermissionService.can_perform(user, 'page:create', space=space)

    # Public spaces are readable by non-members, but not world-writable. A
    # caller needs owner/admin/editor (or org admin/owner above) to create pages.
    return False


class LabelSerializer(serializers.ModelSerializer):
    pages_count = serializers.SerializerMethodField()

    class Meta:
        model = Label
        fields = ['id', 'organization_id', 'name', 'color', 'description', 'pages_count', 'created_at']
        read_only_fields = ['id', 'organization_id', 'created_at']

    def get_pages_count(self, obj):
        return obj.pages.count()


class SpaceMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpaceMembership
        fields = ['id', 'space', 'user_id', 'role', 'created_at', 'created_by_id']
        read_only_fields = ['id', 'created_at', 'created_by_id']


class SpaceListSerializer(serializers.ModelSerializer):
    pages_count = serializers.SerializerMethodField()
    members_count = serializers.SerializerMethodField()

    class Meta:
        model = Space
        fields = [
            'id', 'organization_id', 'key', 'name', 'description', 'space_type',
            'visibility', 'icon', 'color', 'is_archived', 'pages_count',
            'members_count', 'created_at', 'updated_at'
        ]

    def get_pages_count(self, obj):
        return obj.pages.filter(status='published').count()

    def get_members_count(self, obj):
        return obj.memberships.count()


class SpaceDetailSerializer(serializers.ModelSerializer):
    pages_count = serializers.SerializerMethodField()
    members_count = serializers.SerializerMethodField()
    memberships = SpaceMembershipSerializer(many=True, read_only=True)

    class Meta:
        model = Space
        fields = [
            'id', 'organization_id', 'key', 'name', 'description', 'space_type',
            'visibility', 'icon', 'color', 'logo', 'homepage_id', 'owner_id',
            'is_archived', 'pages_count', 'members_count', 'memberships',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'organization_id', 'owner_id', 'created_at', 'updated_at']

    def get_pages_count(self, obj):
        return obj.pages.filter(status='published').count()

    def get_members_count(self, obj):
        return obj.memberships.count()


class SpaceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Space
        # id/organization_id/created_at are read-only so the CREATE response body
        # returns them (clients need the new space's id) — mirrors PageCreateSerializer.
        fields = ['id', 'organization_id', 'key', 'name', 'description',
                  'space_type', 'visibility', 'icon', 'color', 'created_at']
        read_only_fields = ['id', 'organization_id', 'created_at']

    def validate_key(self, value):
        # Ensure key is uppercase and alphanumeric
        value = value.upper()
        if not value.isalnum():
            raise serializers.ValidationError("Key must be alphanumeric")
        return value




class LabelUsageSerializer(LabelSerializer):
    pages_count = serializers.IntegerField(read_only=True)

    class Meta(LabelSerializer.Meta):
        fields = LabelSerializer.Meta.fields + ['pages_count']


class PageListSerializer(serializers.ModelSerializer):
    space_key = serializers.CharField(source='space.key', read_only=True)
    space_name = serializers.CharField(source='space.name', read_only=True)
    organization_id = serializers.IntegerField(source='space.organization_id', read_only=True)
    labels = LabelSerializer(many=True, read_only=True)
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            'id', 'space', 'space_key', 'space_name', 'organization_id',
            'parent', 'title', 'slug', 'status', 'version', 'labels',
            'position', 'view_count', 'children_count', 'created_by_id',
            'created_at', 'updated_at'
        ]

    def get_children_count(self, obj):
        return obj.children.count()


class PageDetailSerializer(serializers.ModelSerializer):
    space_key = serializers.CharField(source='space.key', read_only=True)
    space_name = serializers.CharField(source='space.name', read_only=True)
    organization_id = serializers.IntegerField(source='space.organization_id', read_only=True)
    labels = LabelSerializer(many=True, read_only=True)
    label_ids = serializers.PrimaryKeyRelatedField(
        queryset=Label.objects.all(), many=True, write_only=True,
        source='labels', required=False
    )
    breadcrumbs = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    attachments_count = serializers.SerializerMethodField()
    verify_owner = serializers.IntegerField(source='verify_owner_id', read_only=True)
    verified_by = serializers.IntegerField(source='verified_by_id', read_only=True)
    verified_at = serializers.DateTimeField(read_only=True)
    verified = serializers.SerializerMethodField()

    def get_verified(self, obj):
        return obj.verified_at is not None

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request is not None else None
        if user is None or not getattr(user, 'is_authenticated', False):
            # WIKI-124 + SCS-239: verification metadata never renders on
            # anonymous read paths — server-side field omission, not SPA hiding.
            for _name in ('verify_owner', 'verified_by', 'verified_at', 'verified'):
                fields.pop(_name, None)
        return fields

    class Meta:
        model = Page
        fields = [
            'id', 'space', 'space_key', 'space_name', 'organization_id',
            'parent', 'title', 'slug', 'content_json', 'content_text',
            'status', 'version', 'verified', 'verify_owner', 'verified_by', 'verified_at',
            'labels', 'label_ids',
            'position', 'is_restricted', 'view_count', 'breadcrumbs',
            'children_count', 'comments_count', 'attachments_count',
            'created_by_id', 'updated_by_id', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'version', 'view_count', 'created_by_id', 'created_at', 'updated_at']

    def get_breadcrumbs(self, obj):
        return obj.breadcrumbs

    def get_children_count(self, obj):
        return obj.children.count()

    def get_comments_count(self, obj):
        return obj.comments.count()

    def get_attachments_count(self, obj):
        return obj.attachments.count()


class PageCreateSerializer(serializers.ModelSerializer):
    space_key = serializers.CharField(source='space.key', read_only=True)
    organization_id = serializers.IntegerField(source='space.organization_id', read_only=True)
    input_space_key = serializers.CharField(write_only=True, required=False, source='_input_space_key')
    labels = LabelSerializer(many=True, read_only=True)
    label_ids = serializers.PrimaryKeyRelatedField(
        queryset=Label.objects.all(), many=True, write_only=True,
        source='labels', required=False
    )
    template_id = serializers.UUIDField(write_only=True, required=False)

    class Meta:
        model = Page
        fields = [
            'id', 'space', 'space_key', 'organization_id', 'input_space_key',
            'parent', 'title', 'slug',
            'content_json', 'content_text', 'template_id', 'status', 'labels', 'label_ids',
            'position', 'is_restricted'
        ]
        read_only_fields = ['id', 'slug', 'organization_id']
        extra_kwargs = {
            'space': {'required': False}
        }

    def validate(self, attrs):
        template_id = attrs.pop('template_id', None)
        if template_id is not None:
            supplied_content = {
                field for field in ('content_json', 'content_text')
                if field in self.initial_data
            }
            if supplied_content:
                raise serializers.ValidationError({
                    'template_id': (
                        'template_id is mutually exclusive with content_json/content_text; '
                        'the server copies the canonical template content.'
                    ),
                })
            # This is consumed by PageViewSet.perform_create after the target
            # space has passed the normal page-create authorization checks.
            self._template_id = template_id

        # If input_space_key is provided, resolve it to space
        space_key = attrs.pop('_input_space_key', None)
        if space_key and not attrs.get('space'):
            from .models import Space
            try:
                space = Space.objects.get(key__iexact=space_key)
                attrs['space'] = space
            except Space.DoesNotExist:
                raise serializers.ValidationError({'space_key': f"Space with key '{space_key}' not found"})

        # Ensure we have a space
        if not attrs.get('space'):
            raise serializers.ValidationError({'space': 'Either space or space_key is required'})

        # Validate user has WRITE access to the target space. Public spaces are
        # read-only for non-members (WikiPermissionService returns org_member),
        # so they must not be writable-by-any-authenticated-user by UUID.
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            space = attrs['space']
            user = request.user
            if not _can_create_page_in_space(user, space):
                raise serializers.ValidationError({'space': 'You do not have permission to create pages in this space'})

        parent = attrs.get('parent')
        if parent is not None and parent.space_id != attrs['space'].id:
            raise serializers.ValidationError({
                'parent': 'Parent page must belong to the same space.'
            })

        return attrs


class PageVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PageVersion
        fields = [
            'id', 'page', 'version_number', 'title', 'content_json',
            'content_text', 'change_message', 'created_by_id', 'created_at'
        ]
        read_only_fields = ['id', 'page', 'version_number', 'created_by_id', 'created_at']


class PageCommentSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()
    # WIKI-53: expose the author surface. The MCP reads author_email/author_id
    # to render the comment author; created_by_id alone left it "Unknown".
    author_id = serializers.IntegerField(source='created_by_id', read_only=True)

    class Meta:
        model = PageComment
        fields = [
            'id', 'page', 'parent', 'content', 'is_inline',
            'selection_start', 'selection_end', 'is_resolved',
            'resolved_by_id', 'resolved_at', 'created_by_id',
            'author_id', 'created_at', 'updated_at', 'replies', 'replies_count'
        ]
        read_only_fields = ['id', 'created_by_id', 'author_id', 'created_at', 'updated_at']

    def get_replies(self, obj):
        if obj.parent is None:  # Only get replies for top-level comments
            replies = obj.replies.all()[:5]  # Limit to 5 replies inline
            return PageCommentSerializer(replies, many=True).data
        return []

    def get_replies_count(self, obj):
        return obj.replies.count()


class AttachmentSerializer(serializers.ModelSerializer):
    organization_id = serializers.IntegerField(source='page.space.organization_id', read_only=True)

    class Meta:
        model = Attachment
        fields = [
            'id', 'page', 'organization_id', 'file', 'filename', 'file_size',
            'sha256', 'integrity_state', 'storage_version_id',
            'supersedes_attachment_id', 'mime_type', 'created_by_id', 'created_at'
        ]
        read_only_fields = [
            'id', 'organization_id', 'filename', 'file_size', 'sha256',
            'integrity_state', 'storage_version_id', 'supersedes_attachment_id',
            'mime_type', 'created_by_id', 'created_at',
        ]


class TemplateSerializer(serializers.ModelSerializer):
    space_name = serializers.CharField(source='space.name', read_only=True)
    content_text = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )

    class Meta:
        model = Template
        fields = [
            'id', 'organization_id', 'space', 'space_name', 'name', 'description',
            'icon', 'content_json', 'content_text', 'is_global', 'created_by_id',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'organization_id', 'created_by_id', 'created_at', 'updated_at']


class PageTreeSerializer(serializers.ModelSerializer):
    """Serializer for page tree/hierarchy view with depth limiting"""
    children = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = ['id', 'title', 'slug', 'status', 'position', 'children']

    def get_children(self, obj):
        # Get depth from context, default to 0 if not set
        current_depth = self.context.get('current_depth', 0)
        max_depth = self.context.get('max_depth', 5)

        # Stop recursion if we've reached max depth
        if current_depth >= max_depth:
            return []

        # Get children with same filter logic as tree endpoint
        request = self.context.get('request')
        from django.db.models import Q

        page_filter = Q(status='published')
        if request and request.user.is_authenticated:
            page_filter = page_filter | Q(created_by_id=request.user.id)

        children = obj.children.filter(page_filter).order_by('position', 'title')

        # Recursively serialize with incremented depth
        return PageTreeSerializer(
            children,
            many=True,
            context={**self.context, 'current_depth': current_depth + 1}
        ).data


class MovePageSerializer(serializers.Serializer):
    space = serializers.UUIDField(required=False)
    parent = serializers.UUIDField(required=False, allow_null=True)
    position = serializers.IntegerField(required=False, default=0)


class ReorderSerializer(serializers.Serializer):
    page_ids = serializers.ListField(child=serializers.UUIDField())


class SearchResultSerializer(serializers.Serializer):
    """Serializer for search results.

    WIKI-42: labels are pre-shaped as bounded plain dicts (id/name/color — the
    only fields the search UI renders) by the view's batch fetch, so this uses
    a plain DictField list rather than the full LabelSerializer. That keeps the
    search response free of per-label ModelSerializer materialization and lets
    the view fetch labels for all hits in a single query."""
    id = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()
    excerpt = serializers.CharField()
    space_key = serializers.CharField()
    space_name = serializers.CharField()
    organization_id = serializers.IntegerField(required=False)
    labels = serializers.ListField(child=serializers.DictField(), required=False)
    updated_at = serializers.DateTimeField()
    rank = serializers.FloatField(required=False)
