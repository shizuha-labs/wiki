"""WIKI-55 template identity, authorization, and instantiation regressions."""

from django.db.models.signals import post_save
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.authentication import FederatedUser
from wiki.models import Page, PageVersion, Space, SpaceMembership, Template
from wiki.signals import update_search_vector


ORG_A = 1
ORG_B = 2


def _user(user_id, org_id, role='member'):
    return FederatedUser(
        user_id=user_id,
        email=f'user{user_id}@example.test',
        username=f'user{user_id}',
        is_staff=False,
        is_superuser=False,
        enabled_services=['wiki'],
        organization_memberships={org_id: role},
    )


def _client(user, org_id=None):
    headers = {'HTTP_X_ORGANIZATION_ID': str(org_id)} if org_id is not None else {}
    client = APIClient(**headers)
    client.force_authenticate(user=user)
    return client


class TemplateContractTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # PostgreSQL FTS is orthogonal to these page-create assertions.
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.owner = _user(501, ORG_A)
        self.viewer = _user(502, ORG_A)
        self.nonmember = _user(503, ORG_A)
        self.org_admin = _user(504, ORG_A, role='admin')
        self.outsider = _user(601, ORG_B, role='admin')

        self.private_space = Space.objects.create(
            organization_id=ORG_A,
            key='W55PRIVATE',
            name='WIKI-55 private',
            visibility='private',
            owner_id=self.owner.id,
        )
        SpaceMembership.objects.create(
            space=self.private_space,
            user_id=self.viewer.id,
            role='viewer',
            created_by_id=self.owner.id,
        )
        self.org_space = Space.objects.create(
            organization_id=ORG_A,
            key='W55ORG',
            name='WIKI-55 org',
            visibility='org',
            owner_id=self.owner.id,
        )
        self.other_org_space = Space.objects.create(
            organization_id=ORG_B,
            key='W55OTHER',
            name='WIKI-55 other org',
            visibility='org',
            owner_id=self.outsider.id,
        )

        self.source_json = {
            'type': 'doc',
            'content': [{
                'type': 'heading',
                'attrs': {'level': 1},
                'content': [{'type': 'text', 'text': 'Template sentinel'}],
            }],
        }
        self.bound_template = Template.objects.create(
            organization_id=ORG_A,
            space=self.private_space,
            name='Bound template',
            content_json=self.source_json,
            content_text='# Template sentinel\n',
            created_by_id=self.owner.id,
        )
        self.org_template = Template.objects.create(
            organization_id=ORG_A,
            space=None,
            name='Org template',
            content_json=self.source_json,
            content_text='# Org sentinel\n',
            created_by_id=self.owner.id,
        )
        self.other_org_template = Template.objects.create(
            organization_id=ORG_B,
            space=self.other_org_space,
            name='Other-org template',
            content_json=self.source_json,
            content_text='# Other org\n',
            created_by_id=self.outsider.id,
        )

        self.owner_client = _client(self.owner, ORG_A)

    @staticmethod
    def _rows(response):
        return response.data.get('results', response.data) if isinstance(response.data, dict) else response.data

    def test_space_bound_template_list_then_detail_update_delete(self):
        listed = self.owner_client.get(f'/api/templates/?space={self.private_space.id}')
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.data)
        self.assertIn(str(self.bound_template.id), {str(row['id']) for row in self._rows(listed)})

        detail = self.owner_client.get(f'/api/templates/{self.bound_template.id}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        self.assertEqual(detail.data['content_text'], '# Template sentinel\n')

        updated = self.owner_client.patch(
            f'/api/templates/{self.bound_template.id}/',
            {'name': 'Bound template updated', 'content_text': '# Updated\n'},
            format='json',
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.data)
        self.assertEqual(updated.data['content_text'], '# Updated\n')

        deleted = self.owner_client.delete(f'/api/templates/{self.bound_template.id}/')
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT, deleted.data)
        self.assertFalse(Template.objects.filter(pk=self.bound_template.id).exists())

    def test_full_create_list_get_update_instantiate_read_delete_journey(self):
        created_template = self.owner_client.post(
            '/api/templates/',
            {
                'space': str(self.private_space.id),
                'name': 'Journey template',
                'content_text': '# Journey source\n',
                'content_json': {
                    'type': 'doc',
                    'content': [{
                        'type': 'heading',
                        'attrs': {'level': 1},
                        'content': [{'type': 'text', 'text': 'Journey source'}],
                    }],
                },
            },
            format='json',
        )
        self.assertEqual(created_template.status_code, status.HTTP_201_CREATED, created_template.data)
        template_id = created_template.data['id']

        listed = self.owner_client.get(f'/api/templates/?space={self.private_space.id}')
        self.assertIn(str(template_id), {str(row['id']) for row in self._rows(listed)})

        detail = self.owner_client.get(f'/api/templates/{template_id}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        self.assertEqual(detail.data['content_text'], '# Journey source\n')

        updated_json = {
            'type': 'doc',
            'content': [{
                'type': 'paragraph',
                'content': [{'type': 'text', 'text': 'Updated journey sentinel'}],
            }],
        }
        updated = self.owner_client.patch(
            f'/api/templates/{template_id}/',
            {
                'content_text': 'Updated journey sentinel\n',
                'content_json': updated_json,
            },
            format='json',
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.data)

        instantiated = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.private_space.id),
                'title': 'Journey page',
                'template_id': str(template_id),
                'status': 'published',
            },
            format='json',
        )
        self.assertEqual(instantiated.status_code, status.HTTP_201_CREATED, instantiated.data)
        page_id = instantiated.data['id']

        read_page = self.owner_client.get(f'/api/pages/{page_id}/')
        self.assertEqual(read_page.status_code, status.HTTP_200_OK, read_page.data)
        self.assertEqual(read_page.data['content_text'], 'Updated journey sentinel\n')
        self.assertEqual(read_page.data['content_json'], updated_json)

        deleted_page = self.owner_client.delete(f'/api/pages/{page_id}/')
        self.assertEqual(deleted_page.status_code, status.HTTP_204_NO_CONTENT, deleted_page.data)
        deleted_template = self.owner_client.delete(f'/api/templates/{template_id}/')
        self.assertEqual(deleted_template.status_code, status.HTTP_204_NO_CONTENT, deleted_template.data)

    def test_list_filter_is_not_reused_as_detail_identity_filter(self):
        unfiltered = self.owner_client.get('/api/templates/')
        self.assertEqual(unfiltered.status_code, status.HTTP_200_OK)
        ids = {str(row['id']) for row in self._rows(unfiltered)}
        self.assertIn(str(self.org_template.id), ids)
        self.assertNotIn(str(self.bound_template.id), ids)

        detail = self.owner_client.get(f'/api/templates/{self.bound_template.id}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)

    def test_private_and_cross_org_template_ids_remain_hidden(self):
        private_probe = _client(self.nonmember, ORG_A).get(
            f'/api/templates/{self.bound_template.id}/'
        )
        cross_org_probe = _client(self.outsider, ORG_B).get(
            f'/api/templates/{self.bound_template.id}/'
        )
        self.assertEqual(private_probe.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(cross_org_probe.status_code, status.HTTP_404_NOT_FOUND)

    def test_template_writes_require_explicit_org_and_object_permission(self):
        no_org = _client(self.owner).patch(
            f'/api/templates/{self.bound_template.id}/', {'name': 'nope'}, format='json'
        )
        viewer = _client(self.viewer, ORG_A).patch(
            f'/api/templates/{self.bound_template.id}/', {'name': 'nope'}, format='json'
        )
        self.assertEqual(no_org.status_code, status.HTTP_400_BAD_REQUEST, no_org.data)
        self.assertEqual(viewer.status_code, status.HTTP_403_FORBIDDEN, viewer.data)

    def test_create_rejects_cross_org_or_unwritable_private_space(self):
        cross_org = self.owner_client.post(
            '/api/templates/',
            {
                'space': str(self.other_org_space.id),
                'name': 'Cross org',
                'content_text': 'nope',
                'content_json': {},
            },
            format='json',
        )
        private = _client(self.nonmember, ORG_A).post(
            '/api/templates/',
            {
                'space': str(self.private_space.id),
                'name': 'Private intrusion',
                'content_text': 'nope',
                'content_json': {},
            },
            format='json',
        )
        self.assertEqual(cross_org.status_code, status.HTTP_403_FORBIDDEN, cross_org.data)
        self.assertEqual(private.status_code, status.HTTP_404_NOT_FOUND, private.data)

    def test_page_creation_instantiates_exact_bound_template_content(self):
        created = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.private_space.id),
                'title': 'Instantiated bound page',
                'template_id': str(self.bound_template.id),
                'status': 'published',
            },
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        page = Page.objects.get(pk=created.data['id'])
        self.assertEqual(page.content_json, self.source_json)
        self.assertEqual(page.content_text, '# Template sentinel\n')
        version = PageVersion.objects.get(page=page, version_number=1)
        self.assertEqual(version.content_json, self.source_json)
        self.assertEqual(version.content_text, '# Template sentinel\n')

    def test_org_template_can_instantiate_to_another_same_org_space(self):
        created = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.org_space.id),
                'title': 'Instantiated org page',
                'template_id': str(self.org_template.id),
                'status': 'draft',
            },
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        page = Page.objects.get(pk=created.data['id'])
        self.assertEqual(page.content_text, '# Org sentinel\n')

    def test_bound_template_cannot_instantiate_into_a_different_space(self):
        response = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.org_space.id),
                'title': 'Wrong target',
                'template_id': str(self.bound_template.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(Page.objects.filter(title='Wrong target').exists())

    def test_cross_org_template_cannot_instantiate_by_uuid(self):
        response = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.org_space.id),
                'title': 'Cross-org target',
                'template_id': str(self.other_org_template.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)
        self.assertFalse(Page.objects.filter(title='Cross-org target').exists())

    def test_template_id_rejects_ambiguous_caller_content(self):
        response = self.owner_client.post(
            '/api/pages/',
            {
                'space': str(self.private_space.id),
                'title': 'Ambiguous content',
                'template_id': str(self.bound_template.id),
                'content_text': 'caller override',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('template_id', response.data)
