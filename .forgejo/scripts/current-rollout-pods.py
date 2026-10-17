import argparse
import json
import subprocess
import sys


SELECTOR = 'app.kubernetes.io/name=shizuha-wiki,app.kubernetes.io/component=backend'
CONTAINER = 'shizuha-wiki'


def owned_by(resource, kind, parent):
    owners = [owner for owner in resource['metadata'].get('ownerReferences', [])
              if owner.get('controller') is True]
    expected = {
        'apiVersion': 'apps/v1', 'kind': kind,
        'name': parent['metadata']['name'], 'uid': parent['metadata']['uid'],
    }
    return len(owners) == 1 and all(owners[0].get(key) == value for key, value in expected.items())


def image_matches(spec, expected_image):
    containers = [container for container in spec.get('containers', [])
                  if container.get('name') == CONTAINER]
    return len(containers) == 1 and containers[0].get('image') == expected_image


def current_rollout_pods(deployment, replica_sets, pods, expected_image):
    desired = deployment['spec'].get('replicas', 1)
    status = deployment.get('status', {})
    if (not isinstance(desired, int) or desired < 1
            or deployment['metadata'].get('deletionTimestamp')
            or status.get('observedGeneration', 0) < deployment['metadata']['generation']
            or any(status.get(field, 0) != desired for field in
                   ['replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas'])
            or not image_matches(deployment['spec']['template']['spec'], expected_image)):
        raise ValueError('wiki Deployment has not converged on the intended image and replicas')
    revision = deployment['metadata'].get('annotations', {}).get('deployment.kubernetes.io/revision')
    current = [replica_set for replica_set in replica_sets['items']
               if owned_by(replica_set, 'Deployment', deployment)
               and revision and replica_set['metadata'].get('annotations', {}).get(
                   'deployment.kubernetes.io/revision') == revision]
    if len(current) != 1:
        raise ValueError('expected exactly one current Deployment-owned ReplicaSet')
    replica_set = current[0]
    if (replica_set['metadata'].get('deletionTimestamp')
            or replica_set['spec'].get('replicas') != desired
            or not image_matches(replica_set['spec']['template']['spec'], expected_image)):
        raise ValueError('current ReplicaSet does not match the intended rollout')
    intended = [pod for pod in pods['items'] if owned_by(pod, 'ReplicaSet', replica_set)
                and not pod['metadata'].get('deletionTimestamp')]
    if len(intended) != desired:
        raise ValueError(f'expected {desired} current nonterminating replicas, found {len(intended)}')
    for pod in intended:
        ready = any(condition.get('type') == 'Ready' and condition.get('status') == 'True'
                    for condition in pod.get('status', {}).get('conditions', []))
        if (pod.get('status', {}).get('phase') != 'Running' or not ready
                or not image_matches(pod['spec'], expected_image)):
            raise ValueError(f'intended replica {pod["metadata"]["name"]} is not Ready on the intended image')
    return sorted(pod['metadata']['name'] for pod in intended)


def main():
    parser = argparse.ArgumentParser(description='Select exactly the healthy current Wiki rollout replicas.')
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    def get_resource(*resource_args):
        result = subprocess.run(['kubectl', 'get', *resource_args, '-n', 'shizuha', '-o', 'json'],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    try:
        names = current_rollout_pods(
            get_resource('deploy', 'shizuha-wiki'),
            get_resource('rs', '-l', SELECTOR),
            get_resource('pods', '-l', SELECTOR),
            args.image,
        )
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f'::error::Wiki rollout replica verification failed: {error}', file=sys.stderr)
        return 1
    print('\n'.join(names))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
