"""Liveness signal for the background workers (tracker receiver and report scheduler).

A worker calls ``beat(name)`` regularly from the code path that must keep running. That touches a small file.
Two things read it:

* the container healthcheck: ``python -m app.heartbeat <name> <max_age_seconds>`` exits 0 while the file is fresh and
  1 when it is stale or missing, so Coolify shows the container as unhealthy (Docker does not restart an unhealthy
  container by itself);
* an optional watchdog thread (``start_watchdog``) that ends the process when the file goes stale, so that
  ``restart: unless-stopped`` starts a fresh one. Off unless ``NUQATI_WORKER_WATCHDOG_SECONDS`` is set to a
  number of seconds (minimum 120).

This module imports only the standard library on purpose: the healthcheck runs it every few seconds and it must
not need a database, settings or any other part of the application.
"""

import logging
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("nuqati.heartbeat")

NAME_PATTERN = re.compile(r"[a-z0-9_]{1,40}")
MIN_WATCHDOG_SECONDS = 120   # below this a slow but healthy cycle could be mistaken for a hang
WATCHDOG_EXIT_CODE = 70      # shows up in `docker logs` / Coolify as the reason for the restart


def _directory() -> Path:
    return Path(os.environ.get("NUQATI_HEARTBEAT_DIR") or tempfile.gettempdir())


def path_for(name: str) -> Path:
    if not NAME_PATTERN.fullmatch(name or ""):
        raise ValueError(f"invalid heartbeat name {name!r}")
    return _directory() / f"nuqati-{name}.alive"


def beat(name: str) -> None:
    """Record 'still alive'. Never raises: a full disk must not stop the worker it is watching."""
    try:
        path = path_for(name)
        with open(path, "a"):
            os.utime(path, None)
    except (OSError, ValueError) as exc:
        log.warning("heartbeat for %s could not be written: %s", name, type(exc).__name__)


def age_seconds(name: str, now: float | None = None) -> float | None:
    """Seconds since the last beat, or None if there has been none."""
    try:
        mtime = path_for(name).stat().st_mtime
    except OSError:
        return None
    return max(0.0, (time.time() if now is None else now) - mtime)


def check(name: str, max_age: float, now: float | None = None) -> tuple[bool, str]:
    age = age_seconds(name, now)
    if age is None:
        return False, f"{name}: no heartbeat yet"
    if age > max_age:
        return False, f"{name}: last heartbeat {age:.0f}s ago (limit {max_age:.0f}s)"
    return True, f"{name}: ok, last heartbeat {age:.0f}s ago"


def watchdog_limit() -> int:
    """Configured watchdog limit in seconds; 0 means off. Bad values switch it off rather than crash the worker."""
    raw = (os.environ.get("NUQATI_WORKER_WATCHDOG_SECONDS") or "").strip()
    if not raw or raw == "0":
        return 0
    if not raw.isdigit():
        log.warning("NUQATI_WORKER_WATCHDOG_SECONDS=%r is not a whole number: watchdog stays off", raw)
        return 0
    value = int(raw)
    if value < MIN_WATCHDOG_SECONDS:
        log.warning("NUQATI_WORKER_WATCHDOG_SECONDS=%s is below the minimum: using %s", value, MIN_WATCHDOG_SECONDS)
        return MIN_WATCHDOG_SECONDS
    return value


def watch_once(name: str, limit: float, exit_fn=os._exit, now: float | None = None) -> bool:
    """One watchdog decision. Returns True if it ended the process."""
    age = age_seconds(name, now)
    if age is not None and age > limit:
        log.critical("%s: no heartbeat for %.0fs (limit %.0fs): ending the process so it is restarted", name, age, limit)
        sys.stderr.flush()
        exit_fn(WATCHDOG_EXIT_CODE)
        return True
    return False


def start_watchdog(name: str, exit_fn=os._exit) -> threading.Thread | None:
    """Start the watchdog thread if NUQATI_WORKER_WATCHDOG_SECONDS asks for it. Returns the thread or None."""
    limit = watchdog_limit()
    if not limit:
        return None
    beat(name)  # the worker may need a while to start; the clock starts now

    def run() -> None:
        poll = max(5.0, min(30.0, limit / 4))
        while True:
            time.sleep(poll)
            watch_once(name, limit, exit_fn)

    thread = threading.Thread(target=run, name=f"watchdog-{name}", daemon=True)
    thread.start()
    log.info("%s: watchdog on, the process is restarted after %ss without a heartbeat", name, limit)
    return thread


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].replace(".", "", 1).isdigit():
        print("usage: python -m app.heartbeat <name> <max_age_seconds>", file=sys.stderr)
        return 2
    try:
        ok, message = check(argv[0], float(argv[1]))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
