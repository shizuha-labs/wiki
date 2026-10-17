import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt as pyjwt
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Product access (do you have Wiki) is live from Identity, like Confluence
# checking the current grant. The JWT is identity: signature, expiry, user_id.
# Space/page ACL is already live in wiki's own DB (WIKI-18).
#
# Positive hits cache 30s so a page of API calls is one ID round-trip and a
# revoke is bounded. Denies are not cached so a grant applies on the next
# request. Identity unreachable: honor a JWT that already lists wiki
# (degraded availability); deny a JWT that omits wiki (never fail open).
_LIVE_GRANT_TTL_S = 30.0
_live_grant_cache = {}


def _tool_slugs_from_id_user(payload):
    if not isinstance(payload, dict):
        return set()
    profile = payload.get('profile') or {}
    tools = profile.get('enabled_tools') or payload.get('enabled_services') or []
    slugs = set()
    if isinstance(tools, dict):
        tools = tools.values()
    for item in tools:
        if isinstance(item, str) and item:
            slugs.add(item)
        elif isinstance(item, dict):
            slug = item.get('slug') or item.get('id')
            if slug:
                slugs.add(str(slug))
    return slugs


def live_service_probe(token, slug):
    """Live ID grant for `slug`.

    Returns True / False when Identity answered, or None when it is unreachable
    so the caller can degrade instead of failing open.
    """
    base = getattr(
        settings,
        'SHIZUHA_ID_API_URL',
        'http://shizuha-id:8001/api',
    ).rstrip('/')
    url = f'{base}/auth/user/'
    req = Request(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
        },
        method='GET',
    )
    try:
        with urlopen(req, timeout=2.5) as resp:
            if resp.status != 200:
                return None
            raw = resp.read().decode()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.info('wiki live service check failed: %s', exc)
        return None
    try:
        payload = json.loads(raw or '{}')
    except json.JSONDecodeError:
        return None
    return slug in _tool_slugs_from_id_user(payload)


def live_service_granted(token, slug):
    """True only when Identity answered and currently grants `slug`."""
    return live_service_probe(token, slug) is True


def _cached_positive_grant(user_id, slug):
    now = time.monotonic()
    hit = _live_grant_cache.get((user_id, slug))
    return bool(hit and hit[0] > now)


def _remember_positive_grant(user_id, slug):
    _live_grant_cache[(user_id, slug)] = (time.monotonic() + _LIVE_GRANT_TTL_S, True)


_live_org_cache = {}


def live_org_member(token, org_id):
    """Whether Admin currently lists `org_id` for this bearer.

    True / False when Admin answered; None when unreachable.
    """
    import os
    base = (
        os.environ.get('SHIZUHA_ADMIN_API_URL')
        or getattr(settings, 'SHIZUHA_ADMIN_API_URL', None)
        or 'http://shizuha-admin:8003/api'
    )
    url = f'{str(base).rstrip("/")}/organizations/'
    req = Request(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
        },
        method='GET',
    )
    try:
        with urlopen(req, timeout=2.5) as resp:
            if resp.status != 200:
                return None
            raw = resp.read().decode()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.info('wiki live org membership check failed: %s', exc)
        return None
    try:
        payload = json.loads(raw or '{}')
    except json.JSONDecodeError:
        return None
    results = payload.get('results') if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        return False
    want = int(org_id)
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get('id')) == want:
                return True
        except (TypeError, ValueError):
            continue
    return False


def heal_request_org_membership(request, org_id):
    """Stamp live Admin membership onto request.user. False if not a member."""
    user = getattr(request, 'user', None)
    if user is None:
        return False
    try:
        org_id = int(org_id)
    except (TypeError, ValueError):
        return False
    uid = getattr(user, 'id', None)
    now = time.monotonic()
    cache_key = (uid, org_id)
    hit = _live_org_cache.get(cache_key)
    if hit and hit[0] > now:
        _stamp_org_membership(user, org_id)
        return True
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    if not token:
        return False
    live = live_org_member(token, org_id)
    if live is True:
        _live_org_cache[cache_key] = (now + _LIVE_GRANT_TTL_S, True)
        _stamp_org_membership(user, org_id)
        return True
    return False


def _stamp_org_membership(user, org_id):
    memberships = dict(getattr(user, 'organization_memberships', None) or {})
    memberships[int(org_id)] = memberships.get(int(org_id)) or 'member'
    user.organization_memberships = memberships


def _deny():
    return JsonResponse(
        {
            'error': 'You do not have access to this service.',
            'service': 'wiki',
            'code': 'service_access_denied',
        },
        status=403,
    )


class ServiceAccessMiddleware:
    SERVICE_SLUG = 'wiki'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        if '/internal/' in request.path:
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                payload = pyjwt.decode(
                    token,
                    getattr(settings, 'JWT_SECRET_KEY', settings.SECRET_KEY),
                    algorithms=['HS256'],
                    options={'verify_exp': True}
                )
                if payload.get('is_staff') or payload.get('is_superuser'):
                    return self.get_response(request)
                enabled_services = payload.get('enabled_services')
                # DRV-46: an explicit list is restrictive. A missing claim is
                # legacy/unrestricted and is left to DRF.
                if enabled_services is not None:
                    user_id = payload.get('user_id')
                    jwt_lists_wiki = self.SERVICE_SLUG in enabled_services
                    if _cached_positive_grant(user_id, self.SERVICE_SLUG):
                        return self.get_response(request)
                    live = live_service_probe(token, self.SERVICE_SLUG)
                    if live is True:
                        _remember_positive_grant(user_id, self.SERVICE_SLUG)
                        return self.get_response(request)
                    if live is False:
                        return _deny()
                    # Identity unreachable. Never fail open for a token that
                    # does not already list wiki.
                    if jwt_lists_wiki:
                        logger.warning(
                            'wiki live grant unreachable; honoring JWT wiki claim for user_id=%s',
                            user_id,
                        )
                        return self.get_response(request)
                    return _deny()
            except Exception:
                pass  # Let DRF authentication handle invalid tokens

        return self.get_response(request)
