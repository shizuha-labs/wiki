"""Execute the image's real static-collection prefix with disposable settings."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest


class StaticBuildEnvironmentTests(unittest.TestCase):
    def test_static_collection_supplies_only_process_local_build_credentials(self):
        root = Path(__file__).resolve().parents[2]
        lines = [line.removeprefix('RUN ') for line in (root / 'Dockerfile').read_text().splitlines()
                 if line.startswith('RUN ') and 'manage.py collectstatic' in line]
        self.assertEqual(len(lines), 1)
        self.assertNotIn('||', lines[0])
        tokens = shlex.split(lines[0])
        env = {name: os.environ[name] for name in ('PATH', 'HOME', 'LANG') if name in os.environ}
        while tokens and '=' in tokens[0]:
            name, value = tokens.pop(0).split('=', 1)
            env[name] = value
        self.assertEqual(tokens[:3], ['python', 'manage.py', 'collectstatic'])
        result = subprocess.run([sys.executable, *tokens[1:], '--dry-run'], cwd=root,
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
