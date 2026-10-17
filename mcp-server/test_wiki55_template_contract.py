"""WIKI-55 MCP surface contract for template CRUD and instantiation."""

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MCP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MCP_DIR))
os.environ.setdefault('SHIZUHA_WIKI_URL', 'https://wiki.example.test')

wiki_server = importlib.import_module('wiki_server')


class TemplateMCPContractTests(unittest.TestCase):
    def test_create_page_from_template_uses_server_side_page_contract(self):
        response = {
            'id': 'page-id',
            'title': 'Runbook copy',
            'slug': 'runbook-copy',
            'organization_id': 1,
            'version': 1,
        }
        with patch.object(wiki_server.base, 'api_request', return_value=response) as request:
            result = wiki_server.create_page_from_template(
                template_id='template-id',
                space_id='space-id',
                title='Runbook copy',
                parent_id='parent-id',
                status='draft',
                organization_id=1,
            )

        request.assert_called_once_with(
            'POST',
            '/pages/',
            data={
                'template_id': 'template-id',
                'space': 'space-id',
                'title': 'Runbook copy',
                'status': 'draft',
                'parent': 'parent-id',
            },
            organization_id=1,
        )
        self.assertIn('Page created from template!', result)
        self.assertIn('**Template**: template-id', result)

    def test_get_template_passes_optional_org_and_returns_source(self):
        response = {
            'id': 'template-id',
            'name': 'Runbook',
            'content_text': '# Exact source\n',
        }
        with patch.object(wiki_server.base, 'api_request', return_value=response) as request:
            result = wiki_server.get_template('template-id', organization_id=1)

        request.assert_called_once_with(
            'GET', '/templates/template-id/', organization_id=1
        )
        self.assertIn('# Exact source', result)

    def test_update_template_sends_required_org_and_both_content_forms(self):
        response = {'id': 'template-id', 'name': 'Updated'}
        with patch.object(wiki_server.base, 'api_request', return_value=response) as request:
            result = wiki_server.update_template(
                'template-id', 1, name='Updated', content='# Updated\n'
            )

        args = request.call_args
        self.assertEqual(args.args, ('PATCH', '/templates/template-id/'))
        self.assertEqual(args.kwargs['organization_id'], 1)
        self.assertEqual(args.kwargs['data']['content_text'], '# Updated\n')
        self.assertEqual(args.kwargs['data']['content_json']['type'], 'doc')
        self.assertIn('Template updated!', result)

    def test_delete_template_sends_required_org(self):
        with patch.object(wiki_server.base, 'api_request', return_value={}) as request:
            result = wiki_server.delete_template('template-id', 1)

        request.assert_called_once_with(
            'DELETE', '/templates/template-id/', organization_id=1
        )
        self.assertEqual(result, 'Template deleted.')


if __name__ == '__main__':
    unittest.main()
