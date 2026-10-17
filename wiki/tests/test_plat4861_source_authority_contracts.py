import io
import json
import os
import re
import subprocess
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from uuid import UUID

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from wiki.models import Page, PageVersion, Space
from wiki.section_edit import list_markdown_sections


User = get_user_model()
HLD_ID = UUID('c0421715-2465-4156-9c91-41c918be27cf')
GOOD_HLD = (
    '# Source authority\n'
    'Origin is the canonical source of truth and Origin CI is Forgejo Actions.\n'
    'GitHub is a read-only downstream mirror.\n'
)


class PremergeWorkflowShellBoundaryTests(SimpleTestCase):
    def test_job_manifest_defers_source_sha_expansion_to_the_pod(self):
        workflow_path = Path(__file__).resolve().parents[2] / '.forgejo/workflows/premerge.yml'
        workflow = workflow_path.read_text()
        manifest = re.search(
            r'(?ms)^\s*cat <<YAML \| kubectl apply -f -\n(?P<body>.*?)^\s*YAML$',
            workflow,
        )
        self.assertIsNotNone(manifest, 'premerge Job manifest heredoc not found')

        # Forgejo expands these expressions before bash runs. Replace them with
        # inert fixtures, then execute the outer unquoted heredoc under nounset.
        # An unescaped in-pod variable (such as SOURCE_SHA) must make this test
        # fail exactly as it would on the Actions runner.
        body = re.sub(r'\$\{\{.*?\}\}', 'deadbeefdeadbeef', manifest.group('body'))
        script = f'set -eu\nJOB=ci-test-shizuha-wiki-deadbee\ncat <<YAML\n{body}YAML\n'
        env = {key: value for key, value in os.environ.items() if key != 'SOURCE_SHA'}
        completed = subprocess.run(
            ['bash', '--noprofile', '--norc'],
            input=script,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, '')
        self.assertIn('case "${SOURCE_SHA}" in', completed.stdout)
        self.assertIn('"${SOURCE_SHA}" > /tmp/source-authority.json', completed.stdout)
        source_authority = completed.stdout[
            completed.stdout.index('- name: source-authority-contract'):
            completed.stdout.index('- name: git-clone')
        ]
        self.assertIn(
            'curl --fail-with-body --retry 8 --retry-connrefused',
            source_authority,
        )
        self.assertIn('--retry-delay 2 --retry-max-time 30', source_authority)
        self.assertNotIn(
            '--retry-all-errors',
            source_authority,
            'deterministic contract rejections must fail immediately',
        )


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.payload


@override_settings(
    SOURCE_AUTHORITY_CONTRACT_URL='http://contract.invalid',
    SOURCE_AUTHORITY_CONTRACT_TIMEOUT_SECONDS=0.1,
)
class ProtectedHLDMutationAdmissionTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.disconnect(update_search_vector, sender=Page)

    @classmethod
    def tearDownClass(cls):
        from django.db.models.signals import post_save
        from wiki.signals import update_search_vector
        post_save.connect(update_search_vector, sender=Page)
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='sora-plat4861',
            email='sora-plat4861@example.com',
            password='x',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1,
            key='ENG4861',
            name='Engineering PLAT-4861',
            visibility='org',
            owner_id=self.user.id,
        )
        self.page = Page.objects.create(
            id=HLD_ID,
            space=self.space,
            title='HLD: Origin source of truth',
            content_text=GOOD_HLD,
            content_json={},
            status='published',
            created_by_id=self.user.id,
        )
        PageVersion.objects.create(
            page=self.page,
            version_number=1,
            title=self.page.title,
            content_text=self.page.content_text,
            content_json=self.page.content_json,
            created_by_id=self.user.id,
        )

    def _allow(self):
        return _Response({
            'decision': 'allow',
            'registry_version': 'orig18-v1',
            'registry_sha256': 'a' * 64,
            'matched_consumers': ['wiki.origin_hld'],
            'violations': [],
        })

    def _reject(self):
        payload = {
            'decision': 'reject',
            'registry_version': 'orig18-v1',
            'registry_sha256': 'b' * 64,
            'matched_consumers': ['wiki.origin_hld'],
            'violations': [{
                'consumer': 'wiki.origin_hld',
                'contract': 'origin-source-authority',
                'location': f'wiki.page_content:{HLD_ID}',
                'message': 'canonical HLD lost Origin authority',
            }],
        }
        return HTTPError(
            'http://contract.invalid/contracts/validate',
            422,
            'rejected',
            {},
            io.BytesIO(json.dumps(payload).encode()),
        )

    @mock.patch('wiki.source_authority_contracts.urllib.request.urlopen')
    def test_full_page_update_commits_only_after_revisioned_allow(self, urlopen):
        urlopen.return_value = self._allow()
        response = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {
                'content_text': GOOD_HLD + '\n## Contract registry\nVersioned and event-driven.\n',
                'expected_version': 1,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.page.refresh_from_db()
        self.assertEqual(self.page.version, 2)
        self.assertIn('Contract registry', self.page.content_text)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers['X-shizuha-event-source'], 'wiki')

    @mock.patch('wiki.source_authority_contracts.urllib.request.urlopen')
    def test_rejected_full_page_update_leaves_page_and_version_unchanged(self, urlopen):
        urlopen.side_effect = self._reject()
        response = self.client.patch(
            f'/api/pages/{self.page.id}/',
            {'content_text': 'GitHub is canonical now.', 'expected_version': 1},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.page.refresh_from_db()
        self.assertEqual(self.page.version, 1)
        self.assertEqual(self.page.content_text, GOOD_HLD)
        self.assertEqual(self.page.versions.count(), 1)

    @mock.patch('wiki.source_authority_contracts.urllib.request.urlopen')
    def test_validator_outage_aborts_section_edit_before_save(self, urlopen):
        urlopen.side_effect = URLError('provider offline')
        section = list_markdown_sections(self.page.content_text)[0]
        response = self.client.post(
            f'/api/pages/{self.page.id}/sections/',
            {
                'heading_or_anchor': section.anchor,
                'base_section_hash': section.section_hash,
                'content': '# Source authority\nGitHub is primary.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.page.refresh_from_db()
        self.assertEqual(self.page.version, 1)
        self.assertEqual(self.page.content_text, GOOD_HLD)

    @mock.patch('wiki.source_authority_contracts.urllib.request.urlopen')
    def test_rejected_restore_does_not_create_a_version(self, urlopen):
        urlopen.side_effect = self._reject()
        response = self.client.post(
            f'/api/pages/{self.page.id}/restore_version/',
            {'version': 1},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.page.refresh_from_db()
        self.assertEqual(self.page.version, 1)
        self.assertEqual(self.page.versions.count(), 1)

    @mock.patch('wiki.source_authority_contracts.urllib.request.urlopen')
    def test_protected_hld_delete_is_contract_admitted(self, urlopen):
        urlopen.side_effect = self._reject()
        response = self.client.delete(f'/api/pages/{self.page.id}/')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Page.objects.filter(pk=self.page.pk).exists())
