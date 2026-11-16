"""Fixed workflow entry points; YAML only handles permissions and matrices."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from contracts import claims_overlap, canonical_bytes, fail, load_record, rooted_path, validate_linked, validate_record
from executor import Runner, checked
from github import GitHub
from release import ArtifactPublisher, publish_release, verify_manifest
from deploy import prepare, reconcile
from receipts import ReceiptStore
from diagnostics import event, observed, error_category
from providers.registry import protected_context, bind_resolution, assert_mapping


def output(name, value):
    encoded = json.dumps(value, separators=(',', ':')) if not isinstance(value, str) else value
    if '\n' in encoded or '\r' in encoded:
        fail('workflow-output', 'workflow output must be single-line')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        stream.write(name + '=' + encoded + '\n')


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def preview_build_baseline(record, root, runner, load_state):
    """Read-only build selection from trusted durable preview materialization.

    Unknown/missing/force-pushed/divergent target baselines force an unprivileged
    all build. A common verified previous PR head enables incremental selection.
    """
    heads = []
    for policy in record['previewPolicy']['targets']:
        payload = load_state(policy['targetId'])
        if not payload:
            return None, True
        state = validate_record(payload['state'])
        active = {c['id'] for c in record['components']}
        if state['repository'] != record['repository'] or state['prNumber'] != record['prNumber'] or state['targetId'] != policy['targetId'] or state['phase'] == 'closed' or not active <= set(payload.get('artifacts', {})):
            return None, True
        if any(c['preview']['mode']=='artifact-only' and c['id'] not in payload.get('artifactSources',{}) for c in record['components']):
            return None,True
        base = state['headSha']
        relation = runner.run(['git','merge-base','--is-ancestor',base,record['headSha']],cwd=root)
        if relation.returncode != 0:
            return None, True
        heads.append(base)
    if not heads or len(set(heads)) != 1:
        return None, True
    return heads[0], False


@observed('plan')
def plan(args, runner):
    argv = ['tronador', 'components', 'plan', '--workdir', str(args.root), '--head', args.head,
            '--event', args.event, '--version', args.version, '--json']
    if args.base:
        argv += ['--base', args.base]
    if not args.base or getattr(args, 'all', False):
        argv += ['--all']
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    if args.event == 'pull-request' and event_path:
        event_payload = json.loads(Path(event_path).read_bytes())
        number = event_payload.get('pull_request', {}).get('number', event_payload.get('number'))
        if type(number) is not int or number < 1:
            fail('plan-pr', 'PR build must carry its originating PR number')
        argv += ['--pr-number', str(number)]
    record = validate_record(load_record(checked(runner, argv)))
    if args.event == 'pull-request' and record['previewPolicy']['enabled'] and not getattr(args,'all',False):
        base, materialize_all = None, True
        automation = os.environ.get('CLOUDOPSWORKS_AUTOMATION_ID')
        if os.environ.get('GH_TOKEN') and automation:
            from preview import PreviewStore
            github = GitHub(os.environ['GITHUB_REPOSITORY'])
            def load_state(target):
                return PreviewStore(github,record['repository'],record['prNumber'],target,automation).load()
            base, materialize_all = preview_build_baseline(record,args.root,runner,load_state)
        revised = argv[:]
        if '--base' in revised:
            position = revised.index('--base')
            del revised[position:position+2]
        if '--all' in revised:
            revised.remove('--all')
        if materialize_all:
            revised.append('--all')
        else:
            revised += ['--base',base]
        record = validate_record(load_record(checked(runner,revised)))
        output('build-baseline','materialize-all' if materialize_all else 'previous-preview-head')
    if record['repository'] != {'id': os.environ['GITHUB_REPOSITORY_ID'], 'fullName': os.environ['GITHUB_REPOSITORY']} or record['headSha'] != args.head:
        fail('plan-identity', 'producer plan does not match workflow repository/head')
    configuration = load_record(checked(runner,['tronador','components','validate','--workdir',str(args.root),'--json']))
    configured, cap = configuration.get('maxParallel'), getattr(args,'max_parallel',32)
    if type(configured) is not int or not 1 <= configured <= 32 or type(cap) is not int or not 1 <= cap <= 32:
        fail('max-parallel','validated configuration and caller concurrency must be integers from 1 to 32')
    output('max-parallel',str(min(configured,cap)))
    selections={item['componentId']:item['reasons'] for item in record['buildSelection']}
    for component in record['components']:
        reasons=selections.get(component['id'],['unchanged'])
        for reason in reasons:event('selection','selected' if component['id'] in selections else 'skipped',component=component['id'],reason=reason,source=record['headSha'],version=record['version'])
    event('selection','succeeded',selected=len(selections),skipped=len(record['components'])-len(selections),source=record['headSha'],version=record['version'])
    save(args.out, record)
    output('matrix', record['matrix'])
    output('noop', str(record['buildNoop']).lower())
    output('version', record['version'])
    output('selected',str(len(selections)))
    output('skipped',str(len(record['components'])-len(selections)))


def tools(args):
    record = validate_record(load_record(args.plan))
    if getattr(args, 'scan_component', False):
        from contracts import _merge_toolchains
        by_id = {component['id']: component for component in record['components']}
        if args.component not in by_id:
            fail('scanner-component', 'scanner owner is not an active component')
        closure = set()
        def collect(ident):
            if ident not in closure:
                closure.add(ident)
                for dependency in by_id[ident]['dependsOn']: collect(dependency)
        collect(args.component)
        versions = {tool['tool']:tool['version'] for tool in _merge_toolchains([by_id[ident] for ident in sorted(closure)])}
    else:
        row = next((r for r in record['matrix']['include'] if r['componentId'] == args.component), None)
        if not row:
            fail('matrix-row', 'component is not a selected row')
        versions = {t['tool']: t['version'] for t in row['toolchains']}
    for tool in ('node','go','java','dotnet','python','rust','ruby','npm','pnpm','yarn','bundler'):
        output(tool, versions.get(tool, ''))


@observed('build')
def build(args, runner):
    record = validate_record(load_record(args.plan))
    if args.component not in {r['componentId'] for r in record['matrix']['include']}:
        fail('matrix-row', 'build owner not selected')
    result = None
    for operation in ('build', 'test', 'package'):
        started=time.monotonic()
        event(operation,'running',component=args.component,source=record['headSha'],version=record['version'])
        try:
            text = checked(runner, ['tronador', 'components', operation, args.component, '--workdir', str(args.root),
                '--plan', str(args.plan.resolve()), '--allow-network', '--no-install-tools', '--json'])
        except Exception as error:
            failure={'apiVersion':record['apiVersion'],'kind':'ComponentResult','repository':record['repository'],
                'componentId':args.component,'headSha':record['headSha'],'version':record['version'],
                'purpose':'release' if record['event']=='release' else 'ci','status':'failed','mainArtifact':None,'previewArtifact':None,
                'error':{'code':error_category(error),'message':'Component source phase failed; inspect the phase and category','retryable':False}}
            save(Path(os.environ.get('CLOUDOPSWORKS_DIAGNOSTICS','.lifecycle-diagnostics'))/('component-'+args.component+'.json'),validate_record(failure))
            event(operation,'failed',component=args.component,source=record['headSha'],version=record['version'],errorCategory=error_category(error),failed=1,durationMs=int((time.monotonic()-started)*1000))
            raise
        if operation == 'package':
            result = load_record(text)
        event(operation,'succeeded',component=args.component,source=record['headSha'],version=record['version'],durationMs=int((time.monotonic()-started)*1000))
    validate_linked(result, {'plan': record})
    bundle = args.bundle
    bundle.mkdir(parents=True, exist_ok=False)
    save(bundle / 'results' / (args.component + '.json'), result)
    for field in ('mainArtifact', 'previewArtifact'):
        artifact = result[field]
        if not artifact:
            continue
        relative = artifact['location'].get('path')
        if not relative:
            fail('local-artifact', 'CI must package to a local bounded artifact')
        source = rooted_path(args.root, relative, output=True)
        from contracts import validate_artifact
        validate_artifact(source, artifact)
        destination = bundle / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)


@observed('baseline')
def baseline(args, github, publisher, runner):
    releases = github.pages('/releases')
    for release in releases:
        if release['draft'] or release['tag_name'] == getattr(args, 'exclude_tag', None):
            continue
        try:
            manifest = github.release_manifest(release)
            verify_manifest(manifest, github, publisher)
        except (ValueError, RuntimeError):
            # Old non-monorepo releases are not baselines. A corrupt monorepo
            # release is not silently treated as a valid empty selection.
            assets = github.pages(f'/releases/{release["id"]}/assets')
            if any(a['name'] == 'monorepo-manifest.json' for a in assets):
                raise
            continue
        relation = runner.run(['git', 'merge-base', '--is-ancestor', manifest['headSha'], args.head], cwd=args.root)
        if relation.returncode != 0:
            fail('release-lineage', 'previous complete release is outside current lineage')
        save(args.out, manifest)
        output('base', manifest['headSha'])
        return
    output('base', '')


@observed('publish')
def publish(args, github, publisher):
    record = validate_record(load_record(args.plan))
    previous = load_record(args.previous) if args.previous and args.previous.exists() else None
    results = [load_record(p) for p in sorted((args.root / 'results').glob('*.json'))]
    manifest = publish_release(record, results, previous, github, publisher, args.root)
    save(args.out, manifest)
    output('manifest', str(args.out))
    selected={r['componentId'] for r in results}
    for component in manifest['components']:
        artifact=component['mainArtifact']
        event('publication','succeeded',component=component['componentId'],reason='published' if component['componentId'] in selected else 'reused',source=artifact['sourceSha'],version=artifact['builtVersion'],digest=artifact['digest'])
    event('publication','succeeded',selected=len(selected),reused=len(manifest['components'])-len(selected),version=manifest['version'])


def deployment(args, github, publisher, runner):
    manifest = validate_record(load_record(args.manifest))
    verify_manifest(manifest, github, publisher)
    identities = json.loads(os.environ['CLOUDOPSWORKS_IDENTITIES'])
    rows = prepare(manifest, runner, identities, registries=protected_context(os.environ)['registries'])
    store = ReceiptStore(github, manifest['repository'], os.environ['CLOUDOPSWORKS_AUTOMATION_ID'])
    for row in rows:
        request = row['request']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = request['artifact']
            context = {'workDir': root, 'chartPath': Path(__file__).resolve().parents[3] / 'kubernetes/helm/charts',
                       'secrets': json.loads(os.environ.get('CLOUDOPSWORKS_PROBE_SECRETS', '{}')),
                       'hostKeys': json.loads(os.environ.get('CLOUDOPSWORKS_HOST_KEYS', '{}')),
                   **protected_context(os.environ)}
            if artifact['location']['kind'] == 'release-asset':
                location = artifact['location']
                release = github.release(location['tag'])
                asset = next(a for a in github.pages(f'/releases/{release["id"]}/assets') if a['name'] == location['name'])
                path = root / location['name']
                path.write_bytes(github.asset_bytes(asset))
                from contracts import validate_artifact
                validate_artifact(path, artifact)
                context['artifactPath'] = path
            results = reconcile([row], runner, store, context=context, force=args.force)
            if any(r['status'] != 'succeeded' for r in results):
                fail('deployment-failed', 'one or more target deployments failed')


def target_matrix(args):
    manifest = validate_record(load_record(args.manifest))
    targets = {t['id']: t for t in manifest['targets']}
    active = sorted({t for c in manifest['components'] for t in c['targetIds']})
    rows = [{key: targets[t][key] for key in ('id','provider','authRef','environment')} for t in active]
    output('matrix', {'include': rows})
    output('noop', str(not rows).lower())


@observed('resolve-target')
def resolve_target(args, runner):
    from deploy import provider, request_for
    manifest = validate_record(load_record(args.manifest))
    target = next((t for t in manifest['targets'] if t['id'] == args.target), None)
    if target is None:
        fail('target', 'target not in complete manifest')
    expected = json.loads(os.environ['CLOUDOPSWORKS_IDENTITIES']).get(target['authRef'])
    rows = []
    for component in manifest['components']:
        if target['id'] not in component['targetIds']:
            continue
        request = validate_record(request_for(manifest, component, target))
        resolved = provider(target['provider']).resolve(request, runner)
        if not expected or resolved['providerIdentity'] != expected:
            fail('resolved-account', 'resolved identity does not match protected binding')
        resolved = bind_resolution(request,resolved,runner,protected_context(os.environ)['registries'])
        rows.append({'request': request, 'resolved': resolved})
    save(args.out, rows)


@observed('global-preflight')
def global_preflight(args):
    from deploy import effective_digest
    manifest = validate_record(load_record(args.manifest))
    rows = []
    for path in sorted(args.directory.glob('*.json')):
        data = json.loads(path.read_bytes())
        if not isinstance(data, list):
            fail('resolution', 'resolution artifact must contain a list')
        rows.extend(data)
    expected = {(c['componentId'], t) for c in manifest['components'] for t in c['targetIds']}
    found, claims, selected = set(), [], []
    for row in rows:
        request, resolved = row['request'], row['resolved']
        validate_record(request)
        binding = request['componentId'], request['target']['id']
        if binding in found or binding not in expected:
            fail('resolution', 'duplicate or undeclared target-component resolution')
        found.add(binding)
        if request['manifestDigest'] != __import__('contracts').digest(manifest):
            fail('resolution', 'resolution belongs to another manifest')
        resources = resolved['resourceClaims']
        if resolved.get('resourceLock') not in resources:
            fail('resolution', 'stable primary resource lock must be a verified ownership claim')
        if not resources or len(set(resources)) != len(resources):
            fail('resolution', 'resource claims are missing or ambiguous')
        for claim in resources:
            if any(claims_overlap(claim, old) for old in claims):
                fail('resource-ownership', 'global canonical resource claims overlap')
            claims.append(claim)
        if request['target']['environment'] == args.environment:
            assert_mapping(request,resolved,protected_context(os.environ)['registries'])
        request['target']['configDigest'] = effective_digest(request['target'], request['workload'], resolved)
        request['idempotencyKey'] = __import__('contracts').digest({'repositoryId': manifest['repository']['id'],
            'targetId': binding[1], 'componentId': binding[0], 'artifactDigest': request['artifact']['digest'],
            'targetConfigDigest': request['target']['configDigest']})
        if request['target']['environment'] == args.environment:
            selected.append(row)
    if found != expected:
        fail('resolution', 'not every active binding completed read-only ownership discovery')
    save(args.out, selected)
    output('matrix', {'include': [{'componentId': r['request']['componentId'], 'id': r['request']['target']['id'],
        'provider': r['request']['target']['provider'], 'authRef': r['request']['target']['authRef'],
        'environment': r['request']['target']['environment'],
        'resourceLock': __import__('contracts').digest(r['resolved']['resourceLock'])[7:]} for r in selected]})
    output('noop', str(not selected).lower())


@observed('apply-row')
def apply_row(args, github, publisher, runner):
    manifest = validate_record(load_record(args.manifest))
    verify_manifest(manifest, github, publisher)
    rows = json.loads(args.rows.read_bytes())
    match = [r for r in rows if r['request']['componentId'] == args.component and r['request']['target']['id'] == args.target]
    if len(match) != 1:
        fail('deployment-row', 'trusted global preflight row is missing or ambiguous')
    row = match[0]
    request = row['request']
    assert_mapping(request,row['resolved'],protected_context(os.environ)['registries'])
    store = ReceiptStore(github, manifest['repository'], os.environ['CLOUDOPSWORKS_AUTOMATION_ID'])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        context = {'workDir': root, 'chartPath': Path(__file__).resolve().parents[3] / 'kubernetes/helm/charts',
                   'secrets': json.loads(os.environ.get('CLOUDOPSWORKS_PROBE_SECRETS', '{}')),
                   'hostKeys': json.loads(os.environ.get('CLOUDOPSWORKS_HOST_KEYS', '{}')),
                   **protected_context(os.environ)}
        artifact = request['artifact']
        if artifact['location']['kind'] == 'release-asset':
            location = artifact['location']
            release = github.release(location['tag'])
            asset = next(a for a in github.pages(f'/releases/{release["id"]}/assets') if a['name'] == location['name'])
            path = root / location['name']
            path.write_bytes(github.asset_bytes(asset))
            __import__('contracts').validate_artifact(path, artifact)
            context['artifactPath'] = path
        def persist(result):
            save(Path('.lifecycle-diagnostics')/('deployment-'+args.component+'-'+args.target+'.json'),result)
            event('deployment',result['status'],component=args.component,target=args.target,source=request['artifact']['sourceSha'],version=request['releaseVersion'],digest=result['artifactDigest'],errorCategory=(result.get('error') or {}).get('code','none'))
        context['result_sink']=persist
        result = reconcile([row], runner, store, context=context, force=args.force)
        if not result:event('deployment','reused',component=args.component,target=args.target,reason='already-converged',source=request['artifact']['sourceSha'],version=request['releaseVersion'],digest=request['artifact']['digest'],reused=1)
        if any(r['status'] != 'succeeded' for r in result):
            fail('deployment-failed', 'native deployment or declared serving probe failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--base', default='')
    p.add_argument('--head', required=True)
    p.add_argument('--event', required=True, choices=['pull-request','push','release','manual'])
    p.add_argument('--version', required=True)
    p.add_argument('--all', action='store_true')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--max-parallel',type=int,default=32)
    for name in ('tools','build'):
        p = sub.add_parser(name)
        if name == 'tools': p.add_argument('--scan-component', action='store_true')
        p.add_argument('--plan', type=Path, required=True)
        p.add_argument('--component', required=True)
        if name == 'build':
            p.add_argument('--root', type=Path, default=Path('.'))
            p.add_argument('--bundle', type=Path, required=True)
    p = sub.add_parser('summary')
    p.add_argument('--needs', required=True)
    args = parser.parse_args()
    runner = Runner()
    if args.command == 'summary':
        needs = json.loads(args.needs)
        for phase,job in needs.items():
            event('workflow-summary',job['result'],reason=phase)
        event('workflow-summary','completed',succeeded=sum(j['result']=='success' for j in needs.values()),skipped=sum(j['result']=='skipped' for j in needs.values()),failed=sum(j['result'] in ('failure','cancelled') for j in needs.values()))
        if any(job['result'] in ('failure','cancelled') for job in needs.values()) or not needs or all(job['result'] == 'skipped' for job in needs.values()):
            fail('workflow-failed', 'required lifecycle prerequisite failed, cancelled or never executed')
    elif args.command == 'plan':
        plan(args, runner)
    elif args.command == 'tools':
        tools(args)
    elif args.command == 'build':
        build(args, runner)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        event('entrypoint','failed',errorCategory=error_category(error),failed=1)
        raise SystemExit(1)
