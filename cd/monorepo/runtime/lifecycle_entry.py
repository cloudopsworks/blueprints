"""No-input caller preparation. Version authority remains Tronador/GitVersion."""
import json
import os
from pathlib import Path
import re
import sys
from contracts import fail,load_record
from executor import Runner,checked
from workflow import output


def prepare(root,runner,environment=os.environ,*,github=None):
    host=json.loads(Path(environment['GITHUB_EVENT_PATH']).read_bytes())
    event=environment['GITHUB_EVENT_NAME']
    repository={'id':environment['GITHUB_REPOSITORY_ID'],'fullName':environment['GITHUB_REPOSITORY']}
    if event=='pull_request':
        pr=host.get('pull_request',{})
        if str(pr.get('base',{}).get('repo',{}).get('id'))!=repository['id']:
            fail('lifecycle-host','PR base repository differs from actual host')
        head=pr.get('head',{}).get('sha');kind='pull-request'
    elif event in ('push','create','workflow_dispatch'):
        head=environment['GITHUB_SHA'];kind='manual' if event=='workflow_dispatch' else 'push'
    else:fail('lifecycle-host','unsupported source preparation event')
    if not isinstance(head,str) or not re.fullmatch(r'[0-9a-f]{40}',head):
        fail('lifecycle-host','source head is not immutable')
    actual=checked(runner,['git','rev-parse','HEAD'],cwd=root).strip()
    if actual!=head:fail('lifecycle-checkout','source checkout differs from actual host head')
    checked(runner,['tronador','project','version','--workdir',str(root),'--allow-network','--json'])
    version=(root/'VERSION').read_text().strip().removeprefix('v')
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?',version):
        fail('lifecycle-version','sole repository version is invalid')
    base=''
    if github is not None:
        from stage_baseline import find
        run=github.repo('GET','/actions/runs/'+environment['GITHUB_RUN_ID']+'/attempts/'+environment['GITHUB_RUN_ATTEMPT'])
        blueprint=Path(__file__).resolve().parents[3]
        blueprint_sha=checked(runner,['git','rev-parse','HEAD'],cwd=blueprint).strip()
        previous=find(github,run,repository=repository,head=head,root=root,runner=runner,
            blueprint_sha=blueprint_sha,pr_number=host.get('number',host.get('pull_request',{}).get('number')) if event=='pull_request' else None)
        if previous:base=previous['headSha']
    # A failed/expired/unknown publisher forces source materialization, never
    # guesses event.before or runs source in a protected downstream job.
    for key,value in [('head',head),('version',version),('event',kind),('base',base),('materialize-all',str(not bool(base)).lower())]:output(key,value)



if __name__=='__main__':
    try:
        from github import GitHub
        prepare(Path.cwd(),Runner(),github=GitHub(os.environ['GITHUB_REPOSITORY']))
    except Exception:raise SystemExit('lifecycle-preparation-failed') from None
