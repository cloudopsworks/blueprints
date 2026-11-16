"""Fixed trusted chart deployment and owned-Service loopback health forwarding."""
import contextlib
import json
from pathlib import Path
import socket
import subprocess
import time

from . import common as c


@contextlib.contextmanager
def forward(executor, namespace, service, port, env):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        local = sock.getsockname()[1]
    process = subprocess.Popen(['kubectl', 'port-forward', '--address=127.0.0.1', '--namespace', namespace,
        'service/' + service, str(local) + ':' + str(port)], env={**__import__('os').environ, **env},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 15
        while True:
            c.require(process.poll() is None, 'port-forward', 'owned Service forwarding exited')
            try:
                with socket.create_connection(('127.0.0.1', local), timeout=.2):
                    break
            except OSError:
                c.require(time.monotonic() < until, 'port-forward', 'owned Service forwarding timed out')
                time.sleep(.1)
        yield 'http://127.0.0.1:' + str(local)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def deploy(r, ex, ctx, credentials, *, image=None):
    # Kept only as an explicit denial for stale internal callers. Normal v2
    # provider entrypoints must use the authorized shared IaC adapter instead.
    c.require(False,'iac-authorization-required','direct Helm workload mutation is retired')
