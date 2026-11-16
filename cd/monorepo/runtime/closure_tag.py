"""Load immutable Git objects for the existing frozen-tag primitive, no worktree."""
import argparse
import base64
import os
from pathlib import Path
import re
from closure_entry import discover
from contracts import fail
from executor import Runner, checked
from github import GitHub


def prepare(github,runner,environ,head,destination):
    selected=discover(github,runner,environ)
    if not selected['eligible'] or selected['mergeSha']!=head:fail('closure-tag-source','merged source is not eligible')
    root=Path(destination)
    if root.exists() or root.is_symlink():fail('closure-tag-workspace','Git object directory must be new')
    repository=environ['GITHUB_REPOSITORY'];token=environ['GH_TOKEN']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or any(c in token for c in '\r\n\x00'):
        fail('closure-tag-repository','repository transport is invalid')
    root.mkdir(mode=0o700)
    env={'PATH':os.environ.get('PATH',os.defpath),'HOME':str(root),'GIT_TERMINAL_PROMPT':'0',
        'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_COUNT':'1',
        'GIT_CONFIG_KEY_0':'http.https://github.com/.extraheader',
        'GIT_CONFIG_VALUE_0':'AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode()}
    checked(runner,['git','init','--bare',str(root)],env=env)
    checked(runner,['git','remote','add','origin','https://github.com/'+repository+'.git'],cwd=root,env=env)
    checked(runner,['git','fetch','--no-recurse-submodules','origin',head,'+refs/tags/*:refs/tags/*'],cwd=root,env=env)
    checked(runner,['git','update-ref','HEAD',head],cwd=root,env=env)
    if checked(runner,['git','rev-parse','--verify','HEAD^{commit}'],cwd=root,env=env).strip()!=head:
        fail('closure-tag-head','Git object identity differs')
    return root


if __name__=='__main__':
    try:
        parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare']);parser.add_argument('--head',required=True)
        parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
        prepare(GitHub(os.environ['GITHUB_REPOSITORY'],os.environ['GH_TOKEN']),Runner(inherit_environment=False),os.environ,args.head,args.out)
    except Exception:raise SystemExit('closure-tag-objects-failed') from None
