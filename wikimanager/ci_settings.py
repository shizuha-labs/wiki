"""Seat-local CI settings: sqlite in-memory, no Celery broker, migrations bypassed.

The wiki migration set contains Postgres-specific RunSQL (0006/0007) and the
Page model declares a Postgres-only GinIndex on its SearchVectorField — both
cannot execute on sqlite, which seat-side test runs use (no shizuha-db from a
seat). MIGRATION_MODULES bypasses the migrations (tables come from the models)
and the pre-migrate hook strips the GinIndex for the sqlite schema editor.
Postgres FTS behaviour itself is exercised in Origin CI (postgres service).
"""
from django.contrib.postgres.indexes import GinIndex
from django.db.models.signals import pre_migrate

from wikimanager.settings import *  # noqa: F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
MIGRATION_MODULES = {'wiki': None}


def _strip_postgres_only_indexes(sender=None, **kwargs):
    from wiki.models import Page
    Page._meta.indexes = [i for i in Page._meta.indexes if not isinstance(i, GinIndex)]


pre_migrate.connect(_strip_postgres_only_indexes)
