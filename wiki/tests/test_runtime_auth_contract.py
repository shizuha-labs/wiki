"""Exercise the actual CI executable against stale overlays and real files."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase

SCRIPT = Path(__file__).resolve().parents[2] / '.forgejo/scripts/runtime-auth-contract.py'


class RuntimeAuthContractTests(TestCase):
    def run_contract(self, operation, *, data=None, expected=None, cwd=None):
        command = [sys.executable, str(SCRIPT), operation]
        if expected is not None:
            command += ['--expected', json.dumps(expected)]
        return subprocess.run(command, input=json.dumps(data) if data is not None else None,
                              text=True, capture_output=True, cwd=cwd, timeout=10)

    def test_retired_auth_mount_is_removed_without_changing_other_workloads(self):
        obsolete = {'name': 'shizuha-auth-hotfix', 'mountPath': '/app/shizuha_auth.py', 'subPath': 'shizuha_auth.py'}
        media = {'name': 'media', 'mountPath': '/app/media'}
        containers = [{'name': 'shizuha-wiki', 'image': 'reviewed', 'volumeMounts': [obsolete, media]},
                      {'name': 'sidecar', 'volumeMounts': [obsolete]}]
        result = self.run_contract('sanitize', data=containers)
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = json.loads(result.stdout)
        self.assertEqual(rendered[0], {'name': 'shizuha-wiki', 'image': 'reviewed', 'volumeMounts': [media]})
        self.assertEqual(rendered[1], containers[1])
        self.assertEqual(self.run_contract('sanitize', data=rendered).stdout, result.stdout)

    def test_exact_files_pass_but_runtime_overlay_and_missing_file_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('shizuha_auth.py', 'shizuha_revocation.py'):
                (root / name).write_text('reviewed ' + name)
            expected = json.loads(self.run_contract('fingerprint', cwd=root).stdout)
            self.assertEqual(self.run_contract('verify', data=expected, expected=expected).returncode, 0)
            (root / 'shizuha_auth.py').write_text('old verifier without revocation')
            stale = json.loads(self.run_contract('fingerprint', cwd=root).stdout)
            self.assertNotEqual(self.run_contract('verify', data=stale, expected=expected).returncode, 0)
            (root / 'shizuha_revocation.py').unlink()
            self.assertNotEqual(self.run_contract('fingerprint', cwd=root).returncode, 0)

    def test_empty_or_partial_evidence_never_passes(self):
        self.assertNotEqual(self.run_contract('verify', data={}, expected={}).returncode, 0)
        self.assertNotEqual(self.run_contract('verify', data={}, expected={'shizuha_auth.py': 'x'}).returncode, 0)

    def test_workflow_uses_sanitizer_and_verifies_each_rolled_replica(self):
        workflow = (SCRIPT.parents[2] / '.forgejo/workflows/deploy.yml').read_text()
        self.assertIn('runtime-auth-contract.py sanitize', workflow)
        self.assertIn('runtime-auth-contract.py fingerprint', workflow)
        self.assertIn('python - fingerprint < .forgejo/scripts/runtime-auth-contract.py', workflow)
        self.assertIn('runtime-auth-contract.py verify --expected', workflow)
