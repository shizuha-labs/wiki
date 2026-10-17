"""PLAT-5027: `create` must be gated by the same space ACL as update/delete.

Regression: _can_create_page_in_space() returned True for ANY org member in an
org-visible space (`space.visibility == 'org' and org_role`), so a principal
with permissions:{} (org_member in an ORG_READONLY space like HANDBOOK) could
create pages it could never edit or delete — degrading the mandated UPSERT to
insert-only. create now delegates to the canonical WikiPermissionService so
create/update/delete agree on the space permission map.
"""
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.models import Page, Space

ORG_A = 1


def _fed(user_id, org, role='member'):
    from wiki.authentication import FederatedUser
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@org{org}.example',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={org: role},
    )


def _client(user, org):
    c = APIClient(HTTP_X_ORGANIZATION_ID=str(org))
    c.force_authenticate(user=user)
    return c


class CreatePageAclTests(APITestCase):
    def setUp(self):
        self.member = _fed(501, ORG_A, role='member')  # org_member in HANDBOOK
        self.editor = _fed(502, ORG_A, role='member')  # editor in a normal org space
        self.c_member = _client(self.member, ORG_A)
        self.c_editor = _client(self.editor, ORG_A)

        # HANDBOOK is in ORG_READONLY_SPACE_KEYS -> org members get role
        # 'org_member' with permissions {} (no page:create/update/delete).
        self.handbook = Space.objects.create(
            organization_id=ORG_A, key='HANDBOOK', name='Agent Handbook',
            visibility='org', owner_id=0,
        )
        # A normal org-visible space -> org members get role 'editor'.
        self.normal = Space.objects.create(
            organization_id=ORG_A, key='DOCS', name='Team Docs',
            visibility='org', owner_id=0,
        )

    def _create_page(self, client, space, title='PLAT-5027 probe'):
        return client.post('/api/pages/', {
            'space': str(space.id),
            'title': title,
            'content_text': 'probe body',
            'content_json': {},
            'status': 'published',
        }, format='json')

    def test_org_member_with_empty_perms_cannot_create_in_handbook(self):
        # The regression: previously this succeeded even with permissions {}.
        # The serializer-level write gate refuses with a clear permission error
        # (fail-closed), matching the established create-denial pattern.
        resp = self._create_page(self.c_member, self.handbook)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            'do not have permission to create pages',
            str(resp.data.get('space', '')),
        )
        self.assertFalse(Page.objects.filter(space=self.handbook, title='PLAT-5027 probe').exists())

    def test_editor_can_create_in_normal_org_space(self):
        # Negative control: the check fails closed, not merely passes when
        # permitted — a real editor in a writable space still creates.
        resp = self._create_page(self.c_editor, self.normal, title='PLAT-5027 editor probe')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Page.objects.filter(space=self.normal, title='PLAT-5027 editor probe').exists())

    def test_org_member_cannot_create_in_handbook_via_direct_check(self):
        # Unit-level: the serializer gate agrees with the endpoint.
        from wiki.serializers import _can_create_page_in_space
        self.assertFalse(_can_create_page_in_space(self.member, self.handbook))
        self.assertTrue(_can_create_page_in_space(self.editor, self.normal))
