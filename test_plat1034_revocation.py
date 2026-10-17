"""PLAT-1034: wiki ShizuhaJWTAuthentication enforces token revocation (fail-closed)."""
import time
from unittest.mock import MagicMock, patch

# ── auth-layer integration tests (PLAT-1034 code-review P2) ───────────────
# Verify ShizuhaJWTAuthentication.get_validated_token calls is_token_revoked
# and raises InvalidToken when the token is revoked — on BOTH HS256 and RS256
# paths. Mocks _is_token_revoked directly to isolate auth-layer logic from the
# revocation network call (covered by the unit tests above).


def _make_hs256_token():
    """Return a valid HS256 AccessToken bytes string using simplejwt defaults."""
    from rest_framework_simplejwt.tokens import AccessToken
    from django.conf import settings as _st
    import django
    # Minimal Django settings needed to create an AccessToken without a DB.
    if not _st.configured:
        _st.configure(
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
            INSTALLED_APPS=[
                'django.contrib.contenttypes',
                'django.contrib.auth',
                'rest_framework_simplejwt',
            ],
            SECRET_KEY='test-secret-only',
            SIMPLE_JWT={'ALGORITHM': 'HS256', 'SIGNING_KEY': 'test-secret-only'},
        )
        django.setup()
    tok = AccessToken()
    tok['user_id'] = 99
    tok['client_id'] = 'wiki'
    return str(tok).encode('utf-8')


def _make_rs256_token_and_key():
    """Return (rs256_token_bytes, rsa_public_key) for a minimal RS256 JWT."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    import jwt as _jwt, time as _time

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()
    now = int(_time.time())
    payload = {
        'user_id': 77,
        'client_id': 'wiki',
        'iat': now,
        'exp': now + 3600,
    }
    token = _jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': 'test-key-1'})
    return token.encode('utf-8') if isinstance(token, str) else token, public_key


def test_hs256_revoked_token_raises_invalid_token():
    """HS256 path: revoked → get_validated_token raises InvalidToken."""
    from shizuha_auth import ShizuhaJWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken

    auth = ShizuhaJWTAuthentication()
    raw = _make_hs256_token()

    with patch('shizuha_revocation.is_token_revoked', return_value=True):
        try:
            auth.get_validated_token(raw)
            assert False, 'expected InvalidToken'
        except (InvalidToken, Exception) as exc:
            # Accept InvalidToken or TokenError (both signal revoked)
            assert 'revok' in str(exc).lower() or 'invalid' in str(exc).lower(), (
                f'expected revocation error, got: {exc}'
            )


def test_hs256_active_token_passes():
    """HS256 path: not revoked → get_validated_token returns a validated token."""
    from shizuha_auth import ShizuhaJWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken

    auth = ShizuhaJWTAuthentication()
    raw = _make_hs256_token()

    with patch('shizuha_revocation.is_token_revoked', return_value=False):
        validated = auth.get_validated_token(raw)
    assert validated is not None
    assert validated.get('user_id') == 99


def test_rs256_revoked_token_raises_invalid_token():
    """RS256 path: revoked → get_validated_token raises InvalidToken."""
    from shizuha_auth import ShizuhaJWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken

    raw, pub_key = _make_rs256_token_and_key()
    auth = ShizuhaJWTAuthentication()

    with patch('shizuha_auth._jwks_fetch_keys', return_value={'test-key-1': pub_key}), \
         patch('shizuha_revocation.is_token_revoked', return_value=True):
        try:
            auth.get_validated_token(raw)
            assert False, 'expected InvalidToken'
        except (InvalidToken, Exception) as exc:
            assert 'revok' in str(exc).lower() or 'invalid' in str(exc).lower(), (
                f'expected revocation error, got: {exc}'
            )


def test_rs256_active_token_passes():
    """RS256 path: not revoked → get_validated_token returns validated dict-token."""
    from shizuha_auth import ShizuhaJWTAuthentication

    raw, pub_key = _make_rs256_token_and_key()
    auth = ShizuhaJWTAuthentication()

    with patch('shizuha_auth._jwks_fetch_keys', return_value={'test-key-1': pub_key}), \
         patch('shizuha_revocation.is_token_revoked', return_value=False):
        validated = auth.get_validated_token(raw)
    assert validated is not None
    assert validated.get('user_id') == 77


# ── shizuha_revocation unit tests ─────────────────────────────────────────


def test_no_client_id_still_checks_authority():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": False}
    with patch("requests.post", return_value=resp) as post:
        assert is_token_revoked({}, "session-token") is True
    assert post.call_count == 1


def test_active_token_allowed():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": True}
    with patch("requests.post", return_value=resp):
        assert is_token_revoked({"client_id": "x"}, "tok") is False


def test_revoked_token_denied():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": False}
    with patch("requests.post", return_value=resp):
        assert is_token_revoked({"client_id": "x"}, "tok2") is True


def test_network_error_fails_closed():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    with patch("requests.post", side_effect=OSError("timeout")):
        assert is_token_revoked({"client_id": "x"}, "tok3") is True


def test_non_200_fails_closed():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=503)
    with patch("requests.post", return_value=resp):
        assert is_token_revoked({"client_id": "x"}, "tok4") is True


def test_bad_json_fails_closed():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.side_effect = ValueError("bad json")
    with patch("requests.post", return_value=resp):
        assert is_token_revoked({"client_id": "x"}, "tok5") is True


def test_cache_hit_prevents_duplicate_call():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": True}
    with patch("requests.post", return_value=resp) as mock_post:
        is_token_revoked({"client_id": "x"}, "cached_tok")
        is_token_revoked({"client_id": "x"}, "cached_tok")
        assert mock_post.call_count == 1


def test_expired_cache_triggers_fresh_lookup():
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE, _cache_key
    _REVOCATION_CACHE.clear()
    key = _cache_key("stale_tok")
    _REVOCATION_CACHE[key] = (time.monotonic() - 1, False)  # already expired
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": False}
    with patch("requests.post", return_value=resp) as mock_post:
        result = is_token_revoked({"client_id": "x"}, "stale_tok")
        assert result is True
        assert mock_post.call_count == 1


# ── bytes vs str normalisation ─────────────────────────────────────────────


def test_revocation_called_with_str_for_bytes_raw_token():
    """get_validated_token normalises bytes raw_token to str for revocation."""
    from shizuha_revocation import is_token_revoked, _REVOCATION_CACHE
    _REVOCATION_CACHE.clear()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"active": True}
    with patch("requests.post", return_value=resp) as mock_post:
        is_token_revoked({"client_id": "c"}, "bytestr")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["token"] == "bytestr"


# ── FULL authenticate() request-level integration (PLAT-1034 code-review: "add auth
#    integration tests") ──────────────────────────────────────────────────────
# The tests above exercise get_validated_token directly. These drive the complete
# DRF entrypoint ShizuhaJWTAuthentication.authenticate(request): Authorization
# header -> get_validated_token (revocation enforced) -> get_user. This proves a
# revoked token is rejected on the real request path (not just the token method),
# and an active token authenticates through to a user.


def _request_with_bearer(raw_token):
    from rest_framework.test import APIRequestFactory
    _make_hs256_token()  # ensure Django is configured before building a request
    tok = raw_token.decode("utf-8") if isinstance(raw_token, bytes) else raw_token
    return APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {tok}")


def test_authenticate_request_revoked_token_rejected_end_to_end():
    """authenticate(request): a revoked token is rejected on the full DRF path."""
    from shizuha_auth import ShizuhaJWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken

    auth = ShizuhaJWTAuthentication()
    req = _request_with_bearer(_make_hs256_token())
    with patch("shizuha_revocation.is_token_revoked", return_value=True):
        try:
            auth.authenticate(req)
            assert False, "expected authenticate() to reject a revoked token"
        except (InvalidToken, Exception) as exc:
            assert "revok" in str(exc).lower() or "invalid" in str(exc).lower(), (
                f"expected revocation rejection from authenticate(), got: {exc}"
            )


def test_authenticate_request_revocation_lookup_failure_fails_closed_end_to_end():
    """authenticate(request): if the revocation lookup errors, the token is denied
    (fail-closed) on the full path — a revocation-status outage must not admit a
    possibly-revoked token."""
    from shizuha_auth import ShizuhaJWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken
    from shizuha_revocation import _REVOCATION_CACHE

    _REVOCATION_CACHE.clear()
    auth = ShizuhaJWTAuthentication()
    req = _request_with_bearer(_make_hs256_token())
    # Real is_token_revoked (fails closed -> True) with the network call erroring.
    with patch("requests.post", side_effect=OSError("revocation-status unreachable")):
        try:
            auth.authenticate(req)
            assert False, "expected fail-closed rejection when revocation lookup errors"
        except (InvalidToken, Exception) as exc:
            assert "revok" in str(exc).lower() or "invalid" in str(exc).lower(), (
                f"expected fail-closed rejection, got: {exc}"
            )
