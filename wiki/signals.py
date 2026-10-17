"""Signal handlers for Shizuha Wiki."""
from django.db.models import QuerySet
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.postgres.search import SearchVector
from .attachment_deletion import enqueue_attachment_deletions
from .models import Attachment, Page, Space


@receiver(post_save, sender=Page)
def update_search_vector(sender, instance, **kwargs):
    """Update search vector when page is saved"""
    # Use raw SQL update to avoid recursion
    Page.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('title', weight='A') + SearchVector('content_text', weight='B')
    )


def _root_queryset(origin, model):
    return isinstance(origin, QuerySet) and origin.model is model


@receiver(pre_delete, sender=Space)
def enqueue_space_attachment_objects(sender, instance, origin=None, **kwargs):
    """Collect a Space cascade's complete object-key set in one outbox insert."""
    spaces = origin if _root_queryset(origin, Space) else Space.objects.filter(pk=instance.pk)
    enqueue_attachment_deletions(
        Attachment.objects.filter(page__space__in=spaces).only('id', 'page_id', 'file')
    )


@receiver(pre_delete, sender=Page)
def enqueue_page_attachment_objects(sender, instance, origin=None, **kwargs):
    """Collect a Page cascade's complete object-key set in one outbox insert."""
    pages = origin if _root_queryset(origin, Page) else Page.objects.filter(pk=instance.pk)
    enqueue_attachment_deletions(
        Attachment.objects.filter(page__in=pages).only('id', 'page_id', 'file')
    )


@receiver(pre_delete, sender=Attachment)
def enqueue_direct_attachment_object(sender, instance, origin=None, **kwargs):
    """Persist a direct or otherwise-uncovered attachment deletion obligation."""
    if isinstance(origin, Space):
        enqueue_attachment_deletions(
            Attachment.objects.filter(page__space=origin).only('id', 'page_id', 'file')
        )
    elif _root_queryset(origin, Space):
        enqueue_attachment_deletions(
            Attachment.objects.filter(page__space__in=origin).only('id', 'page_id', 'file')
        )
    elif isinstance(origin, Page):
        enqueue_attachment_deletions(
            Attachment.objects.filter(page=origin).only('id', 'page_id', 'file')
        )
    elif _root_queryset(origin, Page):
        enqueue_attachment_deletions(
            Attachment.objects.filter(page__in=origin).only('id', 'page_id', 'file')
        )
    elif _root_queryset(origin, Attachment):
        enqueue_attachment_deletions(origin.only('id', 'page_id', 'file'))
    else:
        enqueue_attachment_deletions([instance])
