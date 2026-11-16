"""Durable GitHub Deployments receipts; local documents are never authority."""
from __future__ import annotations
import datetime as dt
from contracts import API_VERSION, fail, validate_record


def environment(target_id, component_id):
    return f'cloudopsworks/{target_id}/{component_id}'


class ReceiptStore:
    def __init__(self, github, repository, automation_id):
        if not automation_id or not str(automation_id).isdigit():
            fail('automation-identity', 'trusted deployment automation numeric ID is required')
        self.github, self.repository, self.automation_id = github, repository, str(automation_id)

    def attempts(self, target_id, component_id):
        name = environment(target_id, component_id)
        records = self.github.pages('/deployments?environment=' + name)
        found = []
        for deployment in records:
            payload = deployment.get('payload', {})
            if isinstance(payload, str):
                # API historically returns strings for caller-provided strings;
                # this implementation only creates typed JSON object payloads.
                continue
            if str(deployment.get('creator', {}).get('id')) != self.automation_id:
                continue
            if deployment.get('environment') != name or payload.get('apiVersion') != API_VERSION or payload.get('repository') != self.repository or payload.get('targetId') != target_id or payload.get('componentId') != component_id:
                continue
            statuses = self.github.pages(f'/deployments/{deployment["id"]}/statuses')
            trusted = [s for s in statuses if str(s.get('creator', {}).get('id')) == self.automation_id]
            status = max(trusted, key=lambda s: int(s['id']), default=None)
            found.append({'deployment': deployment, 'payload': payload, 'status': status})
        return sorted(found, key=lambda a: int(a['deployment']['id']), reverse=True)

    def convergence(self, request):
        attempts = self.attempts(request['target']['id'], request['componentId'])
        success = next((a for a in attempts if a['status'] and a['status']['state'] == 'success'), None)
        previous = str(success['deployment']['id']) if success else None
        if attempts and (not attempts[0]['status'] or attempts[0]['status']['state'] not in ('success', 'inactive')):
            return 'retry-unresolved', previous
        if not success:
            return 'first-deploy', None
        payload = success['payload']
        if payload.get('artifactDigest') != request['artifact']['digest']:
            return 'artifact-changed', previous
        if payload.get('targetConfigDigest') != request['target']['configDigest']:
            return 'target-changed', previous
        if payload.get('idempotencyKey') != request['idempotencyKey']:
            fail('receipt-binding', 'successful receipt has inconsistent idempotency identity')
        return None, previous

    def begin(self, request):
        payload = {'apiVersion': API_VERSION, 'repository': self.repository,
                   'targetId': request['target']['id'], 'componentId': request['componentId'],
                   'artifactDigest': request['artifact']['digest'], 'targetConfigDigest': request['target']['configDigest'],
                   'releaseVersion': request['releaseVersion'], 'idempotencyKey': request['idempotencyKey']}
        deployment = self.github.repo('POST', '/deployments', {'ref': request['releaseHeadSha'],
            'environment': environment(request['target']['id'], request['componentId']), 'auto_merge': False,
            'required_contexts': [], 'transient_environment': False, 'production_environment': request['target']['environment'] == 'prod',
            'payload': payload, 'description': 'CloudOpsWorks immutable component deployment'})
        if not deployment or not str(deployment.get('id', '')).isdigit():
            fail('receipt-store', 'GitHub deployment creation did not return an identity')
        self.status(deployment['id'], 'in_progress')
        return deployment

    def status(self, deployment_id, state, url=None):
        payload = {'state': state, 'auto_inactive': False, 'description': 'CloudOpsWorks ' + state}
        if url and state == 'success':
            payload['environment_url'] = url
        status = self.github.repo('POST', f'/deployments/{deployment_id}/statuses', payload)
        if not status or not str(status.get('id', '')).isdigit():
            fail('receipt-store', 'GitHub deployment status was not durably stored')
        return status

    def finish(self, deployment, request, result):
        validate_record(result)
        if result['status'] != 'succeeded':
            self.status(deployment['id'], 'failure')
            return None
        status = self.status(deployment['id'], 'success', result['resourceUrl'])
        # Re-read actual API records; do not mint receipt from a local success file.
        attempts = self.attempts(request['target']['id'], request['componentId'])
        if not attempts or str(attempts[0]['deployment']['id']) != str(deployment['id']) or not attempts[0]['status'] or str(attempts[0]['status']['id']) != str(status['id']) or attempts[0]['status']['state'] != 'success':
            fail('receipt-unverified', 'deployment success status read-back failed or was superseded')
        receipt = {'apiVersion': API_VERSION, 'kind': 'DeploymentReceipt', 'repository': self.repository,
                   'componentId': request['componentId'], 'targetId': request['target']['id'],
                   'releaseVersion': request['releaseVersion'], 'artifactDigest': request['artifact']['digest'],
                   'targetConfigDigest': request['target']['configDigest'], 'idempotencyKey': request['idempotencyKey'],
                   'githubDeploymentId': str(deployment['id']), 'githubStatusId': str(status['id']), 'status': 'success',
                   'observedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')}
        return validate_record(receipt)
