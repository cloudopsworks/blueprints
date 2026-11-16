"""Fixed frozen-tag adapter. Never synchronizes or recalculates repository HEAD."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def validate(environment):
    sha=environment.get('EXPECTED_SHA','');version=environment.get('EXPECTED_VERSION','')
    if not sha and not version:return None
    if (not re.fullmatch(r'[0-9a-f]{40}',sha)
            or not re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?',version)
            or environment.get('TRONADOR_VERSION')!='v0.6.0'):
        raise ValueError('frozen-tag-pins')
    return sha,version.removeprefix('v')


def tag(environment):
    pins=validate(environment)
    if pins is None:raise ValueError('frozen-tag-pins')
    sha,version=pins
    token=environment.get('GITHUB_TOKEN','')
    if not token or any(c in token for c in '\r\n\x00'):raise ValueError('frozen-tag-token')
    child=dict(environment)
    # Ephemeral native Git HTTPS auth, never persisted to the source checkout
    # and never placed in argv or emitted in CLI/action diagnostics.
    for key in list(child):
        if key.startswith('GIT_CONFIG_'):del child[key]
    child.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
        GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode())
    for key,value in [('user.name',environment['INPUTS_BOT_USER']),('user.email',environment['INPUTS_BOT_EMAIL'])]:
        subprocess.run(['git','config','--local',key,value],check=True,capture_output=True,text=True)
    completed=subprocess.run(['tronador','versions','tag','--expected-sha',sha,'--expected-version',version,
        '--publish','--allow-network','--json'],check=True,capture_output=True,text=True,timeout=300,env=child)
    if len(completed.stdout)>4096:raise ValueError('frozen-tag-result')
    result=json.loads(completed.stdout)
    if (not isinstance(result,dict) or set(result)!={'tag','version','sha'}
            or result!={'tag':'v'+version,'version':version,'sha':sha}):
        raise ValueError('frozen-tag-result')
    with Path(environment['GITHUB_OUTPUT']).open('a') as output:
        for key in ('tag','version','sha'):output.write(key+'='+result[key]+'\n')
    return result


if __name__=='__main__':
    try:
        if sys.argv[1:] == ['validate']:validate(os.environ)
        elif sys.argv[1:] == ['tag']:tag(os.environ)
        else:raise ValueError('frozen-tag-command')
    except Exception:raise SystemExit('frozen-tag-failed') from None
