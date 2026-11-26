"""Database connection pool sizing and the admission of requests (Phase 4.1, found by the load test).

The problem. The API runs its routes in a pool of worker threads (40 in the web framework's default). One request needs
several of them one after the other (open the session, check the login, run the route, close the session) and holds a
database connection from the login check until the session is closed. The connection pool is small (5 + 10). When many
requests arrive at once, every worker thread ends up waiting for a connection while the requests that own the
connections wait for a worker thread to continue: nobody can proceed until the pool's 30 second timeout fires, which
answers the waiting requests with HTTP 500 and "QueuePool limit ... reached". The load test showed it at 400 simulated
phones and with 300 phones sending at the same instant (what happens when every phone uploads at once after an API
restart); the API was idle and unresponsive for the length of the timeout, repeatedly.

The fix. A request is admitted only when a slot is free (`NUQATI_DB_REQUEST_SLOTS`, default: the pool size minus
RESERVED_CONNECTIONS). The waiting happens in the event loop, with no worker thread and no connection, so the requests
that hold connections always find a thread and finish; the rest queue for milliseconds. The reserved connections are for
the readiness probe, routes that open a second connection, and migrations.

Settings (all optional). NUQATI_DB_POOL_SIZE (5), NUQATI_DB_MAX_OVERFLOW (10), NUQATI_DB_REQUEST_SLOTS (pool total minus 5,
at least 1; 0 = no admission control, the behaviour before this change, only for experiments). A slot count above the pool total
minus 1 is reduced to it, because that is the configuration that can stall. Unusable values are ignored with a warning.

Standard library only, so it can be tested without the web framework or a database.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

log = logging.getLogger('nuqati.db_pool')

POOL_SIZE_DEFAULT = 5
MAX_OVERFLOW_DEFAULT = 10
RESERVED_CONNECTIONS = 5


@dataclass(frozen=True)
class PoolSettings:
    pool_size: int
    max_overflow: int
    request_slots: int  # 0 = unlimited

    @property
    def total(self) -> int:
        return self.pool_size + self.max_overflow


def _integer(environ, name: str, default: int, low: int, high: int) -> int:
    raw = str(environ.get(name, '')).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        log.warning('%s=%r is not a whole number from %d to %d; using %d', name, raw, low, high, default)
        return default
    return value


def load_pool_settings(environ=None) -> PoolSettings:
    environ = os.environ if environ is None else environ
    size = _integer(environ, 'NUQATI_DB_POOL_SIZE', POOL_SIZE_DEFAULT, 1, 100)
    overflow = _integer(environ, 'NUQATI_DB_MAX_OVERFLOW', MAX_OVERFLOW_DEFAULT, 0, 200)
    total = size + overflow
    default_slots = max(1, total - RESERVED_CONNECTIONS)
    slots = _integer(environ, 'NUQATI_DB_REQUEST_SLOTS', default_slots, 0, 1000)
    if slots > total - 1 and slots != 0:
        log.warning('NUQATI_DB_REQUEST_SLOTS=%d is not below the pool total of %d connections, which can stall the API under '
                    'load; using %d', slots, total, max(1, total - 1))
        slots = max(1, total - 1)
    return PoolSettings(size, overflow, slots)


# One semaphore per event loop (there is one in production; tests start several). The loop is kept in the value so that a
# recycled id() can never hand a new loop an old semaphore; the slot count is kept so a changed setting takes effect.
_semaphores: dict[int, tuple[object, asyncio.Semaphore, int]] = {}


class _NoLimit:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def admission(slots: int):
    """Async context manager: waits (in the event loop, holding no thread) until fewer than `slots` requests are admitted."""
    if slots <= 0:
        return _NoLimit()
    loop = asyncio.get_running_loop()
    entry = _semaphores.get(id(loop))
    if entry is None or entry[0] is not loop or entry[2] != slots:
        entry = (loop, asyncio.Semaphore(slots), slots)
        _semaphores[id(loop)] = entry
    return entry[1]
