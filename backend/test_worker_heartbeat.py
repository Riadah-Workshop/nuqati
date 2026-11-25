"""Tests for app/heartbeat.py and for the way the two background workers and compose.yml use it.

The real workers (tracker receiver, report scheduler) are started in containers by the "Worker health checks" job
in .github/workflows/ci.yml. These tests are fast and cover the edge cases: stale and missing heartbeats, bad
settings, the watchdog decision and its real process exit, and the wiring between compose.yml and the worker code.
"""

import ast
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app import heartbeat  # noqa: E402  (standard library only, safe to import without a database)


@pytest.fixture(autouse=True)
def heartbeat_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NUQATI_HEARTBEAT_DIR", str(tmp_path))
    monkeypatch.delenv("NUQATI_WORKER_WATCHDOG_SECONDS", raising=False)
    return tmp_path


def make_old(name, seconds):
    path = heartbeat.path_for(name)
    path.touch()
    t = time.time() - seconds
    os.utime(path, (t, t))


# ---------- beat / age / check ----------

def test_beat_creates_the_file_and_refreshes_it():
    assert heartbeat.age_seconds("worker") is None
    heartbeat.beat("worker")
    assert heartbeat.path_for("worker").exists()
    make_old("worker", 100)
    assert heartbeat.age_seconds("worker") >= 99
    heartbeat.beat("worker")
    assert heartbeat.age_seconds("worker") < 5


def test_check_is_ok_when_fresh_and_fails_when_stale_or_missing():
    ok, message = heartbeat.check("worker", 90)
    assert not ok and "no heartbeat yet" in message
    heartbeat.beat("worker")
    ok, message = heartbeat.check("worker", 90)
    assert ok and "ok" in message
    make_old("worker", 200)
    ok, message = heartbeat.check("worker", 90)
    assert not ok and "limit 90s" in message


def test_check_uses_the_given_clock():
    heartbeat.beat("worker")
    now = time.time() + 500
    assert heartbeat.check("worker", 90, now=now)[0] is False
    assert heartbeat.check("worker", 600, now=now)[0] is True


@pytest.mark.parametrize("bad", ["", "Worker", "a/b", "../etc", "a b", "x" * 41, "tel-tonika"])
def test_names_are_restricted_to_a_safe_pattern(bad):
    with pytest.raises(ValueError):
        heartbeat.path_for(bad)


def test_beat_never_raises_even_when_the_directory_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("NUQATI_HEARTBEAT_DIR", str(tmp_path / "does" / "not" / "exist"))
    heartbeat.beat("worker")  # a full or read-only disk must not stop the worker it is watching
    heartbeat.beat("not a valid name")


def run_cli(args, tmp_path):
    env = {**os.environ, "NUQATI_HEARTBEAT_DIR": str(tmp_path), "PYTHONPATH": str(BACKEND)}
    return subprocess.run([sys.executable, "-B", "-m", "app.heartbeat", *args], env=env, capture_output=True, text=True, timeout=30)


def test_command_line_exit_codes(tmp_path):
    assert run_cli(["teltonika", "90"], tmp_path).returncode == 1           # no heartbeat yet
    heartbeat.beat("teltonika")
    r = run_cli(["teltonika", "90"], tmp_path)
    assert r.returncode == 0 and "ok" in r.stdout
    make_old("teltonika", 300)
    r = run_cli(["teltonika", "90"], tmp_path)
    assert r.returncode == 1 and "limit 90s" in r.stdout
    assert run_cli(["teltonika"], tmp_path).returncode == 2                 # usage
    assert run_cli(["teltonika", "soon"], tmp_path).returncode == 2
    assert run_cli(["../x", "90"], tmp_path).returncode == 2                # invalid name


def test_command_line_needs_no_database_or_settings(tmp_path):
    env = {"PATH": os.environ["PATH"], "NUQATI_HEARTBEAT_DIR": str(tmp_path), "PYTHONPATH": str(BACKEND)}  # no DATABASE_URL, no secret
    heartbeat.beat("teltonika")
    r = subprocess.run([sys.executable, "-B", "-m", "app.heartbeat", "teltonika", "90"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_module_imports_only_the_standard_library():
    tree = ast.parse((BACKEND / "app" / "heartbeat.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "heartbeat.py must not import other app modules"
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


# ---------- watchdog ----------

@pytest.mark.parametrize("raw,expected", [
    (None, 0), ("", 0), ("0", 0), ("  ", 0), ("abc", 0), ("-5", 0), ("600", 600), ("120", 120), ("30", 120), ("1", 120),
])
def test_watchdog_limit_parsing(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("NUQATI_WORKER_WATCHDOG_SECONDS", raw)
    assert heartbeat.watchdog_limit() == expected


@pytest.mark.parametrize("raw", [None, "", "0"])
def test_an_unset_or_zero_watchdog_setting_is_silent(monkeypatch, caplog, raw):
    if raw is not None:
        monkeypatch.setenv("NUQATI_WORKER_WATCHDOG_SECONDS", raw)
    with caplog.at_level("DEBUG", logger="nuqati.heartbeat"):
        assert heartbeat.watchdog_limit() == 0
    assert caplog.records == []


def test_watch_once_only_acts_on_a_stale_heartbeat():
    calls = []
    assert heartbeat.watch_once("worker", 120, calls.append) is False       # no heartbeat yet: not a hang, still starting
    heartbeat.beat("worker")
    assert heartbeat.watch_once("worker", 120, calls.append) is False
    make_old("worker", 500)
    assert heartbeat.watch_once("worker", 120, calls.append) is True
    assert calls == [70]  # the documented exit code (docs/OPERATIONS.md)


def test_watchdog_is_off_by_default():
    assert heartbeat.start_watchdog("worker", exit_fn=lambda code: None) is None
    assert not heartbeat.path_for("worker").exists()


def test_watchdog_thread_ends_the_process_after_a_stale_heartbeat(monkeypatch):
    monkeypatch.setenv("NUQATI_WORKER_WATCHDOG_SECONDS", "600")
    exits = []
    park = threading.Event()  # never set: once the watchdog has fired, its thread just waits (it is a daemon)

    def fake_sleep(seconds):
        if exits:
            park.wait()
        time.sleep(0.01)

    def fake_exit(code):
        exits.append(code)

    monkeypatch.setattr(heartbeat, "time", types.SimpleNamespace(sleep=fake_sleep, time=time.time))
    thread = heartbeat.start_watchdog("worker", exit_fn=fake_exit)
    assert thread is not None and thread.daemon and heartbeat.path_for("worker").exists()  # start_watchdog beats once
    time.sleep(0.2)
    assert exits == []                                                       # fresh heartbeat: nothing happens
    make_old("worker", 5000)
    deadline = time.time() + 5
    while not exits and time.time() < deadline:
        time.sleep(0.02)
    assert exits[:1] == [70]


def test_a_real_process_exits_with_code_70_when_its_heartbeat_stops(tmp_path):
    code = (
        "import os, time\n"
        "import app.heartbeat as h\n"
        "h.MIN_WATCHDOG_SECONDS = 1\n"
        "os.environ['NUQATI_WORKER_WATCHDOG_SECONDS'] = '2'\n"
        "h.start_watchdog('worker')\n"
        "time.sleep(60)\n"   # the worker 'hangs': it never beats again
    )
    env = {"PATH": os.environ["PATH"], "NUQATI_HEARTBEAT_DIR": str(tmp_path), "PYTHONPATH": str(BACKEND)}
    started = time.time()
    r = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, text=True, timeout=45)
    assert r.returncode == 70, (r.returncode, r.stderr)
    assert time.time() - started < 30
    assert "ending the process" in r.stderr


# ---------- wiring: compose.yml and the worker code must agree ----------

def _compose_services():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "compose.yml").read_text())["services"]


def _calls(source: str, function: str | None = None):
    tree = ast.parse(source)
    scope = tree
    if function:
        scope = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
    found = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "heartbeat":
            found.append((node.func.attr, [a.value for a in node.args if isinstance(a, ast.Constant)]))
    return found


@pytest.mark.parametrize("service,module,name,limit,function", [
    ("teltonika", "teltonika_receiver.py", "teltonika", 90, "keep_heartbeat"),
    ("report_scheduler", "report_subscriptions.py", "report_scheduler", 900, "main"),
])
def test_each_worker_beats_under_the_name_its_healthcheck_reads(service, module, name, limit, function):
    health = _compose_services()[service]["healthcheck"]["test"]
    assert health == ["CMD", "python", "-m", "app.heartbeat", name, str(limit)]
    assert ("beat", [name]) in _calls((BACKEND / "app" / module).read_text(), function)
    assert ("start_watchdog", [name]) in _calls((BACKEND / "app" / module).read_text())


def test_receiver_starts_its_heartbeat_task_and_keeps_a_reference_to_it():
    source = (BACKEND / "app" / "teltonika_receiver.py").read_text()
    tree = ast.parse(source)
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    assigned = [n for n in ast.walk(main) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                and getattr(n.value.func, "attr", "") == "create_task"]
    assert assigned, "the heartbeat task must be stored in a variable, or asyncio may garbage-collect it"
    assert "keep_heartbeat" in ast.dump(assigned[0])


def test_healthcheck_limits_leave_room_for_missed_beats():
    assert 90 >= 4 * 15                      # the receiver beats every 15 s
    src = (BACKEND / "app" / "teltonika_receiver.py").read_text()
    assert "HEARTBEAT_SECONDS=15" in src


def test_both_workers_pass_the_watchdog_setting_through_and_default_to_off():
    services = _compose_services()
    for name in ("teltonika", "report_scheduler"):
        assert services[name]["environment"]["NUQATI_WORKER_WATCHDOG_SECONDS"] == "${NUQATI_WORKER_WATCHDOG_SECONDS:-0}"
    assert "NUQATI_WORKER_WATCHDOG_SECONDS" in (ROOT / ".env.example").read_text()


def test_the_healthchecks_do_not_depend_on_the_database_or_the_network():
    for name in ("teltonika", "report_scheduler"):
        test = " ".join(_compose_services()[name]["healthcheck"]["test"])
        assert "curl" not in test and "urlopen" not in test and "5027" not in test
