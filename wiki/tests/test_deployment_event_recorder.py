"""PLAT-6008 — the wiki deploy lane must publish a correlated DeploymentEvent.

`shizuha-labs/wiki` had recorded zero DeploymentEvents ever (positive control:
`shizuha-labs/hive` returned 100 on the identical query), so the armed PLS-675 /
PLAT-1351 v4 close gate rejected every wiki live-acceptance task with
`missing_correlated_deploy_event` no matter how complete its QA evidence was.
The consumer half of the gate was enforcing while the producer half for this repo
was never wired. This mirrors the connect/drive port done under PLAT-5852.

These tests exercise the recorder itself (dry-run contract, convergence negative
control, and the live command boundary with fake `kubectl`/`curl`) plus the
workflow wiring, so a future edit cannot silently drop the recording step or move
it ahead of rollout convergence.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECORDER = ROOT / ".forgejo" / "scripts" / "record-deployment-event.sh"
CASE = {
    "project": "WIKI",
    "repo": "shizuha-labs/wiki",
    "service": "shizuha-wiki-frontend",
    "target": "shizuha-wiki-frontend",
    "image": "registry/shizuha-wiki-frontend:test",
    "surfaces": "/wiki/,/wiki/spaces",
}


class DeploymentEventRecorderTests(unittest.TestCase):
    def _run(self, **overrides):
        env = {
            **os.environ,
            "DEPLOYMENT_EVENT_DRY_RUN": "1",
            "DEPLOYMENT_EVENT_PR_NUMBER": "46",
            "GITHUB_REPOSITORY": CASE["repo"],
            "GITHUB_SHA": "a" * 40,
            "GITHUB_REF_NAME": "main",
            "GITHUB_RUN_ID": "123",
        }
        # The recorder prefers $FORGEJO_TOKEN (broker agents). CI runner shells
        # may already export it, which would make the fake-secret 404 tests
        # non-hermetic. Clear it unless the test intentionally injects one.
        env.pop("FORGEJO_TOKEN", None)
        env.update(overrides)
        return subprocess.run(
            [
                str(RECORDER),
                CASE["project"],
                "shizuha",
                CASE["service"],
                "frontend",
                CASE["target"],
                CASE["image"],
                CASE["surfaces"],
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    def _fake_live_path(self, **overrides):
        """Run the non-dry recorder boundary with deterministic command fakes."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp)
            (fake_bin / "kubectl").write_text(
                """#!/usr/bin/env python3
import base64
import json
import os
import sys

args = sys.argv[1:]
if "secret" in args:
    secret = args[args.index("secret") + 1]
    query = args[-1]
    if secret == "forgejo-token" and os.environ.get("FAKE_FORGEJO_TOKEN_404") == "1":
        sys.stderr.write('Error from server (NotFound): secrets "forgejo-token" not found')
        sys.exit(1)
    values = {
        ("forgejo-token", "password"): "forgejo-test-token",
        ("pulse-api-token", "username"): "pulse-recorder",
        ("pulse-api-token", "password"): "pulse-test-password",
    }
    field = "username" if "username" in query else "password"
    sys.stdout.write(base64.b64encode(values[(secret, field)].encode()).decode())
elif any(value.startswith("deployment/") for value in args):
    print(json.dumps({
        "metadata": {"generation": 7},
        "spec": {"replicas": 2},
        "status": {
            "readyReplicas": 2,
            "updatedReplicas": 2,
            "availableReplicas": 2,
            "observedGeneration": 7,
        },
    }))
else:
    raise SystemExit("unexpected kubectl call: " + " ".join(args))
"""
            )
            (fake_bin / "curl").write_text(
                """#!/usr/bin/env python3
import json
import os
import sys

url = sys.argv[-1]
if "/commits/" in url and url.endswith("/pull"):
    print(json.dumps({
        "number": 46,
        "merged": True,
        "merge_commit_sha": os.environ["FAKE_MERGE_SHA"],
    }))
elif url.endswith("/api/auth/login/"):
    print(json.dumps({"tokens": {"access": "pulse-test-access"}}))
elif url.endswith("/api/deployment-events/ingest/"):
    print(json.dumps({
        "id": "deployment-event-1",
        "state": "smoke_passed",
        "pr_numbers": [46],
        "source_task_keys": json.loads(
            os.environ.get("FAKE_SOURCE_TASK_KEYS", '["PLAT-6008"]')
        ),
    }))
else:
    raise SystemExit("unexpected curl call: " + url)
"""
            )
            for command in (fake_bin / "kubectl", fake_bin / "curl"):
                command.chmod(0o755)
            env = {
                "DEPLOYMENT_EVENT_DRY_RUN": "0",
                "FAKE_MERGE_SHA": "a" * 40,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }
            env.update(overrides)
            return self._run(**env)

    def test_dry_run_emits_exact_merge_pr_and_replica_provenance(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project_key"], CASE["project"])
        self.assertEqual(payload["repo"], CASE["repo"])
        self.assertEqual(payload["commit_sha"], "a" * 40)
        self.assertEqual(payload["pr_numbers"], [46])
        self.assertEqual(payload["state"], "smoke_passed")
        self.assertEqual(payload["smoke_result"], "passed")
        self.assertEqual(payload["metadata"]["qa_surfaces"], CASE["surfaces"].split(","))
        self.assertTrue(payload["metadata"]["replicas_ready"])
        self.assertEqual(payload["metadata"]["ready_replicas"], 2)
        self.assertEqual(
            payload["metadata"]["truth_contract"],
            "origin-rollout-deployment-event-v1",
        )

    def test_replica_mismatch_negative_control_fails_loud(self):
        result = self._run(DEPLOYMENT_EVENT_READY_REPLICAS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not converged", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_live_command_boundary_requires_exact_pr_and_task_correlation(self):
        result = self._fake_live_path()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pr_numbers=[46]", result.stdout)
        self.assertIn("source_task_keys=['PLAT-6008']", result.stdout)

        # The Forgejo inline PR-provenance step is defense-in-depth only:
        # Pulse correlates the exact merge SHA to linked-PR tuples at ingest
        # (shizuha-tasks#240) and fail-louds on no correlation. So an exact
        # merge mismatch degrades to a warning + PR_NUMBER=0 rather than
        # red-lighting the whole deploy (PLAT-5852 run 478 red on a missing
        # origin/forgejo-token). The authoritative Pulse ingest gate (no-task
        # correlation) still fails loud.
        wrong_merge = self._fake_live_path(FAKE_MERGE_SHA="b" * 40)
        self.assertEqual(wrong_merge.returncode, 0, wrong_merge.stderr)
        self.assertIn("PR provenance unavailable", wrong_merge.stderr)
        # Pulse-derived correlation, not the inline Forgejo PR number.
        self.assertIn("pr_numbers=[46]", wrong_merge.stdout)

        no_task = self._fake_live_path(FAKE_SOURCE_TASK_KEYS="[]")
        self.assertNotEqual(no_task.returncode, 0)
        self.assertIn("did not correlate to any linked Pulse task", no_task.stderr)

    def test_missing_forgejo_token_degrades_but_pulse_gate_still_fails_loud(self):
        # No readable forgejo-token (the run 478 failure: secrets
        # "forgejo-token" NotFound in origin): inline provenance is skipped with
        # a warning and PR_NUMBER=0; convergence + Pulse task correlation still
        # gate the transaction. The fake kubectl 404s the forgejo secret read
        # (FAKE_FORGEJO_TOKEN_404) but still returns the pulse secret + deployment.
        result = self._fake_live_path(FAKE_FORGEJO_TOKEN_404="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Forgejo API token unavailable", result.stderr)
        self.assertIn("skipping inline PR provenance", result.stderr)
        # Pulse-derived correlation still reported even with no inline PR.
        self.assertIn("pr_numbers=[46]", result.stdout)

        no_task = self._fake_live_path(
            FAKE_FORGEJO_TOKEN_404="1", FAKE_SOURCE_TASK_KEYS="[]"
        )
        self.assertNotEqual(no_task.returncode, 0)
        self.assertIn("did not correlate to any linked Pulse task", no_task.stderr)

    def test_recorder_is_executable(self):
        # The workflows invoke the script directly (not via `bash <path>`), so a
        # lost exec bit is a silent deploy-lane break rather than a test failure.
        self.assertTrue(os.access(RECORDER, os.X_OK), f"{RECORDER} is not executable")

    def test_both_deploy_workflows_record_only_after_rollout_verification(self):
        for name in ("deploy.yml", "deploy-frontend.yml"):
            source = (ROOT / ".forgejo" / "workflows" / name).read_text()
            self.assertEqual(source.count("record-deployment-event.sh"), 1)
            self.assertLess(
                source.rfind("kubectl rollout status"),
                source.index("record-deployment-event.sh"),
                name,
            )
            self.assertIn("if ! .forgejo/scripts/record-deployment-event.sh", source)
            self.assertIn("rollout succeeded but DeploymentEvent recording failed", source)
            # The deployed service's own Pulse project key, not the platform key
            # that carries the pipeline defect.
            self.assertIn("WIKI shizuha shizuha-wiki", source)


if __name__ == "__main__":
    unittest.main()
