"""Bounded structured lifecycle evidence. Never serialize exception text or process output."""
import json
import os
from pathlib import Path
import re
import time
from functools import wraps
from contracts import ContractError
from executor import ExecutionError


def error_category(error):
    if isinstance(error, ContractError) or type(error).__name__ == 'ProviderError':
        code = getattr(error,'code','contract-failed')
        return code if isinstance(code,str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}',code) else 'contract-failed'
    if isinstance(error,ExecutionError):return 'process-failed'
    return 'internal-error'


def event(phase,status,**details):
    value={'phase':phase,'status':status}
    patterns={'component':r'[a-z][a-z0-9-]{0,47}','target':r'[a-z][a-z0-9-]{0,47}',
        'source':r'[0-9a-f]{40}','digest':r'sha256:[0-9a-f]{64}',
        'version':r'[0-9A-Za-z.+-]{1,256}','reason':r'[a-z][a-z0-9-]{0,63}',
        'errorCategory':r'[a-z][a-z0-9-]{0,63}',
        'namespace':r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'}
    for key,item in details.items():
        if key in patterns and isinstance(item,str) and re.fullmatch(patterns[key],item):value[key]=item
        elif key in ('durationMs','selected','skipped','reused','failed','succeeded') and type(item) is int and item>=0:value[key]=item
    if details.get('provider') in ('aws','gcp','azure'):value['provider']=details['provider']
    link=details.get('artifactLink')
    if isinstance(link,dict) and set(link)=={'repository','runId','artifactId','url'}:
        repository,run,artifact=link['repository'],link['runId'],link['artifactId']
        if (isinstance(repository,str) and len(repository)<=200 and re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',repository)
            and repository.split('/')[1] not in ('.','..')
            and all(isinstance(item,str) and re.fullmatch(r'[1-9][0-9]{0,19}',item) for item in (run,artifact))):
            expected='https://github.com/'+repository+'/actions/runs/'+run+'/artifacts/'+artifact
            if link['url']==expected:value['artifactUrl']=expected
    line=json.dumps(value,sort_keys=True,separators=(',',':'))
    root=Path(os.environ.get('CLOUDOPSWORKS_DIAGNOSTICS','.lifecycle-diagnostics'))
    root.mkdir(parents=True,exist_ok=True)
    with (root/'events.jsonl').open('a') as stream:stream.write(line+'\n')
    print(line)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write('```json\n'+line+'\n```\n')
    return value


def observed(phase):
    def decorate(function):
        @wraps(function)
        def run(*args,**kwargs):
            started=time.monotonic()
            identity={key:getattr(args[0],key) for key in ('component','target') if args and hasattr(args[0],key)}
            try:
                result=function(*args,**kwargs)
                event(phase,'succeeded',**identity,durationMs=int((time.monotonic()-started)*1000))
                return result
            except Exception as error:
                event(phase,'failed',**identity,errorCategory=error_category(error),durationMs=int((time.monotonic()-started)*1000),failed=1)
                raise
        return run
    return decorate
