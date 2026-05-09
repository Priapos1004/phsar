"""Subprocess seam for pg_dump / pg_restore / psql calls in backup_service.

Exists so failure branches (non-zero returncode, timeout, corrupt-archive
stderr) can be exercised in tests without real Postgres binaries. Real call
sites use the module-level _default_runner (asyncio.create_subprocess_exec);
tests monkeypatch it to a fake that returns canned process objects.
"""

import asyncio
from typing import Awaitable, Callable

SubprocessRunner = Callable[..., Awaitable[asyncio.subprocess.Process]]

_default_runner: SubprocessRunner = asyncio.create_subprocess_exec


async def run_capture(
    args: list[str],
    env: dict[str, str],
    timeout: float | None = None,
    capture_stdout: bool = True,
) -> tuple[int, bytes, bytes]:
    """Run a subprocess to completion and return (returncode, stdout, stderr).

    Raises asyncio.TimeoutError if timeout is exceeded; the process is killed
    and reaped before the exception propagates so the caller doesn't leak a
    zombie. Translation into domain errors (BackupIntegrityError etc.) is the
    caller's job.
    """
    proc = await _default_runner(
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if timeout is None:
            stdout, stderr = await proc.communicate()
        else:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode is None:
        # communicate() returning without setting returncode would be an asyncio
        # contract violation — fail loudly rather than silently mapping to 0.
        raise RuntimeError(f"Subprocess exited without a returncode: {args[0]!r}")
    return proc.returncode, stdout or b"", stderr or b""
