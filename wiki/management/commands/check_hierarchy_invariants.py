"""WIKI-38: detect cross-space parent edges (page.space_id != parent.space_id)."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F


class Command(BaseCommand):
    help = (
        'Fail if any Page has a parent in a different space. '
        'Hierarchy is always same-space (WIKI-38 / architecture disposition).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Max offending rows to print (default 50).',
        )

    def handle(self, *args, **options):
        from wiki.models import Page

        qs = (
            Page.objects.filter(parent__isnull=False)
            .exclude(space_id=F('parent__space_id'))
            .select_related('space', 'parent', 'parent__space')
            .order_by('id')
        )
        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS('hierarchy invariants OK (0 cross-space parent edges)'))
            return

        limit = options['limit']
        self.stdout.write(self.style.ERROR(f'cross-space parent edges: {total}'))
        for page in qs[:limit]:
            parent = page.parent
            self.stdout.write(
                f'  page={page.id} space={page.space_id} ({getattr(page.space, "name", "?")}) '
                f'parent={parent.id} parent_space={parent.space_id} '
                f'({getattr(parent.space, "name", "?")}) title={page.title!r}'
            )
        if total > limit:
            self.stdout.write(f'  ... and {total - limit} more')
        raise CommandError(
            f'{total} cross-space parent edge(s) violate same-space hierarchy (WIKI-38)'
        )
