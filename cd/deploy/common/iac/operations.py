"""Shared native Terragrunt operation transport for legacy and component roots.

Legacy callers keep their own characterized selector, cwd, env and step guards.
Component callers pass only fixed typed argv after canonical authorization and
private saved-plan inspection. This helper performs no configuration parsing,
source execution, plan publication or provider SDK operations.
"""
from __future__ import annotations
import subprocess
import sys


def command(arguments, *, tool='terragrunt', working_directory=None):
    if not isinstance(arguments,list) or not arguments or any(not isinstance(a,str) for a in arguments):
        raise ValueError('iac_operation_arguments')
    argv=[tool,'--non-interactive']
    if working_directory is not None:argv.extend(['--working-dir',str(working_directory)])
    return [*argv,'run','--',*arguments]


def main():
    # The literal separator prevents an operation argument being mistaken for a
    # helper option. No shell or second interpretation of the arguments occurs.
    if len(sys.argv)<3 or sys.argv[1]!='--':raise SystemExit('expected literal operation separator')
    raise SystemExit(subprocess.run(command(sys.argv[2:]),check=False).returncode)


if __name__=='__main__':main()
