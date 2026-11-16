"""Protected, data-only authorization for the schema-v2 IaC boundary.

The stage producer and the current privileged job are different identities.
Neither an automation actor nor a schema-valid deployment receipt is authority.
The current job must use this boundary before resolving cloud credentials.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import quote
import zipfile

from contracts import ContractError, _check, canonical_bytes, digest, load_record, validate_record
from executor import checked
from operations import StateHandleStore, _claims, validate_operation
from snapshot import materialize_snapshot
from staging import trusted_stage_bundle


STATE_MARKER = 'CLOUDOPSWORKS_STATE_V1 '
SCAN_MARKER = 'CLOUDOPSWORKS_SCAN_V1 '
MAX_LOG_BYTES = 8 * 1024 * 1024
HOST_FIELDS = {'repository', 'runId', 'runAttempt', 'event', 'ref', 'headSha',
               'workflowRef', 'workflowSha', 'sourceSha', 'blueprintSha',
               'callerPath', 'lifecycle', 'planDigest', 'manifestDigest'}
CURRENT_FIELDS = {'repository', 'runId', 'runAttempt', 'event', 'ref', 'headSha',
                  'workflowRef', 'workflowSha', 'blueprintSha', 'actor'}
STAGE_FIELDS = {'runId', 'runAttempt', 'artifactId', 'archiveDigest'}
STATE_FIELDS = {'repositoryId', 'runId', 'runAttempt', 'receiptId',
                'stateHandleDigest', 'resourceClaims', 'workflowRef',
                'workflowSha', 'sourceStage', 'sourceContext'}
CALLERS = {'main-build.yml': 'monorepo-main-build.yml',
           'pr-build.yml': 'monorepo-pr-build.yml',
           'pr-close.yaml': 'monorepo-pr-close.yml',
           'deploy.yml': 'monorepo-manual-apply.yml',
           'deploy-container.yml': 'monorepo-container.yml',
           'environment-destroy.yml': 'monorepo-operation.yml',
           'environment-unlock.yml': 'monorepo-operation.yml'}


def preview_phase_name(caller, target_id, phase, component_id=None):
    """One checked-in trusted graph authority, never a caller-provided prefix."""
    require(isinstance(target_id,str) and re.fullmatch(r'[a-z][a-z0-9-]{0,47}',target_id), 'preview-job-target')
    graph=json.loads((Path(__file__).resolve().parents[3]/'tests/monorepo/fixtures/revision_callers.json').read_text())['previewPhaseGraph']
    require(caller in graph['callerPrefixes'] and phase in graph['jobNames'],'preview-job-phase')
    template=graph['callerPrefixes'][caller]+graph['jobNames'][phase]
    if '{component}' in template:
        require(isinstance(component_id,str) and re.fullmatch(r'[a-z][a-z0-9-]{0,47}',component_id),'preview-job-component')
    return template.format(target=target_id,component=component_id)


def require(condition, code):
    if not condition:
        raise ContractError('authorization-' + code, 'Protected operation authorization failed')


def _id(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value)


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value)


def _json_cli(executor, arguments, *, data=None):
    # The only source reader is Tronador over the nonexecutable API snapshot.
    # Never expose command diagnostics, protected stdin or process output.
    try:
        value = load_record(checked(executor, ['tronador', 'components', *arguments],
                                   input=canonical_bytes(data).decode() if data is not None else None))
    except Exception:
        raise ContractError('authorization-cli', 'Protected configuration normalization failed') from None
    require(isinstance(value, dict), 'cli-result')
    return value


def _records(data, prefix):
    require(isinstance(data, bytes) and len(data) <= MAX_LOG_BYTES, 'host-log-bound')
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeError:
        raise ContractError('authorization-host-log', 'Protected job log is unavailable') from None
    pattern = re.compile(r'^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z )?' + re.escape(prefix) + r'(\{.*\})$')
    return [load_record(match.group(1)) for line in text.splitlines()
            if (match := pattern.fullmatch(line))]


def _stage_locator(value):
    require(isinstance(value, dict) and set(value) == STAGE_FIELDS
            and all(_id(value[k]) for k in ('runId', 'runAttempt', 'artifactId'))
            and _digest(value['archiveDigest']), 'stage-locator')
    return value



def _source_context(value, source_sha):
    require(isinstance(value, dict) and set(value) == {'event', 'ref', 'baseRef', 'sourceSha', 'prNumber'}
            and value['sourceSha'] == source_sha and _sha(source_sha)
            and value['event'] in ('push', 'create', 'workflow_dispatch', 'pull_request')
            and all(isinstance(value[k], str) and len(value[k]) <= 1024 for k in ('ref', 'baseRef'))
            and value['ref'].startswith(('refs/heads/', 'refs/tags/'))
            and (value['prNumber'] is None or type(value['prNumber']) is int and value['prNumber'] > 0),
            'source-context')
    return value

def state_marker(handle, entry, *, host, source_stage, source_context):
    """Return a bounded marker after durable API readback, before backend INIT.

    The caller also creates an ordinary deployment status whose log_url locates
    this CURRENT job's run/attempt. That URL is a locator, not proof. A later
    reader verifies exact protected code/job and this full digest independently.
    No backend, application values or credentials are printed by this helper.
    """
    validate_operation(handle)
    payload = entry.get('payload', {}) if isinstance(entry, dict) else {}
    require(payload.get('stateHandle') == handle and payload.get('stateHandleDigest') == digest(handle)
            and _id(str(entry.get('id', ''))), 'state-readback')
    require(isinstance(host, dict) and _id(host.get('runId')) and _id(host.get('runAttempt'))
            and _sha(host.get('workflowSha')) and isinstance(host.get('workflowRef'), str)
            and host.get('repository') == handle['origin']['repository'], 'state-host')
    _source_context(source_context, handle['origin']['sourceSha'])
    value = {'repositoryId': handle['origin']['repository']['id'], 'runId': host['runId'],
             'runAttempt': host['runAttempt'], 'receiptId': str(entry['id']),
             'stateHandleDigest': digest(handle), 'resourceClaims': _claims(payload.get('resourceClaims')),
             'workflowRef': host['workflowRef'], 'workflowSha': host['workflowSha'],
             'sourceStage': copy.deepcopy(_stage_locator(source_stage)),
             'sourceContext': copy.deepcopy(source_context)}
    return STATE_MARKER + canonical_bytes(value).decode()


def parse_state_marker(data, handle, entry, *, run_id, attempt):
    records = _records(data, STATE_MARKER)
    # One job may emit several component reservations. Match this exact receipt,
    # but reject duplicate/conflicting records instead of choosing the last one.
    records = [v for v in records if isinstance(v, dict) and v.get('receiptId') == str(entry.get('id'))]
    require(len(records) == 1, 'state-marker')
    value = records[0]
    require(set(value) == STATE_FIELDS and value.get('repositoryId') == handle['origin']['repository']['id']
            and value.get('runId') == str(run_id) and value.get('runAttempt') == str(attempt)
            and value.get('stateHandleDigest') == digest(handle)
            and value.get('resourceClaims') == _claims(entry.get('payload', {}).get('resourceClaims'))
            and _sha(value.get('workflowSha')) and isinstance(value.get('workflowRef'), str), 'state-binding')
    _stage_locator(value['sourceStage'])
    _source_context(value['sourceContext'], handle['origin']['sourceSha'])
    return value


def _job(github, run_id, attempt, name, *, completed=True):
    jobs = []
    for page in range(1, 101):
        response = github.repo('GET', f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}')
        require(isinstance(response, dict) and isinstance(response.get('jobs'), list), 'jobs')
        jobs.extend(response['jobs'])
        if len(response['jobs']) < 100:
            break
    else:
        require(False, 'jobs-bound')
    selected = [j for j in jobs if j.get('name') == name]
    require(len(selected) == 1, 'job-identity')
    job = selected[0]
    require(str(job.get('run_id')) == str(run_id) and str(job.get('run_attempt')) == str(attempt)
            and _id(str(job.get('id', ''))), 'job-attempt')
    if completed:
        require(job.get('status') == 'completed' and job.get('conclusion') == 'success', 'job-result')
    return job


def _file(github, path, sha):
    require(_sha(sha) and path.startswith('.github/workflows/') and '/' not in path.removeprefix('.github/workflows/'), 'caller-path')
    record = github.repo('GET', '/contents/' + path + '?ref=' + sha)
    require(isinstance(record, dict) and record.get('encoding') == 'base64'
            and isinstance(record.get('content'), str), 'caller-file')
    try:
        content = base64.b64decode(''.join(record['content'].splitlines()), validate=True)
    except ValueError:
        require(False, 'caller-file')
    require(0 < len(content) <= 128 * 1024 and record.get('sha') ==
            hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest(), 'caller-bytes')
    return content


def _run(github, run_id, attempt):
    require(_id(str(run_id)) and _id(str(attempt)), 'run-locator')
    run = github.repo('GET', f'/actions/runs/{run_id}/attempts/{attempt}')
    require(isinstance(run, dict) and str(run.get('id')) == str(run_id)
            and str(run.get('run_attempt')) == str(attempt) and _sha(run.get('head_sha')), 'run-attempt')
    return run


def _archive(data):
    names = {'build-plan.json', 'manifest.json', 'source-origin.json', 'scanners.json', 'host.json'}
    require(isinstance(data, bytes) and len(data) <= 64 * 1024 * 1024, 'stage-bound')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            require(len(entries) == len(names) and {e.filename for e in entries} == names
                    and all(e.file_size <= 4 * 1024 * 1024 and not e.flag_bits & 1
                            and (e.external_attr >> 16) & 0o170000 in (0, 0o100000) for e in entries), 'stage-files')
            return {e.filename: load_record(archive.read(e)) for e in entries}
    except (zipfile.BadZipFile, RuntimeError, ValueError, OSError):
        raise ContractError('authorization-stage-archive', 'Protected stage archive is invalid') from None


def _protected_branch(github, branch):
    from owners import current_branch_policy
    record = github.repo('GET', '/branches/' + quote(branch, safe=''))
    require(isinstance(record, dict) and record.get('protected') is True
            and _sha(record.get('commit', {}).get('sha')), 'protected-branch')
    current_branch_policy(github, branch)
    return record['commit']['sha']


def _ancestor(github, older, newer):
    require(_sha(older) and _sha(newer), 'lineage')
    comparison = github.repo('GET', '/compare/' + older + '...' + newer)
    require(isinstance(comparison, dict) and comparison.get('status') in ('ahead', 'identical')
            and comparison.get('merge_base_commit', {}).get('sha') == older, 'lineage')


def _repository(github):
    repo = github.repo('GET', '')
    require(isinstance(repo, dict) and str(repo.get('full_name')) == github.repository
            and _id(str(repo.get('id', ''))) and isinstance(repo.get('default_branch'), str), 'repository')
    return repo, {'id': str(repo['id']), 'fullName': github.repository}


def _called(run, path, blueprint_sha):
    expected = 'cloudopsworks/blueprints/.github/workflows/' + path + '@v5.11.0'
    require(len([v for v in run.get('referenced_workflows', [])
                 if v.get('path') == expected and v.get('sha') == blueprint_sha]) == 1, 'called-code')


def _blueprint(github, expected):
    require(_sha(expected), 'blueprint-sha')
    ref = github.request('GET', '/repos/cloudopsworks/blueprints/git/ref/tags/v5.11.0')
    obj = ref.get('object', {}) if isinstance(ref, dict) else {}
    for _ in range(8):
        if obj.get('type') == 'commit':
            require(obj.get('sha') == expected, 'blueprint-ref')
            return
        require(obj.get('type') == 'tag' and _sha(obj.get('sha')), 'blueprint-ref')
        tagged = github.request('GET', '/repos/cloudopsworks/blueprints/git/tags/' + obj['sha'])
        obj = tagged.get('object', {}) if isinstance(tagged, dict) else {}
    require(False, 'blueprint-ref')


def scan_marker(stage, resolved, results):
    """Nonsecret completed results, emitted only by the fixed scan barrier job."""
    _stage_locator(stage)
    require(isinstance(resolved, dict) and isinstance(results, list), 'scan-result')
    document = json.loads(Path(__file__).with_name('schema').joinpath('operations-v1.schema.json').read_text())
    require(len(results) <= 2560, 'scan-bound')
    for result in results:
        _check(result, document['$defs']['ScannerResult'], '$.result', document=document)
    value = {'stageArtifactId': stage['artifactId'], 'stageArchiveDigest': stage['archiveDigest'],
             'policyDigest': digest(resolved['scanners']), 'resolvedConfigDigest': digest(resolved),
             'resultsDigest': digest(results), 'results': results}
    require(len(canonical_bytes(value)) <= 4 * 1024 * 1024, 'scan-bound')
    return SCAN_MARKER + canonical_bytes(value).decode()


def _scan_barrier(github, host, stage, resolved, plan, manifest, preview_target_id=None):
    caller = host['workflowRef'].split('@', 1)[0].rsplit('/', 1)[-1]
    prefix = {'main-build.yml': 'lifecycle / ', 'pr-build.yml': 'preview / ',
              'pr-close.yaml': 'close / lifecycle / ', 'deploy.yml': 'operation / ',
              'environment-destroy.yml': 'operation / ', 'environment-unlock.yml': 'operation / '}.get(caller)
    require(prefix is not None, 'scan-caller')
    if caller=='pr-build.yml' or caller=='pr-close.yaml' and preview_target_id is not None:
        require(isinstance(preview_target_id,str) and any(t['targetId']==preview_target_id
                for t in plan['previewPolicy']['targets']), 'scan-preview-target')
        name=preview_phase_name(caller,preview_target_id,'scan')
    else:
        require(preview_target_id is None,'scan-preview-target')
        name=prefix+'monorepo-scan-barrier'
    job = _job(github, host['runId'], host['runAttempt'], name)
    records = _records(github.repo('GET', f'/actions/jobs/{job["id"]}/logs', raw=True, limit=MAX_LOG_BYTES), SCAN_MARKER)
    require(len(records) == 1, 'scan-marker')
    value = records[0]
    fields = {'stageArtifactId', 'stageArchiveDigest', 'policyDigest', 'resolvedConfigDigest', 'resultsDigest', 'results'}
    require(isinstance(value, dict) and set(value) == fields
            and value['stageArtifactId'] == stage['artifactId']
            and value['stageArchiveDigest'] == stage['archiveDigest']
            and value['policyDigest'] == digest(resolved['scanners'])
            and value['resolvedConfigDigest'] == digest(resolved)
            and isinstance(value['results'], list) and value['resultsDigest'] == digest(value['results']), 'scan-binding')
    # Revalidate the exact closed result shape, not just its digest or the job's
    # green conclusion. The required bit is checked against current policy.
    scan_marker(stage, resolved, value['results'])
    from scanners import require_completed_gates
    return require_completed_gates(plan, manifest, resolved['scanners'], value['results'])


def _environment(github, policy, lifecycle):
    from owners import protection_preflight, reviewers
    require(policy.get('branchProtection') is True and policy.get('requiredReviewers', 0) >= 1
            and policy.get('owners') and policy.get('reviewers'),
            'source-policy')
    paths = {p.replace('/**/*', '/**') for p in policy.get('protectedSources', [])}
    require('.github/**' in paths and '.cloudopsworks/**' in paths, 'source-policy')
    protection_preflight(github, policy)
    sources = [r for r in github.pages('/rulesets') if r.get('name') == 'protected-sources']
    require(len(sources) == 1, 'source-native-protection')
    source_rule = github.repo('GET', '/rulesets/' + str(sources[0]['id']))
    actual_paths = {p.replace('/**/*', '/**') for rule in source_rule.get('rules', [])
                    if rule.get('type') == 'file_path_restriction'
                    for p in rule.get('parameters', {}).get('restricted_file_paths', [])}
    require(source_rule.get('enforcement') == 'active' and source_rule.get('target') == 'push'
            and ('**' in actual_paths or paths <= actual_paths), 'source-native-protection')
    selected = [e for e in policy['environments'] if e['name'] == lifecycle['protectedEnvironment']]
    require(len(selected) == 1, 'environment-policy')
    env = github.repo('GET', '/environments/' + quote(selected[0]['name'], safe=''))
    require(isinstance(env, dict) and env.get('deployment_branch_policy') ==
            {'protected_branches': True, 'custom_branch_policies': False}, 'environment-protection')
    rules = [r for r in env.get('protection_rules', []) if r.get('type') == 'required_reviewers']
    require(len(rules) <= 1, 'environment-reviewers')
    if selected[0]['reviewers']:
        expected = {(r['type'], r['id']) for r in reviewers(github, policy['reviewers'])}
        actual = {(r['type'], r['reviewer']['id']) for r in (rules[0].get('reviewers', []) if rules else [])}
        require(actual and actual <= expected and rules[0].get('prevent_self_review') is True,
                'environment-reviewers')
    elif rules:
        # A stronger existing gate may stay; do not mutate or silently weaken it.
        require(rules[0].get('reviewers') and rules[0].get('prevent_self_review') is True,
                'environment-reviewers')


def _current_host(github, host, repository, blueprint_sha, default_sha, *, historical=False, preview_target_id=None, continuation=False):
    require(isinstance(host, dict) and set(host) == CURRENT_FIELDS and host.get('repository') == repository
            and all(_id(host.get(k)) for k in ('runId', 'runAttempt'))
            and all(_sha(host.get(k)) for k in ('headSha', 'workflowSha', 'blueprintSha'))
            and host['blueprintSha'] == blueprint_sha and isinstance(host.get('actor'), str)
            and 0 < len(host['actor']) <= 256, 'current-host')
    run = _run(github, host['runId'], host['runAttempt'])
    require(str(run.get('repository', {}).get('id')) == repository['id']
            and run.get('event') == host['event'] and run.get('status') in ('in_progress', 'completed'),
            'current-run')
    path = run.get('path', '').split('@', 1)[0]
    caller = path.removeprefix('.github/workflows/')
    expected = CALLERS.get(caller)
    if caller in ('deploy.yml','deploy-container.yml', 'environment-destroy.yml', 'environment-unlock.yml'):
        require(host['event'] == 'workflow_dispatch', 'manual-event')
    if host['event'] == 'workflow_run' and caller == 'pr-build.yml':
        expected = 'monorepo-preview.yml'
    require(expected is not None and host['workflowRef'] == repository['fullName'] + '/' + path + '@' + host['ref'],
            'current-caller')
    _called(run, expected, blueprint_sha)
    if preview_target_id is not None:
        require(caller in ('pr-build.yml','pr-close.yaml') and not continuation,'preview-host-scope')
        preview_phase_name(caller,preview_target_id,'root')
        graph=json.loads((Path(__file__).resolve().parents[3]/'tests/monorepo/fixtures/revision_callers.json').read_text())['previewPhaseGraph']
        for reusable_path in graph['requiredReusables']:
            if reusable_path!=expected:_called(run,reusable_path,blueprint_sha)
    elif continuation:
        require(caller=='pr-close.yaml' and host['event']=='pull_request_target','closure-host-scope')
        _called(run,'monorepo-closure.yml',blueprint_sha)
    require(_file(github, path, host['workflowSha']) == _file(github, path, default_sha), 'current-caller-bytes')
    if historical:
        require(run['head_sha'] == host['headSha'], 'historical-host-head')
        return run
    if host['event'] == 'workflow_run':
        require(host['ref'].startswith('refs/heads/') and run['head_sha'] == host['headSha'], 'current-preview-host')
        branch_sha = _protected_branch(github, host['ref'].removeprefix('refs/heads/'))
        _ancestor(github, host['headSha'], branch_sha)
    elif host['event'] in ('push', 'create', 'workflow_dispatch', 'pull_request_target'):
        if host['event']=='pull_request_target':
            require(host['ref']=='refs/heads/'+github.repo('GET','')['default_branch'],'current-target-default-host')
        require(run['head_sha'] == host['headSha'], 'current-head')
        if host['ref'].startswith('refs/heads/'):
            branch_sha = _protected_branch(github, host['ref'].removeprefix('refs/heads/'))
            _ancestor(github, host['headSha'], branch_sha)
        else:
            require(host['ref'].startswith('refs/tags/'), 'current-ref')
            require(github.tag_sha(host['ref'].removeprefix('refs/tags/')) == host['headSha'], 'current-tag')
            # Branch lineage is checked against the Go-classified configured
            # protected source branches after the data-only snapshot exists.
    else:
        require(False, 'current-event')
    return run



def _tag_lineage(github, executor, root, head_sha):
    eligible = []
    for branch in github.pages('/branches?protected=true'):
        name = branch.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'(?:main|master|develop|support/[^/]+|release/[^/]+)', name):
            continue
        lifecycle = _json_cli(executor, ['lifecycle', '--workdir', str(root), '--event', 'push',
                                        '--ref', 'refs/heads/' + name, '--base-ref', '', '--json'])
        if lifecycle.get('eligible') is not True:
            continue
        sha = _protected_branch(github, name)
        comparison = github.repo('GET', '/compare/' + head_sha + '...' + sha)
        if (isinstance(comparison, dict) and comparison.get('status') in ('ahead', 'identical')
                and comparison.get('merge_base_commit', {}).get('sha') == head_sha):
            eligible.append(name)
    require(eligible, 'tag-lineage')

def verify_closure_record(github, repository, record, *, source_sha, ref, run=None):
    """Recheck a host-bound closure locator against independent merge metadata."""
    require(isinstance(record,dict) and set(record)=={'prNumber','mergeSha','baseRef'}
        and type(record['prNumber']) is int and record['prNumber']>0
        and _sha(record['mergeSha']) and record['mergeSha']==source_sha
        and isinstance(record['baseRef'],str) and 0<len(record['baseRef'])<=256
        and ref=='refs/heads/'+github.repo('GET','')['default_branch'], 'closure-record')
    pr=github.repo('GET','/pulls/'+str(record['prNumber']))
    require(isinstance(pr,dict) and pr.get('number')==record['prNumber'] and pr.get('state')=='closed'
        and pr.get('merged') is True and pr.get('merge_commit_sha')==source_sha
        and str(pr.get('base',{}).get('repo',{}).get('id'))==repository['id']
        and pr['base']['repo'].get('full_name')==repository['fullName']
        and pr['base'].get('ref')==record['baseRef'], 'closure-merge')
    if run is not None:
        associations=run.get('pull_requests',[])
        require(isinstance(associations,list) and (not associations or len(associations)==1
            and associations[0].get('number')==record['prNumber']), 'closure-run-pr')
    _ancestor(github,source_sha,_protected_branch(github,record['baseRef']))
    return pr


def _prepare(github, source_run, *, blueprint_sha, executor, engine, current_host,
             current_artifact_id=None, inspection=False, preview_target_id=None):
    repo, repository = _repository(github)
    _blueprint(github, blueprint_sha)
    default_sha = _protected_branch(github, repo['default_branch'])
    current_run = _current_host(github, current_host, repository, blueprint_sha, default_sha,
        preview_target_id=preview_target_id,continuation=current_host.get('event')=='pull_request_target' and preview_target_id is None)
    require(isinstance(source_run, dict), 'stage-run')
    run = _run(github, str(source_run.get('id')), str(source_run.get('run_attempt')))
    require(str(run.get('repository', {}).get('id')) == repository['id'], 'stage-repository')
    caller = run.get('path', '').split('@', 1)[0].removeprefix('.github/workflows/')
    require(caller in CALLERS, 'stage-caller')
    trust_sha = default_sha
    pr = None
    if run.get('event') == 'pull_request':
        prs = run.get('pull_requests', [])
        require(len(prs) == 1 and type(prs[0].get('number')) is int, 'stage-pr')
        pr = github.repo('GET', '/pulls/' + str(prs[0]['number']))
        require(isinstance(pr, dict) and str(pr.get('base', {}).get('repo', {}).get('id')) == repository['id']
                and str(pr.get('head', {}).get('repo', {}).get('id')) == repository['id'], 'stage-fork')
        trust_sha = pr['base']['sha']
        _protected_branch(github, pr['base']['ref'])
    source_caller = _file(github, '.github/workflows/' + caller, run['head_sha'])
    trusted_caller = _file(github, '.github/workflows/' + caller, trust_sha)
    binding, data = trusted_stage_bundle(github, run, caller=caller, blueprint_sha=blueprint_sha,
        source_caller_bytes=source_caller, trusted_caller_bytes=trusted_caller,
        current_artifact_id=current_artifact_id)
    stage = {key: binding[key] for key in STAGE_FIELDS}
    files = _archive(data)
    host, plan, manifest = files['host.json'], validate_record(files['build-plan.json']), validate_record(files['manifest.json'])
    require(isinstance(host, dict) and set(host) == (HOST_FIELDS|{'closure'} if run.get('event')=='pull_request_target' else HOST_FIELDS) and host.get('repository') == repository
            and host.get('runId') == str(run['id']) and host.get('runAttempt') == str(run['run_attempt'])
            and host.get('event') == run.get('event') and host.get('callerPath') == '.github/workflows/' + caller
            and host.get('sourceSha') == plan['headSha'] and host.get('blueprintSha') == blueprint_sha
            and host.get('planDigest') == digest(plan) and host.get('manifestDigest') == digest(manifest)
            and host.get('workflowRef') == repository['fullName'] + '/' + host['callerPath'] + '@' + host.get('ref', '')
            and _sha(host.get('workflowSha')) and _sha(host.get('headSha')), 'stage-host')
    require(_file(github, host['callerPath'], host['workflowSha']) == trusted_caller,
            'stage-definition')
    require(plan['kind'] == 'BuildPlan' and manifest['kind'] == 'ReleaseManifest'
            and plan['repository'] == manifest['repository'] == repository
            and plan['headSha'] == manifest['headSha'] and plan['version'] == manifest['version'], 'stage-plan')
    if run.get('event') == 'pull_request':
        require(run['head_sha'] == plan['headSha'] and plan['prNumber'] == pr['number']
                and host['ref'] == f'refs/pull/{pr["number"]}/merge', 'stage-pr-source')
        source_ref, base_ref, event = 'refs/heads/' + pr['head']['ref'], pr['base']['ref'], 'pull_request'
    elif run.get('event') in ('push', 'create', 'workflow_dispatch'):
        require(run['head_sha'] == host['headSha'] == plan['headSha'], 'stage-source')
        source_ref, base_ref, event = host['ref'], '', host['event']
    elif run.get('event') == 'pull_request_target':
        require(caller=='pr-close.yaml' and run['head_sha']==host['headSha']
            and plan['event']=='release' and plan['prNumber'] is None
            and github.tag_sha('v'+plan['version'])==plan['headSha'], 'stage-closure-tag')
        _called(run,'monorepo-closure.yml',blueprint_sha)
        verify_closure_record(github,repository,host.get('closure'),source_sha=plan['headSha'],ref=host['ref'],run=run)
        source_ref, base_ref, event = 'refs/tags/v' + plan['version'], '', 'push'
    else:
        require(False, 'stage-event')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-authorization-') as directory:
        root = Path(directory).resolve()
        origin = materialize_snapshot(github, plan['headSha'], root)
        require(files['source-origin.json'] == origin, 'source-snapshot')
        normalized = _json_cli(executor, ['validate', '--workdir', str(root), '--json'])
        resolved = normalized.get('resolved')
        require(isinstance(resolved, dict), 'resolved-configuration')
        document = json.loads(Path(__file__).with_name('schema').joinpath('operations-v1.schema.json').read_text())
        _check(resolved, document['$defs']['ResolvedConfiguration'], '$.resolved', document=document)
        if current_host['ref'].startswith('refs/tags/'):
            _tag_lineage(github, executor, root, current_host['headSha'])
        lifecycle = _json_cli(executor, ['lifecycle', '--workdir', str(root), '--event', event,
                                       '--ref', source_ref, '--base-ref', base_ref, '--json'])
        if run.get('event')=='pull_request_target':
            pr=github.repo('GET','/pulls/'+str(host['closure']['prNumber']))
            closed=_json_cli(executor,['lifecycle','--workdir',str(root),'--event','pull_request_closed',
                '--ref','refs/heads/'+pr['head']['ref'],'--base-ref',host['closure']['baseRef'],'--json'])
            require(closed.get('eligible') is True,'closure-base-policy')
    # PR source can select source/build metadata, never privileged target/owner
    # or scan policy. Normalize the independently fetched trusted BASE YAML too.
    if pr is not None:
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-base-policy-') as directory:
            root = Path(directory).resolve()
            materialize_snapshot(github, trust_sha, root)
            trusted = _json_cli(executor, ['validate', '--workdir', str(root), '--json'])['resolved']
            lifecycle = _json_cli(executor, ['lifecycle', '--workdir', str(root), '--event', event,
                                           '--ref', source_ref, '--base-ref', base_ref, '--json'])
        for key in ('targets', 'previewPolicy', 'policy', 'scanners'):
            resolved[key] = trusted[key]
    for key in ('components', 'targets', 'previewPolicy'):
        require(plan[key] == resolved[key], 'source-configuration')
    require(files['scanners.json'] == resolved['scanners'] and lifecycle == host['lifecycle']
            and lifecycle.get('eligible') is True
            and (inspection or lifecycle.get('deploymentEnabled') is True),
            'source-policy')
    _environment(github, resolved['policy'], lifecycle)
    results = None if inspection else _scan_barrier(github, current_host, stage, resolved, plan, manifest, preview_target_id)
    prepared = PreparedAuthorization(github, executor, engine, repository, stage, host,
                                 current_host, current_run, plan, manifest, resolved,
                                 lifecycle, results, inspection)
    prepared.preview_target_id=preview_target_id
    prepared._source_context = {'event': event, 'ref': source_ref, 'baseRef': host['closure']['baseRef'] if run.get('event')=='pull_request_target' else base_ref,
                                'sourceSha': plan['headSha'], 'prNumber': host['closure']['prNumber'] if run.get('event')=='pull_request_target' else plan['prNumber']}
    return prepared


def inspect_verified_context(github, source_run, *, blueprint_sha, executor, engine,
                             current_host, current_artifact_id=None, preview_target_id=None):
    """Metadata-only inspection for selecting the protected scan environment.

    This object cannot bind settings/credentials or authorize resource mutation.
    Full preparation re-fetches all evidence after the actual scan job finishes.
    """
    return _prepare(github, source_run, blueprint_sha=blueprint_sha, executor=executor,
                    engine=engine, current_host=current_host,
                    current_artifact_id=current_artifact_id, inspection=True, preview_target_id=preview_target_id)


def prepare_verified_context(github, source_run, *, blueprint_sha, executor, engine,
                             current_host, current_artifact_id=None, preview_target_id=None):
    return _prepare(github, source_run, blueprint_sha=blueprint_sha, executor=executor,
                    engine=engine, current_host=current_host,
                    current_artifact_id=current_artifact_id, preview_target_id=preview_target_id)


def _settings(executor, kind, text):
    require(isinstance(text, str) and len(text.encode()) <= 4 * 1024 * 1024, 'settings-input')
    try:
        result = load_record(checked(executor, ['tronador', 'components', 'settings', '--kind', kind], input=text))
    except Exception:
        raise ContractError('authorization-settings', 'Protected settings normalization failed') from None
    require(isinstance(result, dict), 'settings-result')
    return result




def inspect_backend_settings(backend_yaml, executor):
    """Data-only pre-acquisition selector. Identity is never inferred here."""
    return _settings(executor,'backend',backend_yaml)

def _metadata_plan(repository, source_sha, resolved, *, pr_number=None):
    # PRIVATE NONEXECUTING transport. 0.0.0 is schema padding, NOT the published
    # version. No build/stage/release/publication caller may use this helper.
    # Go operations consume only repo/head/components/targets/previewPolicy for
    # handle generation. Equivalence tests lock that nonoperative dependency.
    return validate_record({'apiVersion': 'cloudopsworks.io/v1', 'kind': 'BuildPlan',
        'repository': copy.deepcopy(repository), 'headSha': source_sha, 'baseSha': None,
        'version': '0.0.0', 'event': 'pull-request' if pr_number else 'manual',
        'prNumber': pr_number, 'components': copy.deepcopy(resolved['components']),
        'targets': copy.deepcopy(resolved['targets']), 'previewPolicy': copy.deepcopy(resolved['previewPolicy']),
        'buildSelection': [], 'removedComponents': [], 'matrix': {'include': []}, 'buildNoop': True})


def _historical_metadata(github, executor, engine, handle, host, source, source_context):
    """Re-fetch immutable historical YAML and exact host logs, not expired ZIPs."""
    from staging import parse_stage_marker
    repo, repository = _repository(github)
    bp = handle['origin']['blueprintSha']
    _blueprint(github, bp)
    default_sha = _protected_branch(github, repo['default_branch'])
    current_run = _current_host(github, host, repository, bp, default_sha, historical=True,
        preview_target_id=handle['targetId'] if handle['prNumber'] is not None else None,
        continuation=host.get('event')=='pull_request_target' and handle['prNumber'] is None)
    run = _run(github, source['runId'], source['runAttempt'])
    require(str(run.get('repository', {}).get('id')) == repository['id'], 'historical-repository')
    caller = run.get('path', '').split('@', 1)[0].removeprefix('.github/workflows/')
    prefix = {'main-build.yml': 'lifecycle / ', 'pr-build.yml': 'ci / ',
              'pr-close.yaml': 'close / lifecycle / '}.get(caller)
    require(prefix is not None, 'historical-source-caller')
    _called(run, CALLERS[caller], bp)
    require(_file(github, '.github/workflows/' + caller, run['head_sha']) ==
            _file(github, '.github/workflows/' + caller, default_sha), 'historical-source-definition')
    job = _job(github, source['runId'], source['runAttempt'], prefix + 'monorepo-stage-publisher')
    binding = parse_stage_marker(github.repo('GET', '/actions/jobs/' + str(job['id']) + '/logs',
                                           raw=True, limit=MAX_LOG_BYTES),
                                 repository_id=repository['id'], run_id=source['runId'], attempt=source['runAttempt'])
    require({k: binding[k] for k in STAGE_FIELDS} == source, 'historical-publisher')
    if run.get('event')=='pull_request_target':
        require(caller=='pr-close.yaml' and source_context['event']=='push'
            and source_context['ref'].startswith('refs/tags/v') and source_context['prNumber'] is not None,
            'historical-closure-context')
        _called(run,'monorepo-closure.yml',bp)
        pr=github.repo('GET','/pulls/'+str(source_context['prNumber']))
        verify_closure_record(github,repository,{'prNumber':source_context['prNumber'],
            'mergeSha':handle['origin']['sourceSha'],'baseRef':source_context['baseRef']},
            source_sha=handle['origin']['sourceSha'],ref=host['ref'],run=run)
        require(github.tag_sha(source_context['ref'].removeprefix('refs/tags/'))==handle['origin']['sourceSha'],
            'historical-closure-tag')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-historical-data-') as directory:
        root = Path(directory).resolve()
        materialize_snapshot(github, handle['origin']['sourceSha'], root)
        resolved = _json_cli(executor, ['validate', '--workdir', str(root), '--json'])['resolved']
        _source_context(source_context, handle['origin']['sourceSha'])
        lifecycle = _json_cli(executor, ['lifecycle', '--workdir', str(root),
            '--event', source_context['event'], '--ref', source_context['ref'],
            '--base-ref', source_context['baseRef'], '--json'])
    require(lifecycle.get('eligible') is True and lifecycle.get('protectedEnvironment') ==
            handle['protectedEnvironment'], 'historical-lifecycle')
    plan = _metadata_plan(repository, handle['origin']['sourceSha'], resolved, pr_number=handle['prNumber'])
    prepared = PreparedAuthorization(github, executor, engine, repository, source, {}, host,
                                 current_run, plan, {}, resolved, lifecycle, None, True)
    prepared._source_context = copy.deepcopy(source_context)
    return prepared


_BINDING_FIELDS = {'aws':('provider','roleArn','region'),
                   'gcp':('provider','workloadIdentityProvider','serviceAccount','project'),
                   'azure':('provider','clientId','tenantId','subscriptionId')}


def _validate_capture(value):
    from credential_context import credential_environment
    require(isinstance(value,dict) and set(value) == {'provider','identity','environment','binding'}
            and value.get('provider') in _BINDING_FIELDS, 'credential-capture')
    document = json.loads(Path(__file__).with_name('schema').joinpath('operations-v1.schema.json').read_text())
    _check(value['identity'],document['$defs']['BackendIdentity'],'$.identity',document=document)
    require(value['identity']['provider'] == value['provider'] and isinstance(value['binding'],dict)
            and set(value['binding']) == set(_BINDING_FIELDS[value['provider']]), 'credential-capture')
    credential_environment(value)


def _selected_binding(settings, ref, provider, account):
    require(isinstance(account,str) and re.fullmatch(
        {'aws':r'[0-9]{12}','gcp':r'[1-9][0-9]{0,31}',
         'azure':r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'}[provider],account),
        'selected-canonical-identity')
    binding = settings['auth'].get(ref)
    require(isinstance(binding,dict) and binding.get('provider') == provider
            and settings['identities'].get(ref) == account, 'selected-binding-identity')
    if provider == 'aws':
        match = re.fullmatch(r'arn:aws(?:-us-gov|-cn)?:iam::([0-9]{12}):role/.+',binding['roleArn'])
        require(match is not None and match[1] == account, 'selected-role-account')
    elif provider == 'azure':
        require(binding['subscriptionId'].lower() == account,'selected-subscription')
    return binding


def _check_selected_capture(settings,ref,provider,account,capture):
    _validate_capture(capture)
    selected = _selected_binding(settings,ref,provider,account)
    require(capture['provider'] == provider
            and capture['binding'] == {k:selected[k] for k in _BINDING_FIELDS[provider]}, 'selected-principal')
    key = {'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[provider]
    require(capture['identity'][key] == account,'selected-canonical-identity')
    if provider == 'azure':
        require(capture['identity']['tenantId'] == selected['tenantId'].lower(),'selected-tenant')

class PreparedAuthorization:
    """Trusted process-local context; inspection objects cannot obtain credentials.

    Instances are created only after independently normalizing the immutable API
    snapshot. No serialized field can upgrade an inspection object into authority.
    """
    def __init__(self, github, executor, engine, repository, stage, host,
                 current_host, current_run, plan, manifest, resolved, lifecycle,
                 scan_results, inspection):
        self.github, self.executor, self.engine = github, executor, engine
        self.repository, self.stage, self.host = repository, stage, host
        self.current_host, self.current_run = current_host, current_run
        self.plan, self.manifest, self.resolved = plan, manifest, resolved
        self.lifecycle, self.scan_results = lifecycle, scan_results
        self._inspection, self._bound = inspection, False
        self._pending, self._readbacks, self._historical = {}, {}, {}
        self._origins = {}

    def inspect(self):
        return copy.deepcopy({'stage': self.stage, 'resolved': self.resolved,
                              'lifecycle': self.lifecycle, 'plan': self.plan,
                              'manifest': self.manifest})

    def select_bindings(self, target_id, component_id, backend_yaml, settings, *, automation_id):
        """Read-only pre-acquisition selection; never authenticates a cloud.

        Historical canonical origin/claims are proved before consulting current
        backend YAML. No empty credential bind or source artifact grants trust.
        """
        require(not self._inspection and self.scan_results is not None and not self._bound,
                'scan-before-selection')
        require(isinstance(settings,dict) and set(settings) ==
                {'auth','identities','registries','probe-secrets','host-keys'},'protected-settings')
        self._settings = {kind:_settings(self.executor,kind,text) for kind,text in settings.items()}
        store = StateHandleStore(self.github,self.repository,automation_id,verify_origin=self._verify_origin)
        selected = [e['payload']['stateHandle'] for e in store.entries()
            if e['payload']['stateHandle']['targetId'] == target_id
            and e['payload']['stateHandle']['componentId'] == (component_id or None)
            and e['payload']['stateHandle']['protectedEnvironment'] == self.lifecycle['protectedEnvironment']
            and e['payload']['stateHandle']['prNumber'] == self.plan['prNumber']]
        require(len({digest(h) for h in selected}) <= 1,'preauth-owner-ambiguity')
        historical = selected[0] if selected else None
        if historical:
            # The old immutable source chooses its original workload alias too;
            # a current target edit/removal cannot retarget recovery acquisition.
            entry = next(e for e in store.entries() if e['payload']['stateHandle'] == historical)
            previous = self._writer_proof(historical,entry)
            target = next((t for t in previous.plan['targets'] if t['id'] == target_id),None)
            require(target is not None,'preauth-historical-target')
            backend = {k:v for k,v in historical['backend'].items() if k not in ('key','prefix')}
            backend_ref = backend.get('authRef',target['authRef'])
        else:
            target = next((t for t in self.plan['targets'] if t['id'] == target_id),None)
            require(target is not None,'preauth-target')
            backend = inspect_backend_settings(backend_yaml,self.executor)
            backend_ref = backend.get('authRef')
            if backend_ref is None:
                require({'s3':'aws','gcs':'gcp','azurerm':'azure'}[backend['kind']] == target['provider'],
                        'backend-explicit-reference')
                backend_ref = target['authRef']
        provider = {'s3':'aws','gcs':'gcp','azurerm':'azure'}[backend['kind']]
        for ref,cloud in ((target['authRef'],target['provider']),(backend_ref,provider)):
            account = self._settings['identities'].get(ref)
            require(isinstance(account,str),'preauth-canonical-identity')
            _selected_binding(self._settings,ref,cloud,account)
        return {'workload':{'authRef':target['authRef'],'provider':target['provider']},
                'backend':{'authRef':backend_ref,'provider':provider,'settings':copy.deepcopy(backend)},
                'historicalHandle':copy.deepcopy(historical)}

    def select_preview_bindings(self, target_id, component_id, backend_yaml, settings, *, automation_id, historical_handle=None):
        """Pre-auth selection for the exact trusted PR/target or frozen child.

        Candidate handles remain untrusted until their independent writer/source
        proof succeeds. An explicit old handle supports per-child backend rotation
        during standing closure without consulting current backend YAML.
        """
        require(self.plan.get('prNumber') is not None, 'preview-selection-pr')
        require(target_id in {t['targetId'] for t in self.plan.get('previewPolicy',{}).get('targets',[])},
                'preview-selection-target')
        if historical_handle is None:
            return self.select_bindings(target_id,component_id,backend_yaml,settings,automation_id=automation_id)
        require(not self._inspection and not self._bound and self.scan_results is not None,
                'scan-before-selection')
        h=historical_handle
        require(h.get('origin',{}).get('repository')==self.repository and h.get('targetId')==target_id
                and h.get('componentId')==(component_id or None) and h.get('prNumber')==self.plan['prNumber']
                and h.get('scope') in ('preview-environment','preview-component'), 'preview-selection-scope')
        require(isinstance(settings,dict) and set(settings)=={'auth','identities','registries','probe-secrets','host-keys'},
                'protected-settings')
        self._settings={kind:_settings(self.executor,kind,text) for kind,text in settings.items()}
        store=StateHandleStore(self.github,self.repository,automation_id,verify_origin=self._verify_origin)
        entries=[e for e in store.entries() if e['payload']['stateHandle']==h]
        require(bool(entries),'preview-selection-owner')
        old=self._writer_proof(h,entries[-1])
        target=next((t for t in old.plan['targets'] if t['id']==target_id),None)
        require(target is not None,'preauth-historical-target')
        backend={k:v for k,v in h['backend'].items() if k not in ('key','prefix')}
        ref=backend.get('authRef',target['authRef'])
        provider={'s3':'aws','gcs':'gcp','azurerm':'azure'}[backend['kind']]
        for alias,cloud in ((target['authRef'],target['provider']),(ref,provider)):
            identity=self._settings['identities'].get(alias)
            require(isinstance(identity,str),'preauth-canonical-identity')
            _selected_binding(self._settings,alias,cloud,identity)
        return {'workload':{'authRef':target['authRef'],'provider':target['provider']},
                'backend':{'authRef':ref,'provider':provider,'settings':copy.deepcopy(backend)},
                'historicalHandle':copy.deepcopy(h)}

    def bind(self, backend_yaml, settings, credentials, *, automation_id, on_readback=None):
        require(not self._inspection and self.scan_results is not None and not self._bound,
                'scan-before-bind')
        require(isinstance(backend_yaml, str) and isinstance(settings, dict)
                and set(settings) == {'auth', 'identities', 'registries', 'probe-secrets', 'host-keys'},
                'protected-settings')
        normalized = {kind: _settings(self.executor, kind, text) for kind, text in settings.items()}
        require(isinstance(credentials, dict) and set(credentials) == {'workload','backend'}, 'credential-context')
        for capture in credentials.values():
            _validate_capture(capture)
        require(on_readback is None or callable(on_readback), 'readback-observer')
        self._backend, self._settings = backend_yaml, normalized
        self._credentials = copy.deepcopy(credentials)
        self._on_readback = on_readback or (lambda line: print(line, flush=True))
        self.store = StateHandleStore(self.github, self.repository, automation_id,
                                     verify_origin=self._verify_origin,
                                     after_readback=self.record_readback)
        self._bound = True
        return self

    def _module_origin(self, module):
        from iac import execution_tree
        row = self.engine.catalog.get('modules', {}).get(module)
        require(isinstance(row, dict), 'module-catalog')
        lock = self.engine.root / row['path'] / '.terraform.lock.hcl'
        return {'repository': self.repository, 'sourceSha': self.plan['headSha'],
                'runId': self.current_host['runId'], 'runAttempt': self.current_host['runAttempt'],
                'blueprintSha': self.current_host['blueprintSha'],
                'moduleRevision': execution_tree(self.engine.root, row),
                'providerLockDigest': 'sha256:' + hashlib.sha256(lock.read_bytes()).hexdigest()}

    def _operation(self, *, target, component, provider_identity, backend, auth_refs,
                   historical=None, operation='apply', origin=None, qualifier=None, lock_id=None, environment=None,
                   backend_identity=None):
        module = (target['provider'] + '-preview-environment' if operation == 'preview' and not component
                  else target['kind'].replace('.', '-'))
        context = {'backend': backend, 'origin': origin or self._module_origin(module),
                   'invocation': {'repository': self.repository, 'sourceSha': self.plan['headSha'],
                                  'runId': self.current_host['runId'],
                                  'runAttempt': self.current_host['runAttempt'],
                                  'blueprintSha': self.current_host['blueprintSha'],
                                  'actor': self.current_host['actor']},
                   'releaseName': self.lifecycle.get('targetName') or self.repository['fullName'].split('/')[-1],
                   'authRefs': auth_refs, 'prNumber': self.plan['prNumber'],
                   'historicalHandle': historical, 'lifecycle': self.lifecycle,
                   'providerIdentity': provider_identity, 'plan': self.plan}
        if historical is not None:
            backend_identity = historical.get('backendIdentity')
        elif backend_identity is None and hasattr(self, '_credentials'):
            backend_identity = self._credentials['backend']['identity']
        if backend_identity is not None:
            context['backendIdentity'] = copy.deepcopy(backend_identity)
            if historical is None:
                selected = backend if isinstance(backend,dict) else inspect_backend_settings(backend,self.executor)
                require(isinstance(selected,dict), 'backend-selector-required')
                backend_ref = selected.get('authRef')
                if backend_ref is None:
                    require({'s3':'aws','gcs':'gcp','azurerm':'azure'}.get(selected.get('kind')) == target['provider'],
                            'backend-explicit-reference')
                    backend_ref = target['authRef']
                context['authRefs'] = sorted({target['authRef'],backend_ref})
        args = ['operations', 'plan', '--operation', operation, '--environment', environment or self.lifecycle['environment'],
                '--target', target['id'], '--component', component, '--json']
        if qualifier:
            args.extend(['--qualifier', qualifier])
        if lock_id:
            args.extend(['--lock-id', lock_id])
        result = _json_cli(self.executor, args, data=context)
        return validate_operation(result)

    def _validate_historical_auth(self, handle, workload_ref):
        provider = handle['resourceIdentity']['provider']
        _selected_binding(self._settings, workload_ref, provider, handle['providerIdentity'])
        backend_provider = {'s3':'aws','gcs':'gcp','azurerm':'azure'}[handle['backend']['kind']]
        identity = handle.get('backendIdentity')
        if identity is None:
            require(backend_provider == provider and handle['authRefs'] == [workload_ref], 'legacy-backend-binding')
            # An old Azure handle has no frozen tenant. Do not manufacture one.
            return
        backend_ref = handle['backend']['authRef']
        account = identity[{'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[backend_provider]]
        binding = _selected_binding(self._settings, backend_ref, backend_provider, account)
        require(handle['authRefs'] == sorted({workload_ref,backend_ref}), 'backend-reference-union')
        if backend_provider == 'azure':
            require(binding['tenantId'].lower() == identity['tenantId'], 'backend-tenant-retarget')

    def _execution_credentials(self, handle):
        from credential_context import credential_environment, validate_pair
        pair = self._credentials
        provider = handle['resourceIdentity']['provider']
        backend_provider = {'s3':'aws','gcs':'gcp','azurerm':'azure'}[handle['backend']['kind']]
        backend_ref = handle['backend'].get('authRef')
        refs = [r for r in handle['authRefs'] if r != backend_ref]
        workload_ref = refs[0] if len(refs) == 1 else backend_ref
        if 'backendIdentity' not in handle:
            require(len(handle['authRefs']) == 1 and backend_provider == provider, 'legacy-backend-binding')
            workload_ref = handle['authRefs'][0]
            backend_ref = workload_ref
        _check_selected_capture(self._settings,workload_ref,provider,handle['providerIdentity'],pair['workload'])
        backend_identity = handle.get('backendIdentity',pair['workload']['identity'])
        account = backend_identity[{'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[backend_provider]]
        _check_selected_capture(self._settings,backend_ref,backend_provider,account,pair['backend'])
        if 'backendIdentity' in handle:
            validate_pair(handle,pair['workload'],pair['backend'])
            result=copy.deepcopy(pair)
            sas=self._settings['auth'][workload_ref].get('packageReadSas')
            if sas is not None:
                require(provider=='azure' and isinstance(sas,str),'package-read-sas')
                result['workload']['environment']['TF_VAR_package_read_sas']=sas
            return result
        require(pair['backend']['binding'] == pair['workload']['binding']
                and pair['backend']['identity'] == pair['workload']['identity'], 'legacy-separate-principal')
        return credential_environment(pair['workload'])

    def backend_read_credentials(self, handle, capture):
        """Third selected context: only a verified root's private backend read.

        It never changes the child's mutation pair/authRefs or authorizes INIT.
        Exact frozen alias and native identity are checked before any state GET.
        """
        require(self._bound and handle.get('scope')=='preview-environment'
                and handle.get('origin',{}).get('repository')==self.repository
                and handle.get('prNumber')==self.plan.get('prNumber'),'root-backend-scope')
        entries=[e for e in self.store.entries() if e['payload']['stateHandle']==handle]
        require(bool(entries),'root-backend-history')
        old=self._writer_proof(handle,entries[-1])
        target=next((t for t in old.plan['targets'] if t['id']==handle['targetId']),None)
        require(target is not None,'root-backend-target')
        self._validate_historical_auth(handle,target['authRef'])
        provider={'s3':'aws','gcs':'gcp','azurerm':'azure'}[handle['backend']['kind']]
        ref=handle['backend'].get('authRef',target['authRef'])
        identity=handle.get('backendIdentity')
        account=identity[{'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[provider]] if identity else handle['providerIdentity']
        _validate_capture(capture)
        _check_selected_capture(self._settings,ref,provider,account,capture)
        if identity is not None:require(capture['identity']==identity,'root-backend-identity')
        from credential_context import credential_environment
        return credential_environment(capture)

    def record_readback(self, handle, entry):
        """Only StateHandleStore's exact local POST+GET path calls this hook.

        Cache exact receipt identity, never a run-wide exemption. The marker is
        emitted before store enumeration and therefore before backend INIT.
        """
        expected = self._pending.get(digest(handle))
        require(expected is not None and expected['handle'] == handle
                and entry.get('payload', {}).get('resourceClaims') == expected['claims'], 'readback-canonical')
        source_stage, source_context = self._origins.get(digest(handle), (self.stage, self._source_context))
        line = state_marker(handle, entry, host=self.current_host, source_stage=source_stage,
                            source_context=source_context)
        self._on_readback(line)
        # A failing observer leaves durable claims but grants no local exemption.
        self._readbacks[str(entry['id'])] = copy.deepcopy(entry)

    def _verify_origin(self, handle, entry):
        if entry is None:
            known = self._pending.get(digest(handle))
            return bool(known and known['handle'] == handle)
        local = self._readbacks.get(str(entry.get('id')))
        if local is not None:
            return local == entry
        return self._verify_historical(handle, entry)

    def _writer_proof(self, handle, entry):
        origin = handle['origin']
        locators = {(origin['runId'], origin['runAttempt'])}
        # A status locator only locates a job. It is never actor/host authority.
        statuses = self.github.pages('/deployments/' + str(entry['id']) + '/statuses')
        pattern = re.compile(r'https://github\.com/' + re.escape(self.repository['fullName'])
                             + r'/actions/runs/([1-9][0-9]*)/attempts/([1-9][0-9]*)$')
        for status in statuses:
            match = pattern.fullmatch(status.get('log_url', ''))
            if match:
                locators.add(match.groups())
        candidates = []
        for run_id, attempt in sorted(locators):
            run = _run(self.github, run_id, attempt)
            caller = run.get('path', '').split('@', 1)[0].removeprefix('.github/workflows/')
            prefix = {'main-build.yml': 'lifecycle / ', 'pr-build.yml': 'preview / ',
                      'pr-close.yaml': 'close / lifecycle / ', 'deploy.yml': 'operation / ',
              'environment-destroy.yml': 'operation / ', 'environment-unlock.yml': 'operation / '}.get(caller)
            if prefix is None:
                continue
            if caller in ('pr-build.yml','pr-close.yaml') and handle['prNumber'] is not None:
                phases=('root','destroy') if handle['scope']=='preview-environment' else ('component','cleanup')
                names={preview_phase_name(caller,handle['targetId'],phase,handle['componentId']) for phase in phases}
            else:
                logical = 'monorepo-operation-' if prefix == 'operation / ' else 'monorepo-apply-'
                names={prefix+logical+handle['targetId']+'-'+(handle['componentId'] or '')}
            # A failed whole job can still have durably reserved before INIT.
            jobs = self.github.pages('/actions/runs/' + run_id + '/attempts/' + attempt + '/jobs')
            exact = [j for j in jobs if j.get('name') in names and str(j.get('run_id')) == run_id
                     and str(j.get('run_attempt')) == attempt]
            require(len({j['name'] for j in exact})==len(exact), 'historical-job')
            evidence=[]
            for job in exact:
                data=self.github.repo('GET','/actions/jobs/'+str(job['id'])+'/logs',raw=True,limit=MAX_LOG_BYTES)
                if any(m.get('receiptId')==str(entry['id']) for m in _records(data,STATE_MARKER)):
                    evidence.append(data)
            require(len(evidence)<=1,'historical-job')
            if not evidence:continue
            data=evidence[0]
            marker = parse_state_marker(data, handle, entry, run_id=run_id, attempt=attempt)
            host = {'repository': self.repository, 'runId': run_id, 'runAttempt': attempt,
                    'event': run['event'], 'ref': marker['workflowRef'].split('@', 1)[-1],
                    'headSha': run['head_sha'], 'workflowRef': marker['workflowRef'],
                    'workflowSha': marker['workflowSha'], 'blueprintSha': origin['blueprintSha'],
                    'actor': run.get('actor', {}).get('login', '')}
            source = marker['sourceStage']
            prepared = _historical_metadata(self.github, self.executor, self.engine,
                                            handle, host, source, marker['sourceContext'])
            candidates.append(prepared)
        require(len(candidates) == 1, 'historical-proof')
        return candidates[0]

    def _verify_historical(self, handle, entry):
        key = (str(entry.get('id')), digest(handle), digest(entry.get('payload')))
        if key in self._historical:
            self._validate_historical_auth(handle,self._historical[key])
            return True
        previous = self._writer_proof(handle, entry)
        require(previous.repository == self.repository and previous.plan['headSha'] == handle['origin']['sourceSha'],
                'historical-source')
        target = next((t for t in previous.plan['targets'] if t['id'] == handle['targetId']), None)
        require(target is not None, 'historical-target')
        # The exact protected job log binds the historical backend/settings bytes;
        # mutable current YAML cannot redirect them. Regenerate every handle field.
        backend = {k: v for k, v in handle['backend'].items() if k not in ('key', 'prefix')}
        operation = previous._operation(target=target, component=handle['componentId'] or '',
                        operation='preview' if handle['prNumber'] is not None else 'apply',
                        provider_identity=handle['providerIdentity'], backend=backend,
                        auth_refs=handle['authRefs'], origin=handle['origin'], qualifier=handle['qualifier'], historical=handle)
        require(operation['stateHandle'] == handle, 'historical-canonical')
        actual = previous._module_origin(handle['moduleId'])
        require(all(actual[k] == handle['origin'][k] for k in ('blueprintSha', 'moduleRevision', 'providerLockDigest')),
                'historical-module')
        # Current protected alias membership and full account identity remain required.
        self._validate_historical_auth(handle, target['authRef'])
        self._origins[digest(handle)] = (previous.stage, previous._source_context)
        self._historical[key] = target['authRef']
        return True

    def bind_created_rest_api(self, handle, api_id, *, verify_creation):
        """Monotonic alias, only at the store's independently verified creation gate.

        The verifier must compare private native state, actual provider identity
        and protected creation host. A boolean/serialized receipt is not a gate.
        """
        require(self._bound and callable(verify_creation), 'rest-creation-verifier')
        validate_operation(handle)
        known = self._pending.get(digest(handle))
        require(known is not None and known['handle'] == handle, 'rest-canonical-owner')
        def verified_creation(exact_handle, exact_id):
            require(exact_handle == handle and exact_id == api_id, 'rest-creation-selection')
            verified = verify_creation(exact_handle, exact_id)
            if verified is True:
                # StateHandleStore validates provider/kind/name/version/ID shape
                # before invoking this trusted gate and then persists exactly
                # this canonical single alias, never arbitrary supplied claims.
                entries = [e for e in self.store.entries() if e['payload']['stateHandle'] == handle]
                require(entries, 'rest-reservation')
                current = max(entries, key=lambda e:len(e['payload']['resourceClaims']))
                resource = handle['resourceIdentity']
                alias = ('arn:aws:apigateway:' + resource['region'] + ':' + handle['providerIdentity']
                         + ':/restapis/' + exact_id)
                self._pending[digest(handle)] = {'handle':copy.deepcopy(handle),
                    'claims':_claims(sorted(set(current['payload']['resourceClaims']) | {alias}))}
            return verified
        prior = copy.deepcopy(known)
        try:
            return self.store.bind_created_rest_api(handle, api_id, verify_creation=verified_creation)
        except Exception:
            self._pending[digest(handle)] = prior
            raise

    def resolve_context(self, request):
        """Verified historical handle for trusted readonly native-state preflight."""
        require(self._bound and not self._inspection, 'unbound')
        validate_record(request)
        require(request['repository'] == self.repository, 'resolve-repository')
        matches = [e for e in self.store.entries()
            if e['payload']['stateHandle']['targetId'] == request['target']['id']
            and e['payload']['stateHandle']['componentId'] == request['componentId']
            and e['payload']['stateHandle']['protectedEnvironment'] == self.lifecycle['protectedEnvironment']]
        require(len({digest(e['payload']['stateHandle']) for e in matches}) <= 1, 'resolve-owner-ambiguity')
        return {'historical_handle': copy.deepcopy(matches[0]['payload']['stateHandle']) if matches else None}

    def authorize(self, request, resolved):
        require(self._bound and not self._inspection, 'unbound')
        from deploy import effective_digest, request_for
        validate_record(request)
        target = next((t for t in self.plan['targets'] if t['id'] == request['target']['id']), None)
        component = next((c for c in self.manifest['components'] if c['componentId'] == request['componentId']), None)
        require(target is not None and component is not None and target['id'] in component['targetIds'], 'binding')
        require(isinstance(resolved, dict) and resolved.get('providerIdentity') ==
                self._settings['identities'].get(target['authRef'])
                and target['authRef'] in self._settings['auth'], 'auth-identity')
        expected = request_for(self.manifest, component, target)
        expected['target']['configDigest'] = effective_digest(target, component['workload'], resolved)
        expected['idempotencyKey'] = digest({'repositoryId': self.repository['id'], 'targetId': target['id'],
            'componentId': component['componentId'], 'artifactDigest': expected['artifact']['digest'],
            'targetConfigDigest': expected['target']['configDigest']})
        expected['previousReceiptId'], expected['reason'] = request['previousReceiptId'], request['reason']
        require(request == expected, 'deployment-request')
        claims = _claims(resolved.get('resourceClaims'))
        existing = resolved.get('existing')
        require(isinstance(existing, dict) and set(existing) == {'providerIdentity', 'exists', 'ownerDigest'}
                and existing['providerIdentity'] == resolved['providerIdentity']
                and isinstance(existing['exists'], bool), 'existing-resource')
        # Enumerate and independently authenticate all historical claims first.
        entries = self.store.entries()
        matches = [e for e in entries if e['payload']['stateHandle']['targetId'] == target['id']
                   and e['payload']['stateHandle']['componentId'] == component['componentId']
                   and e['payload']['stateHandle']['protectedEnvironment'] == self.lifecycle['protectedEnvironment']]
        require(len({digest(e['payload']['stateHandle']) for e in matches}) <= 1, 'historical-ambiguity')
        historical = matches[0]['payload']['stateHandle'] if matches else None
        backend = ({k: v for k, v in historical['backend'].items() if k not in ('key', 'prefix')}
                   if historical else self._backend)
        auth_refs = historical['authRefs'] if historical else [target['authRef']]
        operation = self._operation(target=target, component=component['componentId'],
            provider_identity=resolved['providerIdentity'], backend=backend, auth_refs=auth_refs,
            historical=historical)
        handle = operation['stateHandle']
        self._pending[digest(handle)] = {'handle': copy.deepcopy(handle), 'claims': claims}
        return {'plan': operation, 'canonical': copy.deepcopy(operation), 'store': self.store,
                'resourceClaims': claims, 'existing': copy.deepcopy(existing),
                'credentials': self._execution_credentials(handle), 'engine': self.engine}


    def authorize_preview(self, target_id, component_id, resolved):
        """Frozen trusted-base Kubernetes preview root or component binding.

        An unshipped/blocked namespace root has no execution catalog authority;
        neither this method nor a synthetic resolution can activate it.
        """
        require(self._bound and not self._inspection and self.plan['prNumber'] is not None
                and isinstance(component_id, str), 'preview-context')
        target = next((t for t in self.plan['targets'] if t['id'] == target_id), None)
        require(target is not None and isinstance(resolved, dict)
                and target['authRef'] in self._settings['auth']
                and resolved.get('providerIdentity') == self._settings['identities'].get(target['authRef']),
                'preview-identity')
        module = target['provider'] + '-preview-environment' if not component_id else target['kind'].replace('.', '-')
        row = self.engine.catalog.get('modules', {}).get(module)
        require(isinstance(row, dict) and row.get('activationBlocked') is False, 'preview-module')
        claims = _claims(resolved.get('resourceClaims'))
        existing = resolved.get('existing')
        require(isinstance(existing, dict) and set(existing) == {'providerIdentity','exists','ownerDigest'}
                and existing['providerIdentity'] == resolved['providerIdentity']
                and isinstance(existing['exists'], bool), 'preview-existing')
        entries = [e for e in self.store.entries() if e['payload']['stateHandle']['targetId'] == target_id
            and e['payload']['stateHandle']['componentId'] == (component_id or None)
            and e['payload']['stateHandle']['prNumber'] == self.plan['prNumber']]
        require(len({digest(e['payload']['stateHandle']) for e in entries}) <= 1, 'preview-owner-ambiguity')
        historical = entries[0]['payload']['stateHandle'] if entries else None
        backend = ({k:v for k,v in historical['backend'].items() if k not in ('key','prefix')}
                   if historical else self._backend)
        plan = self._operation(target=target, component=component_id, operation='preview',
            provider_identity=resolved['providerIdentity'], backend=backend,
            auth_refs=historical['authRefs'] if historical else [target['authRef']], historical=historical)
        handle = plan['stateHandle']
        require(handle['moduleId'] == module, 'preview-module-binding')
        self._pending[digest(handle)] = {'handle':copy.deepcopy(handle), 'claims':claims}
        return {'plan':plan,'canonical':copy.deepcopy(plan),'store':self.store,'resourceClaims':claims,
                'existing':copy.deepcopy(existing),'credentials':self._execution_credentials(handle),'engine':self.engine}

    def recovery_inputs(self, handle):
        """Sole-Go historical input projection; never executes source or stages."""
        require(self._bound and (getattr(self,'_recovery_operation',None) in ('destroy','unlock')
                or digest(handle) in getattr(self,'_standing_recovery_inputs',set())),'recovery-operation')
        entries=[e for e in self.store.entries() if e['payload']['stateHandle']==handle]
        require(entries,'recovery-owner')
        previous=self._writer_proof(handle,entries[0])
        target=next((t for t in previous.plan['targets'] if t['id']==handle['targetId']),None)
        component=next((c for c in previous.plan['components'] if c['id']==handle['componentId']),None)
        environment=handle['scope']=='preview-environment' and handle['componentId'] is None
        require(target is not None and (component is not None or environment),'recovery-historical-component')
        plan=previous._operation(target=target,component=handle['componentId'] or '',
            provider_identity=handle['providerIdentity'],backend={k:v for k,v in handle['backend'].items() if k not in ('key','prefix')},
            auth_refs=handle['authRefs'],historical=handle,origin=handle['origin'],qualifier=handle['qualifier'],
            operation='preview' if handle['prNumber'] is not None else 'apply')
        require(plan['stateHandle']==handle and isinstance(plan['inputs'],dict),'recovery-canonical-inputs')
        return {'inputs':copy.deepcopy(plan['inputs']),'packageHandler':component['package'].get('entryPoint') if component else None,
                'target':copy.deepcopy(target)}

    def retire_preview(self, handle):
        """Scan-gated open-PR retirement of a removed component, not closure."""
        require(not hasattr(self,'_preview_closure') and self.scan_results is not None
                and handle['scope']=='preview-component' and handle['origin']['repository']==self.repository
                and handle['prNumber']==self.plan['prNumber']
                and handle['componentId'] not in {c['id'] for c in self.plan['components']},'preview-retirement-scope')
        pr=self.github.repo('GET',f'/pulls/{handle["prNumber"]}')
        require(pr.get('state')=='open' and pr.get('head',{}).get('sha')==self.plan['headSha']
                and str(pr.get('base',{}).get('repo',{}).get('id'))==self.repository['id'], 'preview-retirement-current-state')
        require(any(t['targetId']==handle['targetId'] for t in self.plan['previewPolicy']['targets']), 'preview-retirement-target')
        return self._recover_native(handle,operation='destroy',confirmation=None,standing=True)

    def failure_preview(self, handle, *, root_handle, namespace_uid):
        """Standing isolation-failure policy, not generic failed-rollout cleanup.

        The factory supplies the independently read native root UID and repeats
        native ownership/UID checks before EACH saved apply. This method proves
        the exact fixed verification job's typed failure, not an output boolean.
        """
        require(self._bound and not self._inspection and self.scan_results is not None
                and not hasattr(self,'_preview_closure'),'preview-isolation-context')
        validate_operation(root_handle);validate_operation(handle)
        require(root_handle['scope']=='preview-environment'
                and handle['scope'] in ('preview-environment','preview-component')
                and all(handle[k]==root_handle[k] for k in ('targetId','prNumber','providerIdentity'))
                and handle['origin']['repository']==root_handle['origin']['repository']==self.repository
                and handle['resourceIdentity']['namespace']==root_handle['resourceIdentity']['namespace']
                and handle['prNumber']==self.plan['prNumber']
                and isinstance(namespace_uid,str) and bool(namespace_uid), 'preview-isolation-scope')
        current=self.github.repo('GET',f'/pulls/{handle["prNumber"]}')
        require(current.get('state')=='open' and current.get('head',{}).get('sha')==self.plan['headSha']
                and str(current.get('base',{}).get('repo',{}).get('id'))==self.repository['id'],
                'preview-isolation-current-state')
        require(any(t['targetId']==handle['targetId'] for t in self.plan['previewPolicy']['targets']),
                'preview-isolation-policy')
        entries=[e for e in self.store.entries() if e['payload']['stateHandle']==root_handle]
        require(entries,'preview-isolation-root-owner')
        caller=self.current_host['workflowRef'].split('@',1)[0].rsplit('/',1)[-1]
        require(caller in ('pr-build.yml','pr-close.yaml'),'preview-isolation-caller')
        root_job=preview_phase_name(caller,handle['targetId'],'root')
        jobs=self.github.pages('/actions/runs/'+self.current_host['runId']+'/attempts/'+self.current_host['runAttempt']+'/jobs')
        jobs=[j for j in jobs if j.get('name')==root_job
            and str(j.get('run_id'))==self.current_host['runId']
            and str(j.get('run_attempt'))==self.current_host['runAttempt']]
        require(len(jobs)==1 and jobs[0].get('status')=='completed'
                and jobs[0].get('conclusion')=='failure','preview-isolation-job')
        records=_records(self.github.repo('GET','/actions/jobs/'+str(jobs[0]['id'])+'/logs',
            raw=True,limit=MAX_LOG_BYTES),'CLOUDOPSWORKS_PREVIEW_ISOLATION_V1 ')
        require(len(records)==1,'preview-isolation-marker')
        marker=records[0]
        expected={'repositoryId':self.repository['id'],'prNumber':handle['prNumber'],
            'targetId':handle['targetId'],'sourceSha':self.plan['headSha'],
            'namespace':root_handle['resourceIdentity']['namespace'],'namespaceUid':namespace_uid,
            'stateHandleDigest':digest(root_handle),'status':'isolation-failed'}
        require(set(marker)==set(expected)|{'checks'} and all(marker[k]==v for k,v in expected.items()),
                'preview-isolation-binding')
        allowed={'isolation-admission','isolation-network','isolation-ingress','isolation-enforcement','isolation-control'}
        checks=marker['checks']
        require(isinstance(checks,list) and 0<len(checks)<=len(allowed)
                and all(isinstance(c,dict) and set(c)=={'id','status'} and c['id'] in allowed
                    and c['status']=='failed' for c in checks)
                and len({c['id'] for c in checks})==len(checks),'preview-isolation-checks')
        return self._recover_native(handle,operation='destroy',confirmation=None,standing=True)

    def recover_preview(self, handle):
        """Standing closed-PR policy, never an expanded manual confirmation."""
        require(getattr(self,'_preview_closure',None) == (handle['targetId'],handle['prNumber'])
                and handle['scope'] in ('preview-environment','preview-component'), 'preview-closure-scope')
        pr=self.github.repo('GET',f'/pulls/{handle["prNumber"]}')
        require(pr.get('state')=='closed' and str(pr.get('base',{}).get('repo',{}).get('id'))==self.repository['id'],
                'preview-closure-current-state')
        return self._recover_native(handle,operation='destroy',confirmation=None,standing=True)

    def recover(self, handle, *, operation, confirmation, lock_id=None):
        require(not hasattr(self,'_preview_closure'),'manual-standing-policy-separation')
        return self._recover_native(handle,operation=operation,confirmation=confirmation,lock_id=lock_id)

    def _recover_native(self, handle, *, operation, confirmation, lock_id=None, standing=False):
        """Exact native destroy/unlock; current component/target YAML is irrelevant."""
        from operations import assert_confirmation
        require(self._bound and not self._inspection and operation in ('destroy', 'unlock')
                and (getattr(self, '_recovery_operation', None) == operation or standing), 'recovery-operation')
        validate_operation(handle)
        require(handle['origin']['repository'] == self.repository, 'recovery-repository')
        entries = [e for e in self.store.entries() if e['payload']['stateHandle'] == handle]
        require(entries, 'recovery-owner')
        # The full current identity, not merely the alias name, must still agree.
        previous = self._writer_proof(handle, entries[0])
        target_binding = next((t for t in previous.plan['targets'] if t['id'] == handle['targetId']),None)
        require(target_binding is not None,'recovery-auth-target')
        self._validate_historical_auth(handle,target_binding['authRef'])
        target = {'id': handle['targetId'], 'kind': handle['resourceIdentity']['kind']}
        backend = {k: v for k, v in handle['backend'].items() if k not in ('key', 'prefix')}
        plan = self._operation(target=target, component=handle['componentId'] or '',
            provider_identity=handle['providerIdentity'], backend=backend, auth_refs=handle['authRefs'],
            historical=handle, operation=operation, qualifier=handle['qualifier'], lock_id=lock_id,
            environment=handle['environment'])
        if not standing:
            assert_confirmation(plan, environment=handle['protectedEnvironment'], target=handle['targetId'],
                                component=handle['componentId'], confirmation=confirmation)
        claims = _claims(max(entries, key=lambda e:len(e['payload']['resourceClaims']))['payload']['resourceClaims'])
        self._pending[digest(handle)] = {'handle': copy.deepcopy(handle), 'claims': claims}
        if standing:
            self._standing_recovery_inputs=getattr(self,'_standing_recovery_inputs',set())|{digest(handle)}
        return {'plan': plan, 'canonical': copy.deepcopy(plan), 'store': self.store,
                'resourceClaims': claims, 'existing': {'providerIdentity':handle['providerIdentity'],
                'exists':True, 'ownerDigest':digest(handle)},
                'credentials':self._execution_credentials(handle), 'engine':self.engine}


def prepare_preview_closure(github, handles, target_id, pr, *, blueprint_sha, executor, engine, current_host):
    """Host-proven standing closure policy before any source artifact or scanner.

    Only independently recorded historical preview scopes for this exact PR and
    target are admitted. It cannot authorize normal operations or open-PR apply.
    """
    require(isinstance(handles,list) and handles,'preview-closure-handles')
    repo,repository=_repository(github)
    _blueprint(github,blueprint_sha)
    default_sha=_protected_branch(github,repo['default_branch'])
    run=_current_host(github,current_host,repository,blueprint_sha,default_sha,preview_target_id=target_id)
    caller=run.get('path','').split('@',1)[0]
    require(caller in ('.github/workflows/pr-build.yml','.github/workflows/pr-close.yaml',
                      '.github/workflows/environment-destroy.yml','.github/workflows/environment-unlock.yml'),
            'preview-closure-caller')
    current=github.repo('GET',f'/pulls/{pr}')
    require(current.get('state')=='closed' and str(current.get('base',{}).get('repo',{}).get('id'))==repository['id'],
            'preview-closure-current-state')
    probe=PreparedAuthorization(github,executor,engine,repository,{}, {},current_host,run,{}, {},{}, {},None,True)
    histories=[]
    for handle in handles:
        validate_operation(handle)
        require(handle['origin']['repository']==repository and handle['targetId']==target_id
                and handle['prNumber']==pr and handle['scope'] in ('preview-component','preview-environment'),
                'preview-closure-scope')
        old=probe._writer_proof(handle,_find_handle_entry(github,handle))
        target=next((t for t in old.plan['targets'] if t['id']==target_id),None)
        require(target is not None,'preview-closure-target')
        generated=old._operation(target=target,component=handle['componentId'] or '',
            provider_identity=handle['providerIdentity'],backend={k:v for k,v in handle['backend'].items() if k not in ('key','prefix')},
            auth_refs=handle['authRefs'],historical=handle,origin=handle['origin'],operation='preview',qualifier=handle['qualifier'])
        require(generated['stateHandle']==handle,'preview-closure-canonical')
        histories.append(old)
    old=histories[0]
    require(len({h['protectedEnvironment'] for h in handles})==1,'preview-closure-environment')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-closure-policy-') as directory:
        root=Path(directory).resolve();materialize_snapshot(github,current_host['headSha'],root)
        resolved=_json_cli(executor,['validate','--workdir',str(root),'--json'])['resolved']
    _environment(github,resolved['policy'],{'protectedEnvironment':handles[0]['protectedEnvironment']})
    prepared=PreparedAuthorization(github,executor,engine,repository,old.stage,{},current_host,run,
        old.plan,{},resolved,old.lifecycle,[],False)
    prepared._source_context=old._source_context
    prepared._recovery_operation='destroy';prepared._preview_closure=(target_id,pr)
    for handle,history in zip(handles,histories):
        prepared._origins[digest(handle)]=(history.stage,history._source_context)
    return prepared


def prepare_recovery_context(github, handle, *, operation, blueprint_sha, executor, engine, current_host):
    """Manual native recovery, independent of expired build/stage payloads.

    Destroy/unlock execute no source builds or language scanners, matching the
    existing language workflows. Native saved-plan/state/ownership guards remain
    mandatory. This is not an exemption for apply, release or preview execution.
    """
    require(operation in ('destroy', 'unlock'), 'manual-operation')
    validate_operation(handle)
    repo, repository = _repository(github)
    require(handle['origin']['repository'] == repository, 'manual-repository')
    _blueprint(github, blueprint_sha)
    default_sha = _protected_branch(github, repo['default_branch'])
    run = _current_host(github, current_host, repository, blueprint_sha, default_sha)
    expected = {'destroy': '.github/workflows/environment-destroy.yml',
                'unlock': '.github/workflows/environment-unlock.yml'}[operation]
    require(run.get('path', '').split('@', 1)[0] == expected, 'manual-caller-operation')
    probe = PreparedAuthorization(github, executor, engine, repository, {}, {}, current_host,
                                  run, {}, {}, {}, {}, None, True)
    historical = probe._writer_proof(handle, _find_handle_entry(github, handle))
    target = next((t for t in historical.plan['targets'] if t['id'] == handle['targetId']), None)
    require(target is not None, 'manual-historical-target')
    regenerated = historical._operation(target=target, component=handle['componentId'] or '',
        provider_identity=handle['providerIdentity'], backend={k:v for k,v in handle['backend'].items()
        if k not in ('key','prefix')}, auth_refs=handle['authRefs'], origin=handle['origin'],
        operation='preview' if handle['prNumber'] is not None else 'apply', qualifier=handle['qualifier'], historical=handle)
    require(regenerated['stateHandle'] == handle, 'manual-historical-canonical')
    actual = historical._module_origin(handle['moduleId'])
    require(all(actual[k] == handle['origin'][k] for k in ('blueprintSha','moduleRevision','providerLockDigest')),
            'manual-module')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-recovery-policy-') as directory:
        root = Path(directory).resolve()
        materialize_snapshot(github, current_host['headSha'], root)
        resolved = _json_cli(executor, ['validate','--workdir',str(root),'--json'])['resolved']
    # The selected old native environment must still exist in actual current
    # owners policy and retain its real protections; removed targets do not matter.
    _environment(github, resolved['policy'], {'protectedEnvironment':handle['protectedEnvironment']})
    prepared = PreparedAuthorization(github, executor, engine, repository, historical.stage, {}, current_host,
        run, historical.plan, {}, resolved, historical.lifecycle, [], False)
    prepared._source_context = historical._source_context
    prepared._origins[digest(handle)] = (historical.stage, historical._source_context)
    prepared._recovery_operation = operation
    return prepared


def _find_handle_entry(github, handle):
    # Actor checks remain mandatory in StateHandleStore after binding. This
    # precredential lookup selects an exact hash only, then independently proves
    # actual protected host/code/full canonical handle before it is used.
    entries = [e for e in github.pages('/deployments?task=cloudopsworks-state')
               if isinstance(e.get('payload'),dict) and e['payload'].get('stateHandle') == handle
               and e['payload'].get('stateHandleDigest') == digest(handle)]
    require(entries, 'manual-handle-missing')
    for entry in entries:
        payload = entry['payload']
        require(set(payload) == {'apiVersion','kind','stateHandle','stateHandleDigest','resourceClaims'}
                and payload['apiVersion'] == 'cloudopsworks.io/operations/v1'
                and payload['kind'] == 'StateHandleReservation'
                and entry.get('task') == 'cloudopsworks-state'
                and entry.get('environment') == StateHandleStore.environment(handle)
                and _id(str(entry.get('id'))), 'manual-handle-envelope')
        _claims(payload['resourceClaims'])
    return max(entries, key=lambda e:int(e['id']))
