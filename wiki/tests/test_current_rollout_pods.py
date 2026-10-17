import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.forgejo/scripts/current-rollout-pods.py'
SPEC = importlib.util.spec_from_file_location('current_rollout_pods', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
IMAGE = 'localhost:30500/shizuha-wiki:wiki-11c1c89'


class CurrentRolloutPodsTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {
            'metadata': {'name': 'shizuha-wiki', 'uid': 'deployment-uid', 'generation': 221,
                         'annotations': {'deployment.kubernetes.io/revision': '150'}},
            'spec': {'replicas': 2, 'template': {'spec': {'containers': [
                {'name': 'shizuha-wiki', 'image': IMAGE}]}}},
            'status': {'observedGeneration': 221, 'replicas': 2, 'updatedReplicas': 2,
                       'readyReplicas': 2, 'availableReplicas': 2},
        }
        self.replica_set = {
            'metadata': {'name': 'current-rs', 'uid': 'rs-uid',
                         'annotations': {'deployment.kubernetes.io/revision': '150'},
                         'ownerReferences': [self.owner('Deployment', self.deployment)]},
            'spec': copy.deepcopy(self.deployment['spec']),
        }
        self.replica_sets = {'items': [self.replica_set]}
        self.pods = {'items': [self.pod('current-a'), self.pod('current-b')]}

    def owner(self, kind, parent):
        return {'apiVersion': 'apps/v1', 'kind': kind, 'controller': True,
                'uid': parent['metadata']['uid'], 'name': parent['metadata']['name']}

    def pod(self, name):
        return {
            'metadata': {'name': name, 'uid': name + '-uid',
                         'ownerReferences': [self.owner('ReplicaSet', self.replica_set)]},
            'spec': copy.deepcopy(self.deployment['spec']['template']['spec']),
            'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]},
        }

    def select(self):
        return MODULE.current_rollout_pods(self.deployment, self.replica_sets, self.pods, IMAGE)

    def test_exact_ready_current_rollout_excludes_old_terminating_alienware_replica(self):
        stale = self.pod('superseded-alienware')
        stale['metadata']['ownerReferences'][0]['uid'] = 'old-rs-uid'
        stale['metadata']['deletionTimestamp'] = '2026-09-22T03:00:00Z'
        self.pods['items'].append(stale)
        self.assertEqual(self.select(), ['current-a', 'current-b'])

    def test_matching_labels_do_not_admit_jobs_or_foreign_owner_uids(self):
        for field, value in [('kind', 'Job'), ('uid', 'foreign'), ('apiVersion', 'custom/v1'),
                             ('controller', False), ('name', 'recreated-rs')]:
            with self.subTest(field=field):
                unrelated = self.pod('unrelated')
                unrelated['metadata']['ownerReferences'][0][field] = value
                self.pods['items'].append(unrelated)
                self.assertEqual(self.select(), ['current-a', 'current-b'])
                self.pods['items'].pop()

    def test_unhealthy_current_pod_fails_instead_of_being_filtered_out(self):
        for status in [{'phase': 'Pending'}, {'phase': 'Succeeded'},
                       {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'False'}]},
                       {'phase': 'Running'}]:
            with self.subTest(status=status):
                self.pods['items'][0]['status'] = status
                with self.assertRaises(ValueError):
                    self.select()

    def test_missing_extra_or_only_terminating_current_replica_fails_coverage(self):
        original = copy.deepcopy(self.pods)
        for mode in ['missing', 'extra', 'terminating']:
            self.pods = copy.deepcopy(original)
            if mode == 'missing':
                self.pods['items'].pop()
            elif mode == 'extra':
                self.pods['items'].append(self.pod('extra'))
            else:
                self.pods['items'][0]['metadata']['deletionTimestamp'] = 'now'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.select()

    def test_rollout_image_must_match_deployment_replicaset_and_every_pod(self):
        for spec in [self.deployment['spec']['template']['spec'],
                     self.replica_set['spec']['template']['spec'], self.pods['items'][0]['spec']]:
            spec['containers'][0]['image'] = 'registry/old-image'
            with self.assertRaises(ValueError):
                self.select()
            spec['containers'][0]['image'] = IMAGE

    def test_deployment_must_have_observed_and_converged_every_intended_replica(self):
        for field in ['replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas', 'observedGeneration']:
            original = self.deployment['status'][field]
            self.deployment['status'][field] -= 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.select()
            self.deployment['status'][field] = original

    def test_current_replicaset_must_be_unambiguous_owned_and_not_terminating(self):
        original = copy.deepcopy(self.replica_sets)
        for mode in ['foreign-owner', 'wrong-revision', 'ambiguous', 'terminating', 'wrong-count']:
            self.replica_sets = copy.deepcopy(original)
            current = self.replica_sets['items'][0]
            if mode == 'foreign-owner':
                current['metadata']['ownerReferences'][0]['uid'] = 'other'
            elif mode == 'wrong-revision':
                current['metadata']['annotations']['deployment.kubernetes.io/revision'] = '149'
            elif mode == 'ambiguous':
                self.replica_sets['items'].append(copy.deepcopy(current))
            elif mode == 'terminating':
                current['metadata']['deletionTimestamp'] = 'now'
            else:
                current['spec']['replicas'] = 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.select()

    def test_real_cli_fails_closed_then_recovers_from_fresh_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kubectl = root / 'kubectl'
            kubectl.write_text('#!/usr/bin/env python3\nimport os,sys,pathlib\n'
                               'print((pathlib.Path(os.environ["SNAPSHOTS"]) / (sys.argv[2]+".json")).read_text())\n')
            kubectl.chmod(0o755)
            env = {**os.environ, 'PATH': directory + os.pathsep + os.environ['PATH'], 'SNAPSHOTS': directory}
            for filename, value in [('deploy', self.deployment), ('rs', self.replica_sets)]:
                (root / (filename + '.json')).write_text(json.dumps(value))
            for phase, expected in [('Pending', 1), ('Running', 0)]:
                self.pods['items'][0]['status']['phase'] = phase
                (root / 'pods.json').write_text(json.dumps(self.pods))
                result = subprocess.run(['python3', str(SCRIPT), '--image', IMAGE], env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [] if expected else ['current-a', 'current-b'])
            (root / 'pods.json').write_text('not JSON')
            result = subprocess.run(['python3', str(SCRIPT), '--image', IMAGE], env=env,
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_workflow_consumes_fail_closed_selector_before_storage_exec_and_success_stamp(self):
        workflow = (ROOT / '.forgejo/workflows/deploy.yml').read_text()
        selector = workflow.index('PODS="$(python3 .forgejo/scripts/current-rollout-pods.py')
        storage = workflow.index('kubectl exec -n shizuha "${POD}" -- python manage.py check_attachment_storage')
        stamp = workflow.index('kubectl annotate -n shizuha deploy/shizuha-wiki shizuha.io/last-successful-sha=')
        self.assertLess(selector, storage)
        self.assertLess(storage, stamp)
        self.assertIn('--image "localhost:30500/shizuha-wiki:${TAG}"', workflow)
