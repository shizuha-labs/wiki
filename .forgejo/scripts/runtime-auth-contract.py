#!/usr/bin/env python3
"""Retire the obsolete Wiki auth overlay and verify the delivered auth code."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

FILES = ('shizuha_auth.py', 'shizuha_revocation.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('sanitize', 'fingerprint', 'verify'))
    parser.add_argument('--expected')
    args = parser.parse_args()
    if args.operation == 'sanitize':
        containers = json.load(sys.stdin)
        for container in containers:
            if container['name'] == 'shizuha-wiki':
                # This retired file overlay predates the image's canonical
                # verifier. Preserve every unrelated mount and container.
                container['volumeMounts'] = [
                    mount for mount in container.get('volumeMounts', [])
                    if not (mount.get('name') == 'shizuha-auth-hotfix'
                            and mount.get('mountPath') == '/app/shizuha_auth.py')
                ]
        print(json.dumps(containers))
    elif args.operation == 'fingerprint':
        print(json.dumps({name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                          for name in FILES}, sort_keys=True))
    else:
        expected = json.loads(args.expected)
        actual = json.load(sys.stdin)
        if set(expected) != set(FILES) or actual != expected:
            raise SystemExit('Runtime authentication files differ from the reviewed release')
        print('Runtime authentication files match the reviewed release')


if __name__ == '__main__':
    main()
