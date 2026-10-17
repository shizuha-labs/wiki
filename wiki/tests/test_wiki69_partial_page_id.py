"""
WIKI-69 — wiki_get_page resolves partial/prefix page IDs.

A bare 404 on a partial page ID (e.g. the 8-char prefix `1845935e` cited in
cross-links) is a dead-end for navigation. The MCP server resolves the prefix
to the unique full UUID when unambiguous, returns a typed "ambiguous prefix"
error when multiple pages match, and only then falls back to a helpful 404.

The MCP server module needs `mcp.server.fastmcp`, which is not part of the
Django test environment, so this test AST-extracts the pure resolution helper
and exercises it against a mocked base API — proving the classification logic
by construction.
"""
import ast
import os
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "mcp-server" / "wiki_server.py"


def _extract_resolver() -> str:
    tree = ast.parse(SERVER.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_partial_page_id":
            return ast.unparse(node)
    raise AssertionError("_resolve_partial_page_id not found")


class _MockBase:
    def __init__(self, pages):
        self._pages = pages

    def api_request(self, method, endpoint, params=None, **kwargs):
        if endpoint == "/pages/":
            return {"results": self._pages}
        raise AssertionError(f"unexpected endpoint {endpoint}")


def _run_resolver(pages, page_id):
    from typing import Optional  # noqa: F401 — used by the extracted type hint
    ns = {"base": _MockBase(pages), "Optional": Optional}
    exec(_extract_resolver(), ns)
    return ns["_resolve_partial_page_id"](page_id)


class PartialPageIdResolutionTests(SimpleTestCase):
    def test_unique_prefix_resolves_to_full_uuid(self):
        pages = [
            {"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "Books Overview"},
            {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "title": "Other"},
        ]
        self.assertEqual(
            _run_resolver(pages, "1845935e"),
            "1845935e-c5aa-450d-9bf9-73544100a4be",
        )

    def test_ambiguous_prefix_returns_false(self):
        pages = [
            {"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "A"},
            {"id": "1845935e-1111-2222-3333-444444444444", "title": "B"},
        ]
        self.assertIs(_run_resolver(pages, "1845935e"), False)

    def test_no_match_returns_none(self):
        pages = [
            {"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "A"},
        ]
        self.assertIsNone(_run_resolver(pages, "ffffffff"))

    def test_short_prefix_returns_none(self):
        pages = [{"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "A"}]
        # Prefixes shorter than 4 chars are not resolved (avoid huge scans).
        self.assertIsNone(_run_resolver(pages, "18"))

    def test_case_insensitive_prefix(self):
        pages = [{"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "A"}]
        self.assertEqual(
            _run_resolver(pages, "1845935E"),
            "1845935e-c5aa-450d-9bf9-73544100a4be",
        )

    def test_resolves_via_single_server_side_prefix_query(self):
        # WIKI-85: resolution is a SINGLE server-side query (`/pages/?prefix=`),
        # not a Python walk of every paginated page (which exceeded the 30s MCP
        # timeout on 1400+ pages). The mock asserts exactly one /pages/ call with
        # the prefix param, and the resolver classifies the server-filtered
        # results (the backend already applied the prefix filter).
        class _SingleQueryMockBase:
            def __init__(self):
                self._calls = 0

            def api_request(self, method, endpoint, params=None, **kwargs):
                if endpoint != "/pages/":
                    raise AssertionError(f"unexpected endpoint {endpoint}")
                self._calls += 1
                self._params = params or {}
                return {
                    "results": [
                        {"id": "1845935e-c5aa-450d-9bf9-73544100a4be", "title": "B"},
                    ],
                }

        mock = _SingleQueryMockBase()
        from typing import Optional  # noqa: F401
        ns = {"base": mock, "Optional": Optional}
        exec(_extract_resolver(), ns)
        result = ns["_resolve_partial_page_id"]("1845935e")
        self.assertEqual(result, "1845935e-c5aa-450d-9bf9-73544100a4be")
        # Exactly ONE request, with the server-side prefix filter.
        self.assertEqual(mock._calls, 1)
        self.assertEqual(mock._params.get("prefix"), "1845935e")
