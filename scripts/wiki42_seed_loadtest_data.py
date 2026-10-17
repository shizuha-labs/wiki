"""WIKI-42 load-test seeder — production-shaped search corpus.

Creates a PUBLIC space with a corpus that mirrors what OOMKilled the prod
replica on 2026-07-16: mostly ordinary pages plus a heavy tail of multi-MB
documents, all with populated search vectors, so anonymous /api/search/
requests exercise the exact FTS + headline path under load.

Run inside the app container:
    python scripts/wiki42_seed_loadtest_data.py

Idempotent: re-running clears and re-seeds the LOADTEST space only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wikimanager.settings')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.db.models.signals import post_save  # noqa: E402

from wiki.models import Page, Space  # noqa: E402
from wiki.signals import update_search_vector  # noqa: E402

NORMAL_PAGES = 1500          # ~2-8KB each — the ordinary corpus
BIG_PAGES = 25               # 2-5MB each — the heavy tail that killed prod
VECTOR_SOURCE_CHARS = 500_000  # bounded tsvector source, mirrors real vectors

WORDS = ('deploy runbook postgres search kubernetes replica memory incident '
         'rollback audit retrieval pipeline forgejo origin premerge headline '
         'excerpt vector index label space organization').split()


def _body(i: int, target_chars: int) -> str:
    chunk = ' '.join(WORDS[(i + j) % len(WORDS)] for j in range(12)) + '. '
    return (f'Page {i} canonical runbook section. ' + chunk * (target_chars // len(chunk) + 1))[:target_chars]


def main() -> None:
    post_save.disconnect(update_search_vector, sender=Page)
    # A real owner for the load-test space/pages. Space.owner_id and
    # Page.created_by_id are non-null; omitting them makes the seeder fail on
    # a fresh DB (revi P1 #2). Use a high user id that will never collide with
    # real Shizuha ID users but still passes the integer FK.
    owner_id = 900_001
    space, _ = Space.objects.get_or_create(
        key='LOADTEST', defaults=dict(
            name='WIKI-42 load test', organization_id=1, visibility='public',
            owner_id=owner_id,
        ),
    )
    Page.objects.filter(space=space).delete()

    pages = []
    for i in range(NORMAL_PAGES):
        pages.append(Page(
            space=space, title=f'Runbook deploy audit {i}', slug=f'lt-normal-{i}',
            content_text=_body(i, 2_000 + (i % 7) * 1_000),
            status='published', created_by_id=owner_id,
        ))
    for i in range(BIG_PAGES):
        pages.append(Page(
            space=space, title=f'Giant audit export {i}', slug=f'lt-big-{i}',
            content_text=_body(i, 2_000_000 + i * 120_000),
            status='published', created_by_id=owner_id,
        ))
    Page.objects.bulk_create(pages, batch_size=50)

    with connection.cursor() as cur:
        cur.execute(
            """
            UPDATE wiki_page
            SET search_vector = to_tsvector('english',
                title || ' ' || left(content_text, %s))
            WHERE space_id = %s
            """,
            [VECTOR_SOURCE_CHARS, space.id],
        )
    total = Page.objects.filter(space=space).count()
    print(f'seeded space LOADTEST: {total} pages '
          f'({NORMAL_PAGES} normal + {BIG_PAGES} multi-MB), vectors populated')


if __name__ == '__main__':
    main()
