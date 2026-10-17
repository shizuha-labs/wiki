"""Wiki product access is live from Identity; the JWT is identity.

A Drive-only snapshot still 403s (DRV-46). A wiki grant on the ID profile
passes even when the access token still lists id+hive. A wiki revoke on the
ID profile 403s even when the access token still lists wiki. Identity down
honors a JWT that already lists wiki and denies one that omits it.
"""
import json
from unittest.mock import patch
from urllib.error import URLError

import jwt as pyjwt
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from types import SimpleNamespace

from wiki.middleware import (
    ServiceAccessMiddleware,
    _live_grant_cache,
    _live_org_cache,
    _tool_slugs_from_id_user,
    heal_request_org_membership,
    live_org_member,
    live_service_granted,
    live_service_probe,
)

SECRET = 'test-jwt-secret-for-service-access'


def _ok(_request):
    return HttpResponse('ok')


def _bearer(services, user_id=2):
    token = pyjwt.encode(
        {
            'user_id': user_id,
            'username': 'hritik',
            'enabled_services': services,
            'is_staff': False,
            'is_superuser': False,
        },
        SECRET,
        algorithm='HS256',
    )
    return token.decode() if isinstance(token, bytes) else token


def _mw_request(token):
    factory = RequestFactory()
    request = factory.get('/api/spaces/', HTTP_AUTHORIZATION=f'Bearer {token}')
    return ServiceAccessMiddleware(_ok)(request)


class _Resp:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ToolSlugParseTests(SimpleTestCase):
    def test_profile_enabled_tools_objects(self):
        slugs = _tool_slugs_from_id_user({
            'profile': {'enabled_tools': [{'slug': 'id'}, {'slug': 'wiki'}]},
        })
        self.assertEqual(slugs, {'id', 'wiki'})

    def test_enabled_services_list(self):
        slugs = _tool_slugs_from_id_user({'enabled_services': ['id', 'hive']})
        self.assertEqual(slugs, {'id', 'hive'})


@override_settings(JWT_SECRET_KEY=SECRET, SHIZUHA_ID_API_URL='http://id.test/api')
class LiveGrantMiddlewareTests(SimpleTestCase):
    def setUp(self):
        _live_grant_cache.clear()

    def test_jwt_wiki_still_asks_id_on_cache_miss(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'profile': {'enabled_tools': [{'slug': 'id'}, {'slug': 'wiki'}]},
        })) as urlopen:
            response = _mw_request(_bearer(['id', 'wiki']))
        self.assertEqual(response.status_code, 200)
        urlopen.assert_called_once()

    def test_positive_cache_skips_second_id_call(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'profile': {'enabled_tools': [{'slug': 'wiki'}]},
        })) as urlopen:
            self.assertEqual(_mw_request(_bearer(['id', 'wiki'])).status_code, 200)
            self.assertEqual(_mw_request(_bearer(['id', 'wiki'])).status_code, 200)
        self.assertEqual(urlopen.call_count, 1)

    def test_stale_jwt_passes_when_id_profile_has_wiki(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'id': 2,
            'profile': {'enabled_tools': [{'slug': 'id'}, {'slug': 'wiki'}]},
        })):
            response = _mw_request(_bearer(['id', 'hive']))
        self.assertEqual(response.status_code, 200)

    def test_stale_jwt_denied_when_id_profile_lacks_wiki(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'id': 2,
            'profile': {'enabled_tools': [{'slug': 'id'}, {'slug': 'hive'}]},
        })):
            response = _mw_request(_bearer(['id', 'hive']))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)['code'], 'service_access_denied')

    def test_revoke_denied_even_when_jwt_still_lists_wiki(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'profile': {'enabled_tools': [{'slug': 'id'}]},
        })):
            response = _mw_request(_bearer(['id', 'wiki']))
        self.assertEqual(response.status_code, 403)

    def test_id_unreachable_fails_closed_without_wiki_claim(self):
        with patch('wiki.middleware.urlopen', side_effect=URLError('down')):
            response = _mw_request(_bearer(['id', 'hive']))
        self.assertEqual(response.status_code, 403)

    def test_id_unreachable_honors_existing_wiki_claim(self):
        with patch('wiki.middleware.urlopen', side_effect=URLError('down')):
            response = _mw_request(_bearer(['id', 'wiki']))
        self.assertEqual(response.status_code, 200)

    def test_legacy_unrestricted_skips_live_check(self):
        token = pyjwt.encode(
            {
                'user_id': 2,
                'username': 'legacy',
                'is_staff': False,
                'is_superuser': False,
            },
            SECRET,
            algorithm='HS256',
        )
        if isinstance(token, bytes):
            token = token.decode()
        with patch('wiki.middleware.urlopen') as urlopen:
            response = _mw_request(token)
        self.assertEqual(response.status_code, 200)
        urlopen.assert_not_called()

    def test_live_service_granted_reads_id_user(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'profile': {'enabled_tools': [{'slug': 'wiki'}]},
        })):
            self.assertTrue(live_service_granted('tok', 'wiki'))
            self.assertTrue(live_service_probe('tok', 'wiki') is True)

    def test_probe_unreachable_is_none(self):
        with patch('wiki.middleware.urlopen', side_effect=URLError('down')):
            self.assertIsNone(live_service_probe('tok', 'wiki'))
            self.assertFalse(live_service_granted('tok', 'wiki'))


@override_settings(JWT_SECRET_KEY=SECRET, SHIZUHA_ADMIN_API_URL='http://admin.test/api')
class LiveOrgMembershipTests(SimpleTestCase):
    def setUp(self):
        _live_org_cache.clear()

    def test_admin_lists_org(self):
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'results': [{'id': 1, 'name': "Hritik's Workspace"}],
        })):
            self.assertTrue(live_org_member('tok', 1))
            self.assertFalse(live_org_member('tok', 4))

    def test_heal_stamps_user_membership(self):
        user = SimpleNamespace(id=2, organization_memberships={})
        request = SimpleNamespace(
            user=user,
            META={'HTTP_AUTHORIZATION': 'Bearer tok'},
        )
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'results': [{'id': 1, 'name': "Hritik's Workspace"}],
        })):
            self.assertTrue(heal_request_org_membership(request, 1))
        self.assertEqual(user.organization_memberships.get(1), 'member')

    def test_heal_denies_unknown_org(self):
        user = SimpleNamespace(id=2, organization_memberships={})
        request = SimpleNamespace(
            user=user,
            META={'HTTP_AUTHORIZATION': 'Bearer tok'},
        )
        with patch('wiki.middleware.urlopen', return_value=_Resp({
            'results': [{'id': 1}],
        })):
            self.assertFalse(heal_request_org_membership(request, 99))
        self.assertEqual(user.organization_memberships, {})
