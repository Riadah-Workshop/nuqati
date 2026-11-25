"""Logic tests for ops/backup/backup.sh and restore_drill.sh using stand-in PostgreSQL programs.

The real thing (pg_dump, pg_restore, a PostgreSQL server) is exercised by the "Backup and restore drill"
job in .github/workflows/ci.yml. These tests are fast and cover the edge cases that job does not:
pruning, failure handling, partial files, configuration errors and the health check.
"""

import os
import stat
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "ops" / "backup" / "backup.sh"
DRILL = ROOT / "ops" / "backup" / "restore_drill.sh"

FAKE_PG_DUMP = """#!/bin/sh
# stand-in for pg_dump: honours -f FILE, FAKE_DUMP_BYTES and FAKE_PG_DUMP_FAIL
out=""
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && out="$2"; shift; done
if [ -n "${FAKE_PG_DUMP_PARTIAL_THEN_FAIL:-}" ]; then
  head -c 500 /dev/zero | tr '\\0' 'x' > "$out"; echo "pg_dump: connection lost" >&2; exit 1
fi
[ -n "${FAKE_PG_DUMP_FAIL:-}" ] && { echo "pg_dump: connection refused" >&2; exit 1; }
head -c "${FAKE_DUMP_BYTES:-2000}" /dev/zero | tr '\\0' 'x' > "$out"
"""

FAKE_PG_RESTORE = """#!/bin/sh
# stand-in for pg_restore: --list is the read-back check, anything else is the drill restore
for a in "$@"; do
  if [ "$a" = "--list" ]; then [ -n "${FAKE_LIST_FAIL:-}" ] && exit 1; exit 0; fi
done
[ -n "${FAKE_RESTORE_FAIL:-}" ] && { echo "pg_restore: error" >&2; exit 1; }
echo restore >> "$FAKE_LOG"
exit 0
"""

FAKE_PG_ISREADY = """#!/bin/sh
exit 0
"""

FAKE_PSQL = """#!/bin/sh
# stand-in for psql: answers the few queries restore_drill.sh asks
db=""; sql=""
while [ $# -gt 0 ]; do
  case "$1" in -d) db="$2"; shift ;; -c) sql="$2"; shift ;; esac
  shift
done
echo "psql $db: $sql" >> "$FAKE_LOG"
case "$sql" in
  *"DROP DATABASE"*|*"CREATE DATABASE"*) exit 0 ;;
  *"information_schema.tables"*) [ "$db" = "$FAKE_COPY_DB" ] && echo "${FAKE_COPY_TABLES:-12}" || echo 12 ;;
  *to_regclass*)
    if [ "$db" = "$FAKE_COPY_DB" ]; then
      for t in ${FAKE_COPY_MISSING:-}; do case "$sql" in *"public.$t'"*) echo f; exit 0 ;; esac; done
    fi
    echo t ;;
  *"count(*) FROM companies"*) [ "$db" = "$FAKE_COPY_DB" ] && echo "${FAKE_COPY_COMPANIES:-3}" || echo "${FAKE_LIVE_COMPANIES:-3}" ;;
  *"count(*)"*) echo 5 ;;
  *"max("*) echo "2026-11-25 20:00:00+00" ;;
  *) echo "" ;;
esac
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [("pg_dump", FAKE_PG_DUMP), ("pg_restore", FAKE_PG_RESTORE),
                       ("pg_isready", FAKE_PG_ISREADY), ("psql", FAKE_PSQL)]:
        _write_exe(bin_dir / name, body)
    backups = tmp_path / "backups"
    backups.mkdir()
    e = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_DIR": str(backups),
        "PGDATABASE": "nuqati",
        "FAKE_LOG": str(tmp_path / "fake.log"),
        "FAKE_COPY_DB": "nuqati_restore_drill",
        "HOME": str(tmp_path),
    }
    e["_backups"] = backups  # not passed to the child, only for the tests
    return e


def run(script, args, env, extra=None):
    child = {k: v for k, v in env.items() if not k.startswith("_")}
    child.update(extra or {})
    return subprocess.run(["sh", str(script), *args], env=child, capture_output=True, text=True, timeout=60)


def dumps(env):
    return sorted(p.name for p in env["_backups"].glob("nuqati-*.dump"))


def age(path: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


# ---------- backup.sh ----------

def test_scripts_are_valid_posix_sh():
    for script in (BACKUP, DRILL):
        r = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_scripts_use_no_bash_only_features():
    for script in (BACKUP, DRILL):
        text = script.read_text()
        assert text.startswith("#!/bin/sh"), script.name
        for bashism in ("[[", "]]", "<(", "declare ", "local ", "function ", "echo -e", "${!"):
            assert bashism not in text, f"{script.name} uses {bashism!r}; Alpine's sh is busybox ash"


def test_a_successful_backup_creates_a_dump_and_the_last_ok_marker(env):
    r = run(BACKUP, ["once"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(dumps(env)) == 1
    assert (env["_backups"] / "LAST_OK").exists()
    assert not list(env["_backups"].glob(".nuqati-*.partial"))
    assert " OK nuqati-" in r.stdout


def test_a_failed_dump_leaves_no_file_and_no_marker_and_exits_nonzero(env):
    r = run(BACKUP, ["once"], env, {"FAKE_PG_DUMP_FAIL": "1"})
    assert r.returncode == 1
    assert dumps(env) == []
    assert not (env["_backups"] / "LAST_OK").exists()
    assert not list(env["_backups"].glob(".nuqati-*"))
    assert "ERROR" in r.stdout


def test_a_dump_that_fails_halfway_leaves_no_partial_file(env):
    r = run(BACKUP, ["once"], env, {"FAKE_PG_DUMP_PARTIAL_THEN_FAIL": "1"})
    assert r.returncode == 1
    assert list(env["_backups"].iterdir()) == []  # neither a dump, a marker nor a .partial file


def test_a_failure_does_not_touch_the_previous_good_backup(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    before = dumps(env)
    marker = (env["_backups"] / "LAST_OK").read_text()
    r = run(BACKUP, ["once"], env, {"FAKE_PG_DUMP_FAIL": "1"})
    assert r.returncode == 1
    assert dumps(env) == before
    assert (env["_backups"] / "LAST_OK").read_text() == marker


def test_a_dump_that_cannot_be_read_back_is_discarded(env):
    r = run(BACKUP, ["once"], env, {"FAKE_LIST_FAIL": "1"})
    assert r.returncode == 1
    assert dumps(env) == []
    assert not (env["_backups"] / "LAST_OK").exists()
    assert "cannot be read back" in r.stdout


def test_an_empty_dump_is_discarded(env):
    r = run(BACKUP, ["once"], env, {"FAKE_DUMP_BYTES": "0"})
    assert r.returncode == 1
    assert dumps(env) == []


def test_old_dumps_are_pruned_but_the_newest_ones_are_always_kept(env):
    d = env["_backups"]
    for i, days in enumerate([40, 30, 20, 16, 2]):  # five existing dumps, four of them older than 14 days
        p = d / f"nuqati-2026010{i}T000000Z.dump"
        p.write_bytes(b"x" * 100)
        age(p, days)
    assert run(BACKUP, ["once"], env, {"NUQATI_BACKUP_KEEP_DAYS": "14", "NUQATI_BACKUP_MIN_KEEP": "3"}).returncode == 0
    left = dumps(env)
    # new dump + the 2-day-old one + the next newest (MIN_KEEP=3 protects three dumps); the others are gone
    assert len(left) == 3, left
    assert "nuqati-20260104T000000Z.dump" in left  # the 2-day-old dump survives


def test_min_keep_protects_dumps_even_when_all_are_old(env):
    d = env["_backups"]
    for i, days in enumerate([90, 80, 70, 60]):
        p = d / f"nuqati-2025010{i}T000000Z.dump"
        p.write_bytes(b"x" * 100)
        age(p, days)
    assert run(BACKUP, ["once"], env, {"NUQATI_BACKUP_MIN_KEEP": "3"}).returncode == 0
    assert len(dumps(env)) == 3  # the new dump and the two newest old ones


def test_a_much_smaller_dump_produces_a_warning(env):
    assert run(BACKUP, ["once"], env, {"FAKE_DUMP_BYTES": "10000"}).returncode == 0
    time.sleep(1.1)  # file names carry a one-second timestamp
    r = run(BACKUP, ["once"], env, {"FAKE_DUMP_BYTES": "1000"})
    assert r.returncode == 0
    assert "WARNING" in r.stdout and "less than half" in r.stdout


@pytest.mark.parametrize("name,value", [
    ("NUQATI_BACKUP_HOUR_UTC", "24"), ("NUQATI_BACKUP_HOUR_UTC", "abc"),
    ("NUQATI_BACKUP_KEEP_DAYS", "0"), ("NUQATI_BACKUP_KEEP_DAYS", "-3"),
    ("NUQATI_BACKUP_MIN_KEEP", "0"), ("NUQATI_BACKUP_MAX_AGE_HOURS", "x"),
])
def test_invalid_settings_stop_the_container_with_a_clear_message(env, name, value):
    r = run(BACKUP, ["once"], env, {name: value})
    assert r.returncode == 2
    assert "ERROR" in r.stdout
    assert dumps(env) == []


def test_unknown_mode_prints_usage(env):
    r = run(BACKUP, ["explode"], env)
    assert r.returncode == 2 and "usage" in r.stderr


# ---------- health ----------

def test_health_fails_without_a_backup_and_passes_after_one(env):
    assert run(BACKUP, ["health"], env).returncode == 1
    assert run(BACKUP, ["once"], env).returncode == 0
    r = run(BACKUP, ["health"], env)
    assert r.returncode == 0 and "ok" in r.stdout


def test_health_fails_when_the_last_backup_is_too_old(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    age(env["_backups"] / "LAST_OK", 2)  # 48 hours
    r = run(BACKUP, ["health"], env)
    assert r.returncode == 1 and "hours old" in r.stdout


def test_health_limit_is_configurable(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    age(env["_backups"] / "LAST_OK", 2)
    assert run(BACKUP, ["health"], env, {"NUQATI_BACKUP_MAX_AGE_HOURS": "72"}).returncode == 0


# ---------- restore_drill.sh ----------

def _seed_dump(env):
    p = env["_backups"] / "nuqati-20261125T230000Z.dump"
    p.write_bytes(b"x" * 500)
    return p


def test_drill_restores_compares_and_drops_the_copy(env):
    _seed_dump(env)
    r = run(DRILL, [], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: OK" in r.stdout
    assert "nuqati-20261125T230000Z.dump" in r.stdout
    log = Path(env["FAKE_LOG"]).read_text()
    assert 'CREATE DATABASE "nuqati_restore_drill"' in log
    assert log.rstrip().splitlines()[-1].endswith('DROP DATABASE IF EXISTS "nuqati_restore_drill"')  # always cleaned up
    assert "dropped" in r.stdout


def test_drill_fails_and_still_drops_the_copy_when_the_restore_fails(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"FAKE_RESTORE_FAIL": "1"})
    assert r.returncode == 1
    assert "RESULT: FAILED" in r.stdout
    assert 'DROP DATABASE IF EXISTS "nuqati_restore_drill"' in Path(env["FAKE_LOG"]).read_text().splitlines()[-1]


def test_drill_fails_when_the_restored_database_has_no_tables(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"FAKE_COPY_TABLES": "0"})
    assert r.returncode == 1 and "no tables" in r.stdout


def test_drill_fails_without_any_dump(env):
    r = run(DRILL, [], env)
    assert r.returncode == 1 and "no dump found" in r.stdout


def test_drill_uses_an_explicit_dump_path(env):
    other = env["_backups"] / "older.dump"
    other.write_bytes(b"x" * 300)
    _seed_dump(env)
    r = run(DRILL, [str(other)], env)
    assert r.returncode == 0 and "older.dump" in r.stdout


def test_drill_refuses_to_use_the_live_database_name(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"NUQATI_DRILL_DB": "nuqati"})
    assert r.returncode == 1 and "must not be the live database" in r.stdout
    assert not Path(env["FAKE_LOG"]).exists()  # nothing was sent to the server


@pytest.mark.parametrize("bad", ['x"; DROP DATABASE nuqati; --', "a b", "a-b"])
def test_drill_refuses_unsafe_database_names(env, bad):
    _seed_dump(env)
    r = run(DRILL, [], env, {"NUQATI_DRILL_DB": bad})
    assert r.returncode == 1 and "letters, digits and underscores" in r.stdout
    assert not Path(env["FAKE_LOG"]).exists()


def test_drill_warns_when_the_copy_has_more_rows_than_live(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"FAKE_COPY_COMPANIES": "9", "FAKE_LIVE_COMPANIES": "3"})
    assert r.returncode == 0 and "WARNINGS:" in r.stdout and "more rows than live" in r.stdout


def test_drill_fails_when_a_core_table_is_missing_from_the_copy(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"FAKE_COPY_MISSING": "companies"})
    assert r.returncode == 1
    assert "RESULT: FAILED" in r.stdout and "MISSING in the restored copy" in r.stdout


def test_drill_only_warns_when_a_later_table_is_missing_from_the_copy(env):
    _seed_dump(env)
    r = run(DRILL, [], env, {"FAKE_COPY_MISSING": "security_audit"})
    assert r.returncode == 0 and "RESULT: OK" in r.stdout
    assert "WARNINGS:" in r.stdout and "security_audit" in r.stdout
