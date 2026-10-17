"""
Shizuha Wiki Models - Team Documentation and Knowledge Management

Key concepts:
- Space: A collection of pages (like a Confluence space)
- Page: A wiki document with rich content
- PageVersion: Version history for pages
- PageComment: Comments on pages
- PageLabel: Labels/tags for categorization
- Attachment: Files attached to pages
"""
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from django.utils.text import slugify


class Space(models.Model):
    """
    A Space is a container for wiki pages, similar to Confluence spaces.
    Spaces can be organization-wide or team-specific.
    """
    SPACE_TYPES = [
        ('documentation', 'Documentation'),
        ('knowledge_base', 'Knowledge Base'),
        ('project', 'Project'),
        ('team', 'Team'),
        ('personal', 'Personal'),
    ]

    VISIBILITY_CHOICES = [
        ('private', 'Private'),  # Only explicitly added members
        ('org', 'Organization'),  # All authenticated org members
        ('public', 'Public'),  # Anyone, including anonymous users
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.IntegerField(db_index=True, help_text="Organization ID from Shizuha Admin")

    key = models.CharField(max_length=10, help_text="Short unique key like 'ENG', 'HR'")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    space_type = models.CharField(max_length=20, choices=SPACE_TYPES, default='documentation')
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='org')

    icon = models.CharField(max_length=50, blank=True, help_text="Icon identifier")
    color = models.CharField(max_length=7, default='#6366f1', help_text="Hex color code")
    logo = models.ImageField(upload_to='space_logos/', blank=True, null=True)

    homepage_id = models.UUIDField(null=True, blank=True, help_text="ID of the homepage page")

    owner_id = models.IntegerField(help_text="User ID from Shizuha ID")

    priority = models.IntegerField(default=5, help_text="Weight for the freshness review queue ranking (space-admin settable)")

    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['organization_id', 'key']
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization_id', 'is_archived']),
        ]

    def __str__(self):
        return f"{self.key} - {self.name}"


class UserPreference(models.Model):
    """Personal wiki UI settings for one Shizuha ID account (not a browser)."""
    user_id = models.IntegerField(primary_key=True, help_text="Shizuha ID user id")
    diagrams = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"UserPreference({self.user_id})"


class SpaceMembership(models.Model):
    """Members of a space with their roles"""
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('editor', 'Editor'),
        ('viewer', 'Viewer'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='memberships')
    user_id = models.IntegerField(help_text="User ID from Shizuha ID")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by_id = models.IntegerField(null=True)

    class Meta:
        unique_together = ['space', 'user_id']


class Label(models.Model):
    """Labels for categorizing pages across spaces"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.IntegerField(db_index=True)

    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default='#6366f1')
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['organization_id', 'name']
        ordering = ['name']

    def __str__(self):
        return self.name


class Page(models.Model):
    """
    A wiki page with rich content.
    Pages are hierarchical (parent-child relationships).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='pages')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, blank=True)

    # Content stored as TipTap JSON
    content_json = models.JSONField(default=dict, help_text="TipTap JSON content")
    # Plain text for search
    content_text = models.TextField(blank=True, help_text="Plain text content for search")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    version = models.PositiveIntegerField(default=1)

    # Labels
    labels = models.ManyToManyField(Label, blank=True, related_name='pages')

    # Metadata
    position = models.PositiveIntegerField(default=0, help_text="Order within parent")
    is_restricted = models.BooleanField(default=False, help_text="Requires explicit permission")

    # Stats
    view_count = models.PositiveIntegerField(default=0)

    # Verification state (WIKI-124). User refs are Shizuha ID integers — this
    # app has no local User model (see created_by_id / Space.owner_id).
    verify_owner_id = models.IntegerField(null=True, blank=True, help_text="Accountable user for re-verification (Shizuha ID). Defaults to the verifier on first verify.")
    verified_by_id = models.IntegerField(null=True, blank=True, help_text="User who performed the last verification (Shizuha ID).")
    verified_at = models.DateTimeField(null=True, blank=True, help_text="When the last verification happened. NULL = unverified.")

    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)

    # Audit fields
    created_by_id = models.IntegerField(help_text="User ID from Shizuha ID")
    updated_by_id = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['space', 'slug']
        ordering = ['position', 'title']
        indexes = [
            GinIndex(fields=['search_vector']),
            models.Index(fields=['space', 'status']),
            models.Index(fields=['space', 'parent']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        """WIKI-38: hierarchy is always same-space; cross-space parents are corrupt."""
        super().clean()
        if self.parent_id is not None:
            parent_space_id = self.parent.space_id if getattr(self, 'parent', None) is not None else None
            if parent_space_id is None:
                parent_space_id = (
                    type(self).objects.filter(pk=self.parent_id)
                    .values_list('space_id', flat=True)
                    .first()
                )
            if parent_space_id is not None and parent_space_id != self.space_id:
                raise ValidationError({
                    'parent': 'Parent page must belong to the same space.'
                })

    @staticmethod
    def verification_auto_clear_kwargs(new_content_text, new_content_json, old_content_text, old_content_json):
        """WIKI-124: verification auto-clear is a transaction invariant, not convention.

        ANY byte change to content_text/content_json — on either write path
        (whole-page perform_update or the sections action) — clears all three
        verification fields in the same transaction that writes the new
        version. Byte-identical writes (WIKI-50 no-diff skip) and title-only
        edits preserve verification. A content_json shape change that projects
        identical Markdown still clears: the comparison is on stored bytes
        (WIKI-93 rule). Returns serializer.save() kwargs so the clear lands in
        the same UPDATE statement as the content write.
        """
        if new_content_text != old_content_text or new_content_json != old_content_json:
            return {'verified_at': None, 'verified_by_id': None, 'verify_owner_id': None}
        return {}

    def save(self, *args, **kwargs):
        # Fail closed on cross-space parent edges (WIKI-38). full_clean is not
        # always called by DRF/serializers; enforce here for ORM writes too.
        if self.parent_id is not None:
            self.clean()
        if not self.slug:
            base_slug = slugify(self.title)[:450]
            slug = base_slug
            counter = 1
            while Page.objects.filter(space=self.space, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def breadcrumbs(self):
        """Get the page hierarchy as breadcrumbs"""
        breadcrumbs = []
        current = self
        while current:
            breadcrumbs.insert(0, {'id': str(current.id), 'title': current.title, 'slug': current.slug})
            current = current.parent
        return breadcrumbs


class PageVersion(models.Model):
    """Version history for wiki pages"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='versions')

    version_number = models.PositiveIntegerField()
    title = models.CharField(max_length=500)
    content_json = models.JSONField(default=dict)
    content_text = models.TextField(blank=True)

    change_message = models.TextField(blank=True, help_text="Description of changes")

    created_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['page', 'version_number']
        ordering = ['-version_number']

    def __str__(self):
        return f"{self.page.title} v{self.version_number}"


class PublicationSnapshot(models.Model):
    """Immutable, idempotent publication head/section-hash snapshot.

    Wiki owns the source-publication linearization point.  Pulse supplies one
    operation key and an expected ordered tuple; a matching replay receives the
    original row while a payload-changing replay is rejected by the service.
    There is deliberately no update/delete API for this audit object.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation_key = models.CharField(max_length=128, unique=True)
    request_digest = models.CharField(max_length=64)
    snapshot_digest = models.CharField(max_length=64, db_index=True)
    organization_id = models.IntegerField(db_index=True)
    publication_result = models.CharField(max_length=100)
    page_tuples = models.JSONField(default=list)
    created_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wiki_publication_snapshot'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization_id', '-created_at']),
        ]

    def __str__(self):
        return f"publication snapshot {self.id} ({self.operation_key})"


class PageComment(models.Model):
    """Comments on wiki pages - can be inline or at page level"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='comments')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

    content = models.TextField()

    # For inline comments
    is_inline = models.BooleanField(default=False)
    selection_start = models.PositiveIntegerField(null=True, blank=True)
    selection_end = models.PositiveIntegerField(null=True, blank=True)

    is_resolved = models.BooleanField(default=False)
    resolved_by_id = models.IntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment on {self.page.title} by {self.created_by_id}"


def attachment_upload_to(instance, filename):
    """Return a globally non-reusable object key for a new attachment.

    Deletion intents may outlive their attachment metadata.  Including the
    attachment's immutable UUID prevents a later upload with the same user
    filename from ever claiming an object key still referenced by an older
    pending intent.
    """
    safe_filename = PurePosixPath(str(filename).replace('\\', '/')).name
    return f'wiki_attachments/{instance.id}/{safe_filename}'


class Attachment(models.Model):
    """File attachments for wiki pages"""
    INTEGRITY_VERIFIED = 'verified'
    INTEGRITY_UNVERIFIED_LEGACY = 'unverified_legacy'
    INTEGRITY_QUARANTINED = 'quarantined'
    INTEGRITY_MISSING = 'missing'
    INTEGRITY_CHOICES = [
        (INTEGRITY_VERIFIED, 'Verified'),
        (INTEGRITY_UNVERIFIED_LEGACY, 'Unverified legacy'),
        (INTEGRITY_QUARANTINED, 'Quarantined'),
        (INTEGRITY_MISSING, 'Missing'),
    ]
    IMMUTABLE_IDENTITY_FIELDS = (
        'id', 'file', 'file_size', 'sha256', 'mime_type',
        'storage_version_id', 'supersedes_attachment',
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='attachments')

    file = models.FileField(upload_to=attachment_upload_to, max_length=1024)
    filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    mime_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64, blank=True, default='')
    integrity_state = models.CharField(
        max_length=24,
        choices=INTEGRITY_CHOICES,
        default=INTEGRITY_UNVERIFIED_LEGACY,
        db_index=True,
    )
    storage_version_id = models.CharField(max_length=255, blank=True, default='')
    supersedes_attachment = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='replacement_attachments',
    )

    created_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=models.Q(
                    integrity_state__in=[
                        'verified',
                        'unverified_legacy',
                        'quarantined',
                        'missing',
                    ],
                ),
                name='wiki_attachment_integrity_state_valid',
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(integrity_state='verified')
                    | models.Q(sha256__regex=r'^[0-9a-f]{64}$')
                ),
                name='wiki_verified_attachment_has_sha256',
            ),
        ]

    def save(self, *args, **kwargs):
        """Reject ordinary ORM attempts to repoint committed identity.

        The PostgreSQL trigger installed by migration 0006 is authoritative and
        also covers queryset updates and raw SQL.  This guard gives callers a
        useful error before reaching that boundary.
        """
        if not self._state.adding and self.pk:
            current = type(self).objects.only(*self.IMMUTABLE_IDENTITY_FIELDS).get(pk=self.pk)
            changed = []
            for field_name in self.IMMUTABLE_IDENTITY_FIELDS:
                if field_name == 'supersedes_attachment':
                    old_value = current.supersedes_attachment_id
                    new_value = self.supersedes_attachment_id
                else:
                    old_value = getattr(current, field_name)
                    new_value = getattr(self, field_name)
                if field_name == 'file':
                    old_value = old_value.name
                    new_value = new_value.name
                if old_value != new_value:
                    changed.append(field_name)
            if changed:
                raise ValidationError({
                    'attachment_identity': (
                        'Committed attachment identity is immutable; changed: '
                        + ', '.join(changed)
                    ),
                })
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.filename


class AttachmentIntegrityTrustRoot(models.Model):
    """Independent evidence authorizing one legacy attachment promotion.

    The PostgreSQL attachment trigger requires a matching row before it will
    accept ``unverified_legacy -> verified``.  Keeping the evidence in its own
    immutable row means a bulk/queryset/raw-SQL update cannot self-promote the
    bytes merely by copying a digest calculated from the current object.
    """

    TYPE_RECOVERY_MANIFEST = 'recovery_manifest'
    TYPE_SIGNED_UPSTREAM = 'signed_upstream'
    TYPE_OPERATOR_ATTESTATION = 'operator_attestation'
    TYPE_CHOICES = [
        (TYPE_RECOVERY_MANIFEST, 'Recovery manifest'),
        (TYPE_SIGNED_UPSTREAM, 'Signed upstream'),
        (TYPE_OPERATOR_ATTESTATION, 'Operator attestation'),
    ]

    attachment = models.OneToOneField(
        Attachment,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='integrity_trust_root',
    )
    trust_root_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    source_record = models.CharField(max_length=1024)
    expected_size = models.PositiveBigIntegerField()
    expected_sha256 = models.CharField(max_length=64)
    expected_storage_version_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(trust_root_type__in=[
                    'recovery_manifest',
                    'signed_upstream',
                    'operator_attestation',
                ]),
                name='wiki_attachment_trust_root_type_valid',
            ),
            models.CheckConstraint(
                check=models.Q(expected_sha256__regex=r'^[0-9a-f]{64}$'),
                name='wiki_attachment_trust_root_sha256_valid',
            ),
            models.CheckConstraint(
                check=~models.Q(source_record=''),
                name='wiki_attachment_trust_root_source_present',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Attachment integrity trust roots are immutable.')
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.attachment_id}: {self.trust_root_type}'


class AttachmentUploadIntent(models.Model):
    """Crash-safe upload state recorded before object-store mutation."""

    STATE_CREATED = 'created'
    STATE_WRITING = 'writing'
    STATE_VERIFYING = 'verifying'
    STATE_COMMITTING = 'committing'
    STATE_CLEANUP_CLAIMED = 'cleanup_claimed'
    STATE_COMMITTED = 'committed'
    STATE_FAILED = 'failed'
    STATE_CHOICES = [
        (STATE_CREATED, 'Created'),
        (STATE_WRITING, 'Writing'),
        (STATE_VERIFYING, 'Verifying'),
        (STATE_COMMITTING, 'Committing'),
        (STATE_CLEANUP_CLAIMED, 'Cleanup claimed'),
        (STATE_COMMITTED, 'Committed'),
        (STATE_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment_id = models.UUIDField(unique=True, db_index=True)
    page_id = models.UUIDField(db_index=True)
    object_name = models.CharField(max_length=1024, unique=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_CREATED, db_index=True)
    byte_size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default='')
    storage_version_id = models.CharField(max_length=255, blank=True, default='')
    error_code = models.CharField(max_length=64, blank=True, default='')
    last_error = models.TextField(blank=True, default='')
    expires_at = models.DateTimeField(db_index=True)
    cleanup_event_name = models.CharField(max_length=255, unique=True)
    cleanup_claimed_at = models.DateTimeField(null=True, blank=True)
    cleanup_completed_at = models.DateTimeField(null=True, blank=True)
    cleanup_attempts = models.PositiveIntegerField(default=0)
    cleanup_last_attempt_at = models.DateTimeField(null=True, blank=True)
    cleanup_last_error = models.TextField(blank=True, default='')
    cleanup_terminal_failure_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(
                fields=['state', 'expires_at'],
                name='wiki_attach_state_901ea0_idx',
            ),
        ]

    def __str__(self):
        return f'{self.attachment_id} ({self.state})'


class AttachmentDeletionIntent(models.Model):
    """Durable outbox obligation for deleting attachment bytes.

    Attachment metadata and its corresponding intent are committed in the same
    PostgreSQL transaction.  Object-store mutation happens only after commit;
    a failed attempt leaves this row pending for the periodic retry worker.
    Completed rows are retained as an audit trail.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    attachment_id = models.UUIDField(db_index=True)
    page_id = models.UUIDField(db_index=True)
    object_name = models.CharField(max_length=1024)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['object_name'],
                condition=models.Q(completed_at__isnull=True),
                name='wiki_unique_pending_attachment_object_delete',
            ),
        ]
        indexes = [
            models.Index(fields=['completed_at', 'created_at']),
        ]

    def __str__(self):
        state = 'complete' if self.completed_at else 'pending'
        return f'{self.object_name} ({state})'


class PageWatch(models.Model):
    """Users watching pages for updates"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='watchers')
    user_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['page', 'user_id']


class SpaceWatch(models.Model):
    """Users watching entire spaces for updates"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='watchers')
    user_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['space', 'user_id']


class PageLink(models.Model):
    """Track internal links between pages for backlinks"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='outgoing_links')
    target_page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='incoming_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['source_page', 'target_page']


class Template(models.Model):
    """Page templates for common document types"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.IntegerField(db_index=True)
    space = models.ForeignKey(Space, on_delete=models.CASCADE, null=True, blank=True, related_name='templates',
                              help_text="If null, template is org-wide")

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)

    # Keep the canonical author-supplied source alongside the render document.
    # Agent-authored templates are usually Markdown/plain text; discarding that
    # source made a later page instantiation impossible to round-trip exactly.
    content_json = models.JSONField(default=dict)
    content_text = models.TextField(blank=True)

    is_global = models.BooleanField(default=False, help_text="Available across all spaces")

    created_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
