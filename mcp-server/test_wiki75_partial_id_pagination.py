"""WIKI-85 regression: _resolve_partial_page_id uses a single server-side query.

WIKI-75 paginated /pages/ in Python (20/page; page_size is capped and ignored
by the backend), so resolving a prefix against 1400+ pages took ~71 sequential
requests and exceeded the 30s MCP timeout on every lookup (WIKI-85). The fix
moves prefix resolution to ONE server-side query: the resolver sends
`/pages/?prefix=<prefix>` and the backend filters on the UUID prefix (Cast +
startswith). This test pins the new single-query behavior: the resolver makes
exactly one request with the prefix param and classifies the server-filtered
results (unique → full UUID, multiple → ambiguous False, none → None).
"""
import importlib.util
import os
import sys
from unittest import TestCase, mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.environ.setdefault("SHIZUHA_WIKI_URL", "https://wiki.example.test")

# wiki_server.py constructs a module-level ShizuhaMCPBase that requires an API
# URL. The CI test job does not set SHIZUHA_WIKI_URL/SHIZUHA_BASE_URL, so set a
# dummy value before import to avoid a ValueError during module load.
os.environ.setdefault("SHIZUHA_WIKI_URL", "http://localhost:8013")
os.environ.setdefault("SHIZUHA_WIKI_JWT_TOKEN", "test")

# Import wiki_server without executing its module-level MCP bootstrap.
spec = importlib.util.spec_from_file_location(
    "wiki_server_test", os.path.join(_HERE, "wiki_server.py"),
)
wiki = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wiki)


def _server_filtered(ids):
    """A server-side /pages/?prefix= response (backend already filtered)."""
    return {
        "count": len(ids),
        "next": None,
        "previous": None,
        "results": [{"id": i, "title": f"page {i}"} for i in ids],
    }


class Wiki75PartialIdPaginationTests(TestCase):
    def test_prefix_beyond_first_page_resolves(self):
        """A page beyond the first 20 resolves — the backend filtered it."""
        target = "1845935e-c5aa-450d-9bf9-73544100a4be"
        calls = []

        def fake_api_request(method, endpoint, **kwargs):
            calls.append((method, endpoint, kwargs.get("params", {})))
            return _server_filtered([target])

        with mock.patch.object(wiki.base, "api_request", side_effect=fake_api_request):
            result = wiki._resolve_partial_page_id("1845935e")

        self.assertEqual(result, target)
        # Exactly ONE request, with the server-side prefix filter.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2].get("prefix"), "1845935e")

    def test_ambiguous_prefix_across_pages_returns_false(self):
        """Two pages matching the same prefix => ambiguous False."""
        p1 = "abcd0001-0000-4000-8000-000000000000"
        p2 = "abcd0002-0000-4000-8000-000000000000"

        def fake_api_request(method, endpoint, **kwargs):
            return _server_filtered([p1, p2])

        with mock.patch.object(wiki.base, "api_request", side_effect=fake_api_request):
            result = wiki._resolve_partial_page_id("abcd")

        self.assertIs(result, False)

    def test_no_match_returns_none(self):
        """No page matches the prefix => None."""
        def fake_api_request(method, endpoint, **kwargs):
            return _server_filtered([])

        with mock.patch.object(wiki.base, "api_request", side_effect=fake_api_request):
            result = wiki._resolve_partial_page_id("zzzz9999")

        self.assertIsNone(result)

    def test_short_prefix_returns_none(self):
        """Prefixes shorter than 4 chars are not resolved (no request sent)."""
        with mock.patch.object(wiki.base, "api_request") as mock_api:
            result = wiki._resolve_partial_page_id("abc")
        self.assertIsNone(result)
        mock_api.assert_not_called()
