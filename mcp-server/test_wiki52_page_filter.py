"""Regression tests for WIKI-52: page-filtered list wrappers must send page_id,
not the DRF-pagination-owned 'page' query param (which 404s with a page UUID).
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MCP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MCP_DIR))
os.environ.setdefault("SHIZUHA_WIKI_URL", "https://wiki.example.test")
os.environ.setdefault("SHIZUHA_WIKI_JWT_TOKEN", "test-token")

wiki_server = importlib.import_module("wiki_server")
base_module = importlib.import_module("base")

PAGE_UUID = "19ee71e8-4569-4423-a395-0eff7e179879"


class PageFilteredListTests(unittest.TestCase):
    def _captured(self, payload):
        captured = {}

        def _fake_api_request(method, endpoint, params=None, **kwargs):
            captured["method"] = method
            captured["endpoint"] = endpoint
            captured["params"] = params
            return {"results": payload}

        return captured, _fake_api_request

    def test_list_attachments_sends_page_id_not_page(self):
        captured, fake = self._captured([{"id": "att-1"}])
        with patch.object(wiki_server.base, "api_request", side_effect=fake):
            wiki_server.list_attachments(page_id=PAGE_UUID, limit=10)

        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["endpoint"], "/attachments/")
        self.assertEqual(captured["params"]["page_id"], PAGE_UUID)
        self.assertNotIn("page", captured["params"], "page UUID must not ride the pagination param")
        self.assertEqual(captured["params"]["page_size"], 10)

    def test_list_comments_sends_page_id_not_page_with_is_resolved(self):
        captured, fake = self._captured([{"id": "c-1"}])
        with patch.object(wiki_server.base, "api_request", side_effect=fake):
            wiki_server.list_comments(
                page_id=PAGE_UUID, is_resolved=True, limit=10
            )

        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["endpoint"], "/comments/")
        self.assertEqual(captured["params"]["page_id"], PAGE_UUID)
        self.assertNotIn("page", captured["params"], "page UUID must not ride the pagination param")
        self.assertEqual(captured["params"]["is_resolved"], True)
        self.assertEqual(captured["params"]["page_size"], 10)


if __name__ == "__main__":
    unittest.main()
