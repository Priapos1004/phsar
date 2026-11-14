"""A job's CPU-heavy compute, run in a process of its own."""

import asyncio
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from app.core.maintenance import restores
from app.exceptions import ComputeRestoredError


async def run_in_child(fn: Callable[..., Any], *args: Any) -> Any:
    """Run one compute call in a fresh process. Its memory peak can be a large share of the small
    VM's — a galaxy fit's grows with the catalogue and loads numba's JIT — and leaves with the
    child instead of staying in the web process, and CPU-bound work never holds the event
    loop's GIL. Spawn, not fork: a forked child would inherit the parent's threads and torch
    state.

    A restore while the child runs discards its answer (`maintenance.restores` says why)."""
    restores_before = restores()
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        result = await asyncio.get_running_loop().run_in_executor(pool, fn, *args)
    finally:
        pool.shutdown(wait=False)
    if restores() != restores_before:
        raise ComputeRestoredError()
    return result
