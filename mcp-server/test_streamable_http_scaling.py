"""Regression contracts for the fleet-facing Wiki MCP transport."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamableHttpScalingTests(unittest.TestCase):
    def test_wiki_mcp_uses_stateless_json_responses(self):
        tree = ast.parse((ROOT / "mcp-server" / "wiki_server.py").read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FastMCP"
        ]
        self.assertEqual(len(calls), 1)
        keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        for setting in ("stateless_http", "json_response"):
            self.assertIn(setting, keywords)
            self.assertIsInstance(keywords[setting], ast.Constant)
            self.assertIs(keywords[setting].value, True)

    def test_mcp_dependency_cannot_float_into_v2(self):
        for manifest in ("requirements.txt", "mcp-server/requirements.txt"):
            with self.subTest(manifest=manifest):
                requirements = (ROOT / manifest).read_text().splitlines()
                mcp = [
                    line.strip()
                    for line in requirements
                    if line.strip().startswith("mcp")
                ]
                self.assertEqual(mcp, ["mcp>=1.28.1,<2"])

    def test_release_patch_carries_oom_safe_resources(self):
        workflow = (ROOT / ".forgejo" / "workflows" / "deploy.yml").read_text()
        self.assertIn('"requests":{"cpu":"200m","memory":"768Mi"}', workflow)
        self.assertIn('"limits":{"cpu":"1","memory":"2Gi"}', workflow)


if __name__ == "__main__":
    unittest.main()
