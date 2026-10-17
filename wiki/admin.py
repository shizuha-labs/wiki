"""Admin configuration for Shizuha Wiki"""
from django.contrib import admin
from .models import (
    Space, SpaceMembership, Label, Page, PageVersion,
    PageComment, Attachment, AttachmentDeletionIntent, PageWatch, SpaceWatch, Template,
    UserPreference,
)


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user_id', 'updated_at']
    search_fields = ['user_id']


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ['key', 'name', 'space_type', 'visibility', 'is_archived', 'created_at']
    list_filter = ['space_type', 'visibility', 'is_archived']
    search_fields = ['key', 'name', 'description']
    ordering = ['name']


@admin.register(SpaceMembership)
class SpaceMembershipAdmin(admin.ModelAdmin):
    list_display = ['space', 'user_id', 'role', 'created_at']
    list_filter = ['role']


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ['name', 'color', 'organization_id', 'created_at']
    search_fields = ['name']


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ['title', 'space', 'status', 'version', 'view_count', 'created_at', 'updated_at']
    list_filter = ['status', 'space']
    search_fields = ['title', 'content_text']
    ordering = ['-updated_at']


@admin.register(PageVersion)
class PageVersionAdmin(admin.ModelAdmin):
    list_display = ['page', 'version_number', 'created_by_id', 'created_at']
    list_filter = ['page']
    ordering = ['-created_at']


@admin.register(PageComment)
class PageCommentAdmin(admin.ModelAdmin):
    list_display = ['page', 'is_inline', 'is_resolved', 'created_by_id', 'created_at']
    list_filter = ['is_inline', 'is_resolved']


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'page', 'file_size', 'mime_type', 'created_at']
    list_filter = ['mime_type']


@admin.register(AttachmentDeletionIntent)
class AttachmentDeletionIntentAdmin(admin.ModelAdmin):
    list_display = [
        'object_name', 'attachment_id', 'batch_id', 'attempts',
        'completed_at', 'created_at',
    ]
    list_filter = ['completed_at']
    search_fields = ['object_name', 'attachment_id', 'batch_id']
    readonly_fields = [
        'id', 'batch_id', 'attachment_id', 'page_id', 'object_name', 'attempts',
        'last_error', 'created_at', 'updated_at', 'completed_at',
    ]



@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'space', 'is_global', 'created_at']
    list_filter = ['is_global']
