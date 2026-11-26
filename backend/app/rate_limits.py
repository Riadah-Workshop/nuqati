"""Per-user request limits for GPS ingestion, exports and reports (Phase 4.1, finding S9).

Why per user and in memory
- Keyed by the authenticated user id, never by IP address: behind Traefik and Caddy the API sees the proxy's address,
  so an IP key would put every client in one bucket (code-issue 04). A user id is the same wherever the request came from.
- Counted in the API process, with no database write per request. The API runs as one process (see backend/Dockerfile);
  if it is ever started with several workers, each worker counts separately, so the effective limit is that many times
  looser. That is acceptable for abuse protection and is documented in docs/OPERATIONS.md.
- A token bucket: a burst of `capacity` requests is always allowed, then `refill_per_second` requests per second. That
  suits the driver app, which replays up to 100 queued GPS points in a row after being offline and otherwise sends
  about one point every 2 seconds.

Modes, set per group in the environment (default in brackets)
- NUQATI_RATE_LIMIT_INGEST  (log)      GPS samples, safety events, tracking heartbeats
- NUQATI_RATE_LIMIT_REPORTS (enforce)  exports and report screens
  off      no counting at all
  log      count and write a log line when a request would have been refused, but let it through
  enforce  refuse with HTTP 429 and a Retry-After header
An unknown value is ignored (the default applies), so a typo never switches protection off.

The 429 text must never contain the phrase the driver app treats as "drop this GPS point for good"
(driver_app/main.dart, around the `knownNonRetryableGpsSample` check). Any other 429 keeps the point on the phone and
it is sent again at the next sync, so a wrongly tight limit delays data but never loses it.

This module imports only the standard library, so it can be tested without the web framework.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass

log = logging.getLogger('nuqati.rate_limits')

MODES = ('off', 'log', 'enforce')
GROUP_ENV = {'ingest': 'NUQATI_RATE_LIMIT_INGEST', 'reports': 'NUQATI_RATE_LIMIT_REPORTS'}
GROUP_DEFAULT = {'ingest': 'log', 'reports': 'enforce'}

LOG_EVERY_SECONDS = 60.0   # at most one log line per user and scope per minute
MAX_BUCKETS = 100_000      # memory bound; idle buckets are equivalent to new ones, so dropping the oldest loses nothing


@dataclass(frozen=True)
class Rule:
    capacity: float          # burst: requests allowed in a row from a full bucket
    refill_per_second: float  # sustained rate once the burst is used
    group: str               # key of GROUP_ENV


# Sized from the driver app's real behaviour (see docs/OPERATIONS.md, "Rate limits"): about 0.5 GPS requests per second
# while driving, up to 100 in a row when replaying a backlog, one heartbeat per minute.
RULES: dict[str, Rule] = {
    'gps_sample':   Rule(capacity=300, refill_per_second=5.0, group='ingest'),
    'safety_event': Rule(capacity=100, refill_per_second=2.0, group='ingest'),
    'heartbeat':    Rule(capacity=20,  refill_per_second=0.5, group='ingest'),
    'export':       Rule(capacity=10,  refill_per_second=0.2, group='reports'),    # file generation is CPU heavy
    'report':       Rule(capacity=60,  refill_per_second=1.0, group='reports'),
}


def mode_for(group: str) -> str:
    raw = os.getenv(GROUP_ENV[group], '').strip().lower()
    if raw in MODES:
        return raw
    if raw:
        log.warning('%s=%r is not one of %s; using %r', GROUP_ENV[group], raw, '/'.join(MODES), GROUP_DEFAULT[group])
    return GROUP_DEFAULT[group]


@dataclass(frozen=True)
class Decision:
    refuse: bool          # the caller must answer 429
    exceeded: bool        # the bucket was empty (true in log mode too)
    retry_after: int      # whole seconds, at least 1 when exceeded


_ALLOWED = Decision(refuse=False, exceeded=False, retry_after=0)


class RateLimiter:
    """Thread-safe token buckets. FastAPI runs these routes in a thread pool, hence the lock."""

    def __init__(self, clock=time.monotonic, max_buckets: int = MAX_BUCKETS):
        self._clock = clock
        self._max = max_buckets
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, int], list[float]] = {}  # key -> [tokens, last_seen, last_logged]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._buckets)

    def take(self, scope: str, user_id: int, rule: Rule) -> float:
        """Use one token. Returns 0.0 when allowed, otherwise the seconds until a token is available."""
        key = (scope, user_id)
        with self._lock:
            now = self._clock()  # read under the lock so timestamps are in the same order as the updates
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max:
                    self._drop_oldest()
                bucket = [rule.capacity, now, -LOG_EVERY_SECONDS]
                self._buckets[key] = bucket
            tokens = min(rule.capacity, bucket[0] + max(0.0, now - bucket[1]) * rule.refill_per_second)
            bucket[1] = now
            if tokens >= 1.0:
                bucket[0] = tokens - 1.0
                return 0.0
            bucket[0] = tokens
            return (1.0 - tokens) / rule.refill_per_second

    def should_log(self, scope: str, user_id: int) -> bool:
        """True at most once per LOG_EVERY_SECONDS for one user and scope."""
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get((scope, user_id))
            if bucket is None or now - bucket[2] < LOG_EVERY_SECONDS:
                return False
            bucket[2] = now
            return True

    def _drop_oldest(self) -> None:  # caller holds the lock
        victims = sorted(self._buckets, key=lambda k: self._buckets[k][1])[: max(1, self._max // 10)]
        for key in victims:
            del self._buckets[key]


LIMITER = RateLimiter()


def evaluate(scope: str, user_id: int, limiter: RateLimiter | None = None) -> Decision:
    """Count one request and say what to do with it. Never raises."""
    rule = RULES[scope]
    mode = mode_for(rule.group)
    if mode == 'off':
        return _ALLOWED
    limiter = limiter or LIMITER
    wait = limiter.take(scope, user_id, rule)
    if wait <= 0.0:
        return _ALLOWED
    retry_after = max(1, math.ceil(wait))
    if limiter.should_log(scope, user_id):
        log.warning('rate_limit %s scope=%s user=%s retry_after=%ss (capacity %g, %g per second)',
                    'REFUSED' if mode == 'enforce' else 'WOULD_REFUSE (log mode, request allowed)',
                    scope, user_id, retry_after, rule.capacity, rule.refill_per_second)
    return Decision(refuse=(mode == 'enforce'), exceeded=True, retry_after=retry_after)


def refusal_text(retry_after: int) -> str:
    # Deliberately different from the phrase the driver app uses to drop a GPS point (see the module docstring).
    return f'Too many requests. Try again in {retry_after} seconds.'


def limit(scope: str):
    """FastAPI dependency for one route:  @app.post(path, dependencies=[Depends(limit('gps_sample'))])

    It runs after authentication (`current_user` is shared with the route, so no extra database work) and before the
    route body. Unauthenticated requests are therefore answered 401 and never create a bucket.
    """
    if scope not in RULES:
        raise KeyError(f'unknown rate limit scope {scope!r}')
    from fastapi import Depends, HTTPException  # imported here so the rest of this module needs no framework
    from .auth import current_user

    async def rate_limit_dependency(user=Depends(current_user)):
        # async on purpose: the check is a few microseconds of in-memory work, so it runs on the event loop and does not
        # need a worker thread (a request that holds a database connection must not wait for a free thread here)
        decision = evaluate(scope, user.id)
        if decision.refuse:
            raise HTTPException(429, refusal_text(decision.retry_after), headers={'Retry-After': str(decision.retry_after)})

    rate_limit_dependency.__name__ = f'rate_limit_{scope}'
    return rate_limit_dependency
