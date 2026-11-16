"""Exact manual registry publication after independently completed current gates."""
import argparse
import os
from authorization import inspect_verified_context, _scan_barrier
from contracts import fail, load_record
from diagnostics import event, error_category
from executor import checked
from github import GitHub
from iac import IaCExecutor
from normal_entry import NativeRunner, ROOT, output
from operation_entry import completed_source_runs
from release import ArtifactPublisher
from scan_entry import host


def prepare(github, runner, environ, component_id):
    blueprint=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    current=host(environ,blueprint)
    if (current['event']!='workflow_dispatch' or current['workflowRef'].split('@',1)[0]
            !=current['repository']['fullName']+'/.github/workflows/deploy-container.yml'):
        fail('container-caller','registry publication requires its exact manual caller')
    engine=IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json'))
    for source in completed_source_runs(github,current['headSha']):
        try:
            prepared=inspect_verified_context(github,source,blueprint_sha=blueprint,executor=runner,
                engine=engine,current_host=current)
            if prepared.plan['headSha']!=current['headSha'] or prepared.host['ref']!=current['ref']:
                continue
            owners=[c for c in prepared.manifest['components'] if c['componentId']==component_id]
            if len(owners)!=1 or owners[0]['mainArtifact']['format']!='oci':
                fail('container-component','selected active component does not publish an OCI artifact')
            # The successful source publisher is not a scanner pass. Re-fetch the
            # exact source attempt's completed barrier, matching CURRENT Go policy
            # and the entire resolved configuration, before any registry command.
            prepared.scan_results=_scan_barrier(github,prepared.host,prepared.stage,
                prepared.resolved,prepared.plan,prepared.manifest)
            return prepared,owners[0]['mainArtifact']
        except Exception:
            continue
    fail('container-source-gates','no exact current stage and completed current-policy scanner proof; rebuild unprivileged')


def publish(prepared, artifact, component_id, publisher):
    if not prepared._inspection or not prepared.scan_results or artifact not in [
            c['mainArtifact'] for c in prepared.manifest['components'] if c['componentId']==component_id]:
        fail('container-publication','exact inspected stage and completed gates are required')
    result=publisher.publish(artifact,component_id,'main',ROOT,None,None,prepared.plan['repository'])
    event('container-publication',component=component_id,status='succeeded',
        source=artifact['sourceSha'],version=artifact['builtVersion'],digest=artifact['digest'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['inspect','publish'])
    parser.add_argument('--component',required=True);args=parser.parse_args(argv)
    github=GitHub(os.environ['GITHUB_REPOSITORY'],os.environ['GH_TOKEN'])
    runner=NativeRunner(inherit_environment=False)
    prepared,artifact=prepare(github,runner,os.environ,args.component)
    if args.command=='inspect':
        output({'environment':prepared.lifecycle['protectedEnvironment']},os.environ['GITHUB_OUTPUT'])
    else:
        publisher=ArtifactPublisher(github,runner,'ghcr.io/'+os.environ['GITHUB_REPOSITORY'].lower())
        publish(prepared,artifact,args.component,publisher)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        event('container-publication',status='failed',errorCategory=error_category(exc))
        raise SystemExit('container publication failed; see safe lifecycle diagnostics') from None
