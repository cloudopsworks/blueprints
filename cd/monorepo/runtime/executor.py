"""Bounded, argv-only execution shared by trusted deployment adapters."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Protocol


class Executor(Protocol):
    def run(self, argv: list[str], *, input: str | None = None, cwd: str | Path | None = None,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]: ...


class ExecutionError(RuntimeError):
    pass


class Runner:
    def __init__(self, timeout: int = 600, output_limit: int = 8 * 1024 * 1024, *, inherit_environment: bool = True):
        self.timeout = timeout
        self.output_limit = output_limit
        self.inherit_environment = inherit_environment

    def run(self, argv, *, input=None, cwd=None, env=None):
        if not argv or any(not isinstance(a, str) or '\x00' in a for a in argv):
            raise ExecutionError('invalid executable argument vector')
        # Output is returned to the adapter, never printed. Failures intentionally
        # omit argv/stdin/output: they may include credentials or provider data.
        import selectors
        import signal
        import time
        if input is not None and len(input.encode()) > 4 * 1024 * 1024:
            raise ExecutionError('provider stdin exceeds bound')
        with tempfile.TemporaryFile() as incoming:
            if input is not None:
                incoming.write(input.encode())
                incoming.seek(0)
            process = None
            try:
                process = subprocess.Popen(argv, stdin=incoming, cwd=cwd,
                    env={**(os.environ if self.inherit_environment else {}), **(env or {})}, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, start_new_session=True)
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
                selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
                buffers = {'stdout': bytearray(), 'stderr': bytearray()}
                deadline = time.monotonic() + self.timeout
                with selector:
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ExecutionError('provider deadline exceeded')
                        for key, _ in selector.select(min(remaining, 0.2)):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            buffer = buffers[key.data]
                            if len(buffer) + len(chunk) > self.output_limit:
                                raise ExecutionError('provider output exceeds bound')
                            buffer.extend(chunk)
                returncode = process.wait(timeout=max(0.01, deadline-time.monotonic()))
                return subprocess.CompletedProcess(argv, returncode,
                    bytes(buffers['stdout']).decode('utf-8', errors='replace'),
                    bytes(buffers['stderr']).decode('utf-8', errors='replace'))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ExecutionError('provider process unavailable or deadline exceeded') from exc
            finally:
                if process is not None:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    process.stdout.close()
                    process.stderr.close()



def checked(executor, argv, **kwargs):
    result = executor.run(argv, **kwargs)
    if result.returncode:
        raise ExecutionError('provider command failed')
    return result.stdout
