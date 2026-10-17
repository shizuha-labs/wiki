"""Pytest bootstrap: configure minimal Django settings BEFORE any test imports
shizuha_auth, which imports DRF + simplejwt at module level and therefore needs
settings configured. The per-test settings.configure() in the auth tests runs
*after* `from shizuha_auth import ...`, so without this the auth-layer tests fail
to even import. Idempotent — _make_hs256_token()'s `if not settings.configured`
becomes a no-op once this has run."""
import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "rest_framework_simplejwt",
        ],
        SECRET_KEY="test-secret-only",
        SIMPLE_JWT={"ALGORITHM": "HS256", "SIGNING_KEY": "test-secret-only"},
    )
    django.setup()
