"""Logic tests for ops/backup/offsite.sh (the encrypted off-server copy) and its use by backup.sh and restore_drill.sh.

rclone is replaced by a stand-in: a folder plays the destination, "encryption" is ROT13 plus a key check, and failures can be
injected. The real rclone (real encryption, real checksums) is exercised by the "Backup and restore drill" job in
.github/workflows/ci.yml; Google Drive itself can only be tried with real credentials (offsite.sh test).
"""

import os
import re
import stat
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_ops_backup_scripts import FAKE_PG_DUMP, FAKE_PG_ISREADY, FAKE_PG_RESTORE, FAKE_PSQL, _write_exe

ROOT = Path(__file__).resolve().parents[1]
OFFSITE = ROOT / "ops" / "backup" / "offsite.sh"
BACKUP = ROOT / "ops" / "backup" / "backup.sh"
DRILL = ROOT / "ops" / "backup" / "restore_drill.sh"

PASS1 = "first-passphrase-0123456789"
PASS2 = "second-passphrase-9876543210"

FAKE_RCLONE = r"""#!/bin/sh
# stand-in for rclone. $FAKE_REMOTE is the destination folder; "encryption" is ROT13 + a key check.
echo "rclone $*" >> "$FAKE_RCLONE_LOG"
env | grep '^RCLONE_CONFIG' >> "$FAKE_ENV_LOG"
cmd="$1"; shift
mkdir -p "$FAKE_REMOTE"
ARGS="$FAKE_REMOTE/.args.$$"; : > "$ARGS"
include=""; sep=" "; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    --log-level|--retries|--low-level-retries|--contimeout|--timeout|--drive-chunk-size|--combined) shift ;;
    --include) include="$2"; shift ;;
    --separator) sep="$2"; shift ;;
    --format) fmt="$2"; shift ;;
    --files-only|--one-way|--ignore-times) ;;
    -) printf '%s\n' "$1" >> "$ARGS" ;;
    -*) echo "fake rclone: unexpected flag $1" >&2; rm -f "$ARGS"; exit 9 ;;
    *) printf '%s\n' "$1" >> "$ARGS" ;;
  esac
  shift
done
arg() { sed -n "${1}p" "$ARGS"; }
enc() { if [ -n "${FAKE_NO_ENCRYPT:-}" ]; then cat; else tr 'A-Za-z' 'N-ZA-Mn-za-m'; fi; }
remote_file() { echo "$FAKE_REMOTE/$(basename "${1#*:}").bin"; }
fail_if() { [ "${FAKE_FAIL:-}" = "$1" ] && { echo "Failed to $1: simulated error" >&2; rm -f "$ARGS"; exit 1; }; return 0; }
case "$cmd" in
  obscure) read -r line; echo "obscured-$line" ;;
  copyto)
    src=$(arg 1); dst=$(arg 2)
    case "$dst" in
      nqcrypt:*) fail_if copyto
                 [ -f "$FAKE_REMOTE/.key" ] || printf '%s' "$RCLONE_CONFIG_NQCRYPT_PASSWORD" > "$FAKE_REMOTE/.key"
                 enc < "$src" > "$(remote_file "$dst")" ;;
      *) case "$src" in
           nqcrypt:*) fail_if download
                      f=$(remote_file "$src")
                      [ -f "$f" ] || { echo "Failed to copyto: object not found" >&2; rm -f "$ARGS"; exit 1; }
                      [ -n "${FAKE_PARTIAL:-}" ] && head -c 10 /dev/zero > "$dst"   # rclone can leave a partial file behind
                      if [ "$(cat "$FAKE_REMOTE/.key")" != "$RCLONE_CONFIG_NQCRYPT_PASSWORD" ]; then
                        echo "Failed to copyto: failed to authenticate decrypted block - bad password?" >&2; rm -f "$ARGS"; exit 1
                      fi
                      enc < "$f" > "$dst" ;;
           *) echo "fake rclone: unsupported copyto" >&2; exit 9 ;;
         esac ;;
    esac ;;
  cryptcheck)
    dir=$(arg 1); name="${include#/}"
    [ -n "${FAKE_CRYPTCHECK_SILENT:-}" ] && { rm -f "$ARGS"; exit 0; }
    f="$FAKE_REMOTE/$name.bin"
    if [ ! -f "$f" ]; then echo "- $name"; rm -f "$ARGS"; exit 1; fi
    if [ -n "${FAKE_CORRUPT:-}" ] || ! enc < "$dir/$name" | cmp -s - "$f"; then echo "* $name"; rm -f "$ARGS"; exit 1; fi
    echo "= $name" ;;
  lsf)
    fail_if lsf
    for f in "$FAKE_REMOTE"/*.bin; do
      [ -f "$f" ] || continue
      n=$(basename "$f" .bin)
      if [ "$fmt" = sp ]; then printf '%s%s%s\n' "$(stat -c %s "$f")" "$sep" "$n"; else echo "$n"; fi
    done ;;
  deletefile) fail_if delete; rm -f "$(remote_file "$(arg 1)")" ;;
  cat) cat "$FAKE_REMOTE/$(basename "$(arg 1)")" ;;
  *) echo "fake rclone: unsupported command $cmd" >&2; rm -f "$ARGS"; exit 9 ;;
esac
rc=$?
rm -f "$ARGS"
exit $rc
"""


def stamp(days_ago=0.0, now=None):
    t = (now or datetime.now(timezone.utc)) - timedelta(days=days_ago)
    return t.strftime("%Y%m%dT%H%M%SZ")


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [("rclone", FAKE_RCLONE), ("pg_dump", FAKE_PG_DUMP), ("pg_restore", FAKE_PG_RESTORE),
                       ("pg_isready", FAKE_PG_ISREADY), ("psql", FAKE_PSQL)]:
        _write_exe(bin_dir / name, body)
    backups = tmp_path / "backups"
    backups.mkdir()
    remote = tmp_path / "remote"
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    e = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_DIR": str(backups),
        "TMPDIR": str(tmp),
        "HOME": str(tmp_path),
        "PGDATABASE": "nuqati",
        "FAKE_LOG": str(tmp_path / "fake.log"),
        "FAKE_COPY_DB": "nuqati_restore_drill",
        "FAKE_REMOTE": str(remote),
        "FAKE_RCLONE_LOG": str(tmp_path / "rclone.log"),
        "FAKE_ENV_LOG": str(tmp_path / "rclone.env"),
        "NUQATI_OFFSITE": "local",
        "NUQATI_OFFSITE_PATH": str(remote),
        "NUQATI_OFFSITE_PASSWORD": PASS1,
        "NUQATI_OFFSITE_PASSWORD2": PASS2,
    }
    for f in ("rclone.log", "rclone.env"):
        (tmp_path / f).write_text("")
    e.update({"_backups": backups, "_remote": remote, "_tmp": tmp, "_path": tmp_path})
    return e


def run(script, args, env, extra=None, drop=()):
    child = {k: v for k, v in env.items() if not k.startswith("_") and k not in drop}
    child.update(extra or {})
    return subprocess.run(["sh", str(script), *args], env=child, capture_output=True, text=True, timeout=60)


def make_dump(env, when=None, content="PGDMP-plain-text-of-the-database"):
    name = f"nuqati-{when or stamp()}.dump"
    path = env["_backups"] / name
    path.write_text(content * 20)
    return path


def remote_names(env):
    r = env["_remote"]
    return sorted(p.name[:-4] for p in r.glob("*.bin")) if r.exists() else []


def seed_remote(env, days_list):
    env["_remote"].mkdir(exist_ok=True)
    names = []
    for d in days_list:
        n = f"nuqati-{stamp(d)}.dump"
        (env["_remote"] / f"{n}.bin").write_text("old")
        names.append(n)
    return names


# ---------------------------------------------------------------- settings

def test_it_is_off_unless_configured(env):
    r = run(OFFSITE, ["check-config"], env, drop=("NUQATI_OFFSITE",))
    assert r.returncode == 0 and "switched off" in r.stdout
    assert run(OFFSITE, ["status"], env, drop=("NUQATI_OFFSITE",)).stdout.strip() == "off-server copy: not configured"
    make_dump(env)
    r = run(OFFSITE, ["push"], env, drop=("NUQATI_OFFSITE",))
    assert r.returncode == 2 and "switched off" in r.stderr
    assert (env["_path"] / "rclone.log").read_text() == "", "rclone must never be started while the copy is off"
    assert run(OFFSITE, ["check-config"], env, {"NUQATI_OFFSITE": "off"}).returncode == 0


@pytest.mark.parametrize("extra,message", [
    ({"NUQATI_OFFSITE": "dropbox"}, "must be empty, drive or local"),
    ({"NUQATI_OFFSITE_PASSWORD": "short"}, "at least 16 characters"),
    ({"NUQATI_OFFSITE_PASSWORD2": ""}, "at least 16 characters"),
    ({"NUQATI_OFFSITE_PASSWORD2": PASS1}, "must differ"),
    ({"NUQATI_OFFSITE_KEEP_DAYS": "many"}, "whole number"),
    ({"NUQATI_OFFSITE_MIN_KEEP": "0"}, "at least 1"),
    ({"NUQATI_OFFSITE_MAX_AGE_HOURS": "-1"}, "whole number"),
    ({"NUQATI_OFFSITE_PATH": "relative/folder"}, "absolute folder"),
])
def test_wrong_settings_are_named_and_rejected(env, extra, message):
    r = run(OFFSITE, ["check-config"], env, extra)
    assert r.returncode == 1 and message in r.stdout, r.stdout
    make_dump(env)
    r = run(OFFSITE, ["push"], env, extra)
    assert r.returncode == 1 and message in r.stderr
    assert not (env["_remote"]).exists() or remote_names(env) == []


DRIVE = {"NUQATI_OFFSITE": "drive", "NUQATI_OFFSITE_PATH": "nuqati-backups"}
SA = {"NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON": '{"type":"service_account","private_key":"SECRET-KEY"}',
      "NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID": "0ABCshared"}
OAUTH = {"NUQATI_OFFSITE_DRIVE_CLIENT_ID": "id.apps.googleusercontent.com", "NUQATI_OFFSITE_DRIVE_CLIENT_SECRET": "GOCSPX-secret",
         "NUQATI_OFFSITE_DRIVE_TOKEN": '{"access_token":"A","refresh_token":"R"}'}


@pytest.mark.parametrize("extra,message", [
    ({}, "needs credentials"),
    ({**SA, **OAUTH}, "not both"),
    ({"NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON": '{"a":1}'}, "SHARED_DRIVE_ID"),
    ({"NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON": "/path/key.json", "NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID": "x"}, "JSON key file on one line"),
    ({"NUQATI_OFFSITE_DRIVE_TOKEN": '{"a":1}'}, "CLIENT_ID"),
    ({"NUQATI_OFFSITE_DRIVE_CLIENT_ID": "i", "NUQATI_OFFSITE_DRIVE_CLIENT_SECRET": "s", "NUQATI_OFFSITE_DRIVE_TOKEN": "not json"}, "token JSON"),
    ({**SA, "NUQATI_OFFSITE_PATH": "/absolute"}, "no leading slash"),
    ({**SA, "NUQATI_OFFSITE_PATH": "../escape"}, "no leading slash"),
    ({**SA, "NUQATI_OFFSITE_PATH": "my folder"}, "no spaces"),
])
def test_google_drive_settings_are_checked(env, extra, message):
    r = run(OFFSITE, ["check-config"], env, {**DRIVE, **extra})
    assert r.returncode == 1 and message in r.stdout, r.stdout


@pytest.mark.parametrize("creds", [SA, OAUTH])
def test_good_google_drive_settings_pass(env, creds):
    assert run(OFFSITE, ["check-config"], env, {**DRIVE, **creds}).returncode == 0


def test_rclone_receives_the_drive_service_account_and_the_encryption_settings_through_its_environment(env):
    make_dump(env)
    r = run(OFFSITE, ["list"], env, {**DRIVE, **SA})
    assert r.returncode == 0, r.stderr
    seen = (env["_path"] / "rclone.env").read_text()
    for line in ("RCLONE_CONFIG_NQOFFSITE_TYPE=drive", "RCLONE_CONFIG_NQOFFSITE_SCOPE=drive",
                 "RCLONE_CONFIG_NQOFFSITE_TEAM_DRIVE=0ABCshared", "RCLONE_CONFIG_NQCRYPT_TYPE=crypt",
                 "RCLONE_CONFIG_NQCRYPT_REMOTE=nqoffsite:nuqati-backups", "RCLONE_CONFIG_NQCRYPT_FILENAME_ENCRYPTION=off",
                 "RCLONE_CONFIG_NQCRYPT_DIRECTORY_NAME_ENCRYPTION=false", "RCLONE_CONFIG_NQCRYPT_SUFFIX=.bin",
                 f"RCLONE_CONFIG_NQCRYPT_PASSWORD=obscured-{PASS1}", f"RCLONE_CONFIG_NQCRYPT_PASSWORD2=obscured-{PASS2}"):
        assert line in seen.splitlines(), line
    assert 'RCLONE_CONFIG_NQOFFSITE_SERVICE_ACCOUNT_CREDENTIALS={"type":"service_account","private_key":"SECRET-KEY"}' in seen.splitlines()
    assert "NQOFFSITE_TOKEN" not in seen


def test_oauth_uses_the_narrow_drive_file_scope(env):
    r = run(OFFSITE, ["list"], env, {**DRIVE, **OAUTH})
    assert r.returncode == 0, r.stderr
    seen = (env["_path"] / "rclone.env").read_text().splitlines()
    assert "RCLONE_CONFIG_NQOFFSITE_SCOPE=drive.file" in seen
    assert "RCLONE_CONFIG_NQOFFSITE_CLIENT_ID=id.apps.googleusercontent.com" in seen
    assert 'RCLONE_CONFIG_NQOFFSITE_TOKEN={"access_token":"A","refresh_token":"R"}' in seen
    assert not any("SERVICE_ACCOUNT" in line or "TEAM_DRIVE" in line for line in seen)


# ---------------------------------------------------------------- push

def test_push_uploads_the_newest_dump_encrypted_and_records_it(env):
    make_dump(env, stamp(2))
    newest = make_dump(env, stamp(0))
    r = run(OFFSITE, ["push"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert remote_names(env) == [newest.name]
    assert "copyto --ignore-times" in (env["_path"] / "rclone.log").read_text(), "a retry must replace a damaged copy"
    stored = (env["_remote"] / f"{newest.name}.bin").read_text()
    assert stored != newest.read_text() and "PGDMP" not in stored
    ok = (env["_backups"] / "OFFSITE_OK").read_text().split()
    assert ok[1] == newest.name and int(ok[2]) == newest.stat().st_size
    assert "OK " + newest.name in r.stdout and "verified" in r.stdout


def test_push_of_a_named_dump(env):
    old = make_dump(env, stamp(3))
    make_dump(env, stamp(0))
    assert run(OFFSITE, ["push", str(old)], env).returncode == 0
    assert remote_names(env) == [old.name]


def test_a_failed_upload_is_recorded_and_keeps_the_previous_good_record(env):
    make_dump(env, stamp(1))
    assert run(OFFSITE, ["push"], env).returncode == 0
    ok_before = (env["_backups"] / "OFFSITE_OK").read_text()
    make_dump(env, stamp(0))
    r = run(OFFSITE, ["push"], env, {"FAKE_FAIL": "copyto"})
    assert r.returncode == 1 and "upload" in r.stderr and "simulated error" in r.stderr
    assert (env["_backups"] / "OFFSITE_OK").read_text() == ok_before
    assert "upload" in (env["_backups"] / "OFFSITE_FAILED").read_text()
    # the next success clears the failure record
    assert run(OFFSITE, ["push"], env).returncode == 0
    assert not (env["_backups"] / "OFFSITE_FAILED").exists()


@pytest.mark.parametrize("injected", [{"FAKE_CORRUPT": "1"}, {"FAKE_CRYPTCHECK_SILENT": "1"}])
def test_an_upload_that_cannot_be_verified_does_not_count(env, injected):
    make_dump(env)
    r = run(OFFSITE, ["push"], env, injected)
    assert r.returncode == 1 and "could not be verified" in r.stderr
    assert not (env["_backups"] / "OFFSITE_OK").exists()
    assert (env["_backups"] / "OFFSITE_FAILED").exists()


def test_nothing_to_copy_is_a_failure_not_a_silent_success(env):
    r = run(OFFSITE, ["push"], env)
    assert r.returncode == 1 and "no dump to copy" in r.stderr
    (env["_backups"] / "nuqati-20260101T000000Z.dump").write_text("")
    assert run(OFFSITE, ["push"], env).returncode == 1, "an empty dump must not be copied"


def test_only_dumps_made_by_backup_sh_are_pushed(env):
    stray = env["_backups"] / "passwords.txt"
    stray.write_text("secret")
    r = run(OFFSITE, ["push", str(stray)], env)
    assert r.returncode == 1 and "not a dump made by backup.sh" in r.stderr
    assert remote_names(env) == []


def test_no_secret_is_printed_or_put_on_a_command_line(env):
    make_dump(env)
    extra = {**DRIVE, **SA, "NUQATI_OFFSITE": "local", "NUQATI_OFFSITE_PATH": str(env["_remote"])}
    outputs = []
    for args in (["push"], ["status"], ["list"], ["test"], ["check-config"], ["fetch"]):
        r = run(OFFSITE, args, env, extra)
        outputs += [r.stdout, r.stderr]
    everything = "\n".join(outputs) + (env["_path"] / "rclone.log").read_text()
    for secret in (PASS1, PASS2, "SECRET-KEY", f"obscured-{PASS1}"):
        assert secret not in everything, f"{secret!r} leaked into output or an rclone command line"
    for flag in ("-vv", "--dump", "-vvv", "--log-level DEBUG"):
        assert flag not in everything


def test_a_running_copy_blocks_a_second_one_but_a_stale_lock_does_not(env):
    make_dump(env)
    lock = env["_backups"] / ".offsite.lock"
    lock.mkdir()
    r = run(OFFSITE, ["push"], env)
    assert r.returncode == 1 and "another off-server copy is running" in r.stdout
    assert remote_names(env) == []
    old = time.time() - 7 * 3600
    os.utime(lock, (old, old))
    assert run(OFFSITE, ["push"], env).returncode == 0
    assert not lock.exists(), "the lock must be released at the end"


# ---------------------------------------------------------------- pending / status

def test_pending_follows_the_newest_dump(env):
    assert run(OFFSITE, ["pending"], env).returncode == 1, "no dump, nothing pending"
    make_dump(env, stamp(1))
    assert run(OFFSITE, ["pending"], env).returncode == 0
    assert run(OFFSITE, ["push"], env).returncode == 0
    assert run(OFFSITE, ["pending"], env).returncode == 1
    make_dump(env, stamp(0))
    assert run(OFFSITE, ["pending"], env).returncode == 0


def test_status_reports_missing_ok_old_and_failed(env):
    r = run(OFFSITE, ["status"], env)
    assert r.returncode == 1 and "none yet" in r.stdout
    make_dump(env)
    run(OFFSITE, ["push"], env, {"FAKE_FAIL": "copyto"})
    r = run(OFFSITE, ["status"], env)
    assert r.returncode == 1 and "none yet" in r.stdout and "last attempt failed" in r.stdout
    assert run(OFFSITE, ["push"], env).returncode == 0
    r = run(OFFSITE, ["status"], env)
    assert r.returncode == 0 and r.stdout.startswith("ok: last off-server copy 0 hours ago")
    ok = env["_backups"] / "OFFSITE_OK"
    old = time.time() - 60 * 3600
    os.utime(ok, (old, old))
    r = run(OFFSITE, ["status"], env)
    assert r.returncode == 1 and "60 hours old (limit 50)" in r.stdout
    assert run(OFFSITE, ["status"], env, {"NUQATI_OFFSITE_MAX_AGE_HOURS": "100"}).returncode == 0


def test_status_with_invalid_settings_is_unhealthy_and_says_why(env):
    r = run(OFFSITE, ["status"], env, {"NUQATI_OFFSITE_PASSWORD": "short"})
    assert r.returncode == 1 and "invalid settings" in r.stdout and "16 characters" in r.stdout


# ---------------------------------------------------------------- pruning at the destination

def test_old_copies_are_deleted_but_the_newest_few_and_recent_ones_stay(env):
    seeded = seed_remote(env, [2, 5, 10, 31, 40, 60])
    make_dump(env, stamp(0))
    assert run(OFFSITE, ["push"], env).returncode == 0
    left = remote_names(env)
    assert seeded[0] in left and seeded[1] in left and seeded[2] in left, "copies from the last 30 days stay"
    assert seeded[3] not in left and seeded[4] not in left and seeded[5] not in left
    assert len(left) == 4  # the new copy and three recent ones


def test_the_newest_copies_are_kept_even_when_all_are_old(env):
    seeded = seed_remote(env, [40, 50, 60, 70, 80])
    run(OFFSITE, ["push", str(make_dump(env, stamp(45)))], env)
    left = remote_names(env)
    # the push added a 45-day-old name; the newest three of the six are kept whatever their age
    assert len(left) == 3
    assert seeded[0] in left


def test_pruning_only_touches_names_that_backup_sh_creates(env):
    seed_remote(env, [60])
    (env["_remote"] / "holiday-photos.bin").write_text("x")
    (env["_remote"] / "20200101T000000Z-other-file.bin").write_text("x")   # looks like a stamp but is not a dump
    (env["_remote"] / "nuqati-selftest-20200101T000000Z.txt.bin").write_text("x")
    make_dump(env)
    assert run(OFFSITE, ["push"], env).returncode == 0
    assert "holiday-photos" in remote_names(env)
    assert "20200101T000000Z-other-file" in remote_names(env)
    assert "nuqati-selftest-20200101T000000Z.txt" in remote_names(env)


def test_an_unreadable_listing_deletes_nothing_and_the_push_still_counts(env):
    seeded = seed_remote(env, [90, 100, 110])
    make_dump(env)
    r = run(OFFSITE, ["push"], env, {"FAKE_FAIL": "lsf"})
    assert r.returncode == 0 and "nothing was pruned" in r.stdout
    assert set(seeded) <= set(remote_names(env))


def test_a_failed_delete_is_a_warning_not_a_failure(env):
    seed_remote(env, [50, 60, 70, 80])
    make_dump(env)
    r = run(OFFSITE, ["push"], env, {"FAKE_FAIL": "delete"})
    assert r.returncode == 0 and "WARNING could not remove" in r.stdout


# ---------------------------------------------------------------- fetch (restore side)

def test_fetch_latest_downloads_and_decrypts_into_a_private_folder(env):
    make_dump(env, stamp(1))
    newest = make_dump(env, stamp(0), content="NEWEST-")
    assert run(OFFSITE, ["push", str(newest)], env).returncode == 0
    dest = env["_path"] / "restore"
    r = run(OFFSITE, ["fetch", "latest", str(dest)], env)
    assert r.returncode == 0, r.stderr
    path = Path(r.stdout.strip().splitlines()[-1])
    assert path == dest / newest.name
    assert path.read_text() == newest.read_text(), "decrypted content must equal the original"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert [p.name for p in dest.iterdir()] == [newest.name], "no partial file may remain"


def test_fetch_a_named_copy_and_a_default_temporary_folder(env):
    old = make_dump(env, stamp(2), content="OLD-")
    run(OFFSITE, ["push", str(old)], env)
    run(OFFSITE, ["push", str(make_dump(env, stamp(0)))], env)
    r = run(OFFSITE, ["fetch", old.name], env)
    assert r.returncode == 0, r.stderr
    path = Path(r.stdout.strip())
    assert path.read_text() == old.read_text()
    assert path.parent.parent == env["_tmp"] and stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_fetch_with_the_wrong_passphrases_fails_and_leaves_nothing(env):
    make_dump(env)
    assert run(OFFSITE, ["push"], env).returncode == 0
    dest = env["_path"] / "restore"
    r = run(OFFSITE, ["fetch", "latest", str(dest)], env, {"NUQATI_OFFSITE_PASSWORD": "another-passphrase-000000", "FAKE_PARTIAL": "1"})
    assert r.returncode == 1 and "wrong passphrases" in r.stderr
    assert list(dest.iterdir()) == [], "a partial download must be removed"


def test_fetch_rejects_bad_names_and_an_empty_destination(env):
    assert run(OFFSITE, ["fetch", "latest", str(env["_path"] / "d")], env).returncode == 1
    r = run(OFFSITE, ["fetch", "../../etc/passwd", str(env["_path"] / "d2")], env)
    assert r.returncode == 1 and "not a backup name" in r.stderr


def test_a_download_that_is_not_a_readable_dump_is_rejected(env):
    make_dump(env)
    run(OFFSITE, ["push"], env)
    dest = env["_path"] / "restore"
    r = run(OFFSITE, ["fetch", "latest", str(dest)], env, {"FAKE_LIST_FAIL": "1"})
    assert r.returncode == 1 and "not a readable dump" in r.stderr
    assert list(dest.iterdir()) == []


def test_list_shows_size_and_name(env):
    d = make_dump(env)
    run(OFFSITE, ["push"], env)
    r = run(OFFSITE, ["list"], env)
    assert r.returncode == 0 and r.stdout.split() == [str(d.stat().st_size), d.name]


# ---------------------------------------------------------------- self test

def test_self_test_passes_and_cleans_up(env):
    r = run(OFFSITE, ["test"], env)
    assert r.returncode == 0 and "TEST OK" in r.stdout, r.stdout + r.stderr
    assert remote_names(env) == []
    assert list(env["_tmp"].iterdir()) == []


def test_self_test_detects_an_unencrypted_destination_and_removes_the_file(env):
    r = run(OFFSITE, ["test"], env, {"FAKE_NO_ENCRYPT": "1"})
    assert r.returncode == 1 and "UNENCRYPTED" in r.stderr
    assert remote_names(env) == []


def test_self_test_reports_a_failed_upload(env):
    r = run(OFFSITE, ["test"], env, {"FAKE_FAIL": "copyto"})
    assert r.returncode == 1 and "TEST FAILED: upload" in r.stderr


# ---------------------------------------------------------------- backup.sh and restore_drill.sh use it

def test_backup_once_copies_the_dump_off_the_server_when_it_is_on(env):
    r = run(BACKUP, ["once"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    dump = next(env["_backups"].glob("nuqati-*.dump"))
    assert remote_names(env) == [dump.name]


def test_backup_once_never_touches_rclone_when_it_is_off(env):
    r = run(BACKUP, ["once"], env, drop=("NUQATI_OFFSITE",))
    assert r.returncode == 0
    assert (env["_path"] / "rclone.log").read_text() == ""
    assert run(BACKUP, ["once"], env, {"NUQATI_OFFSITE": ""}).returncode == 0


def test_a_failing_off_server_copy_does_not_lose_the_local_backup(env):
    r = run(BACKUP, ["once"], env, {"FAKE_FAIL": "copyto"})
    assert r.returncode == 3, "3 = backup good, off-server copy failed"
    assert len(list(env["_backups"].glob("nuqati-*.dump"))) == 1
    assert (env["_backups"] / "LAST_OK").exists()
    assert (env["_backups"] / "OFFSITE_FAILED").exists()
    assert run(BACKUP, ["once"], env, {"FAKE_PG_DUMP_FAIL": "1"}).returncode == 1


def test_a_failed_local_backup_does_not_start_an_off_server_copy(env):
    r = run(BACKUP, ["once"], env, {"FAKE_PG_DUMP_FAIL": "1"})
    assert r.returncode == 1
    assert (env["_path"] / "rclone.log").read_text() == ""


def test_health_includes_the_off_server_copy_only_when_it_is_on(env):
    assert run(BACKUP, ["once"], env, {"FAKE_FAIL": "copyto"}).returncode == 3
    r = run(BACKUP, ["health"], env)
    assert r.returncode == 1 and "off-server copy: none yet" in r.stdout and "ok: last successful backup" in r.stdout
    assert run(BACKUP, ["health"], env, drop=("NUQATI_OFFSITE",)).returncode == 0, "off = the old behaviour"
    assert run(OFFSITE, ["push"], env).returncode == 0
    r = run(BACKUP, ["health"], env)
    assert r.returncode == 0 and "ok: last off-server copy" in r.stdout


def test_health_is_red_when_the_off_server_settings_are_wrong_but_local_backups_continue(env):
    r = run(BACKUP, ["once"], env, {"NUQATI_OFFSITE_PASSWORD": "short"})
    assert r.returncode == 3 and len(list(env["_backups"].glob("nuqati-*.dump"))) == 1
    h = run(BACKUP, ["health"], env, {"NUQATI_OFFSITE_PASSWORD": "short"})
    assert h.returncode == 1 and "invalid settings" in h.stdout


def test_a_pending_copy_is_retried_only_when_the_retry_interval_has_passed(env):
    assert run(BACKUP, ["once"], env, {"FAKE_FAIL": "copyto"}).returncode == 3
    log = env["_path"] / "rclone.log"
    calls = lambda: log.read_text().count("copyto")  # noqa: E731
    before = calls()
    run(BACKUP, ["offsite-retry"], env)               # tried a moment ago: too early
    assert calls() == before
    attempt = env["_backups"] / "OFFSITE_LAST_ATTEMPT"
    old = time.time() - 2 * 3600
    os.utime(attempt, (old, old))
    r = run(BACKUP, ["offsite-retry"], env)           # the destination works again
    assert r.returncode == 0 and calls() > before
    assert (env["_backups"] / "OFFSITE_OK").exists() and not (env["_backups"] / "OFFSITE_FAILED").exists()
    after = calls()
    os.utime(attempt, (old, old))
    run(BACKUP, ["offsite-retry"], env)               # nothing pending any more
    assert calls() == after


def test_offsite_retry_does_nothing_when_it_is_off(env):
    make_dump(env)
    assert run(BACKUP, ["offsite-retry"], env, drop=("NUQATI_OFFSITE",)).returncode == 0
    assert (env["_path"] / "rclone.log").read_text() == ""


def test_restore_drill_from_the_off_server_copy(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    shutil_dump = next(env["_backups"].glob("nuqati-*.dump"))
    shutil_dump.unlink()   # the local copy is gone (a lost server): only the off-server copy remains
    r = run(DRILL, ["--offsite"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: OK" in r.stdout and "source=off-server" in r.stdout
    assert "the downloaded copy was deleted" in r.stdout
    assert list(env["_tmp"].iterdir()) == [], "the downloaded dump holds personal data and must be gone"
    assert "restore" in (env["_path"] / "fake.log").read_text()


def test_restore_drill_from_the_off_server_copy_fails_cleanly(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    r = run(DRILL, ["--offsite"], env, {"NUQATI_OFFSITE_PASSWORD": "another-passphrase-000000"})
    assert r.returncode == 1 and "RESULT: FAILED - cannot fetch the off-server copy" in r.stdout
    assert list(env["_tmp"].iterdir()) == []


def test_restore_drill_without_the_flag_is_unchanged(env):
    assert run(BACKUP, ["once"], env).returncode == 0
    r = run(DRILL, [], env)
    assert r.returncode == 0 and "source=off-server" not in r.stdout


# ---------------------------------------------------------------- static checks

def test_the_scripts_are_posix_sh_without_bashisms():
    for script in (OFFSITE, BACKUP, DRILL):
        assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0
        text = script.read_text()
        assert text.startswith("#!/bin/sh")
        for bashism in ("[[", "]]", "<(", "echo -e", "${!", "pipefail"):
            assert bashism not in text, f"{script.name} uses {bashism!r}"
        for line in text.splitlines():
            code = line.split("#")[0]
            assert not re.search(r"(^|;|\{|\()\s*(local|declare|function)\s+[A-Za-z_]", code), f"{script.name}: {line.strip()}"


def test_secrets_are_only_read_in_the_two_places_that_need_them():
    text = OFFSITE.read_text()
    uses = [line.strip() for line in text.splitlines() if re.search(r"\$\{?PASS[12]\b|\$\{#PASS[12]\}", line) and not line.strip().startswith("#")]
    allowed = ("[ \"${#PASS1}\" -lt 16 ]", "[ \"$PASS1\" = \"$PASS2\" ]", "_o1=$(printf '%s\\n' \"$PASS1\" | rclone obscure -)")
    for line in uses:
        assert any(a in line for a in allowed), f"unexpected use of a passphrase: {line}"
    assert "-vv" not in text and "--dump" not in text and "log-level DEBUG" not in text
    for line in text.splitlines():
        code = line.split("#")[0]
        if re.search(r"NUQATI_OFFSITE_(PASSWORD|DRIVE_TOKEN|DRIVE_CLIENT_SECRET|DRIVE_SERVICE_ACCOUNT_JSON)|\$_?(sa|tok)\b|\$PASS", code):
            assert not re.search(r"\b(echo|log|elog|printf)\b.*(NUQATI_OFFSITE_(PASSWORD|DRIVE_TOKEN|DRIVE_CLIENT_SECRET|DRIVE_SERVICE_ACCOUNT_JSON)|\$_?(sa|tok)\b|\$PASS)", code) \
                or "rclone obscure" in code, f"a secret may be printed: {line.strip()}"


def test_compose_env_example_docs_and_image_cover_every_setting():
    text = OFFSITE.read_text()
    names = sorted(set(re.findall(r"\bNUQATI_OFFSITE[A-Z0-9_]*", text)) - {"NUQATI_OFFSITE_RCLONE_CONFIG", "NUQATI_OFFSITE_SCRIPT"})
    assert len(names) >= 12
    compose = (ROOT / "compose.yml").read_text()
    example = (ROOT / ".env.example").read_text()
    guide = (ROOT / "docs" / "compliance" / "BACKUP_RESTORE.md").read_text()
    for name in names:
        assert f"{name}: ${{{name}:-}}" in compose, f"{name} must be passed to db_backup by compose.yml (empty = default)"
        assert name in example, f"{name} missing from .env.example"
        assert name in guide, f"{name} missing from docs/compliance/BACKUP_RESTORE.md"
    dockerfile = (ROOT / "ops" / "backup" / "Dockerfile").read_text()
    assert "apk add --no-cache rclone" in dockerfile and "offsite.sh" in dockerfile
    assert "0755" in dockerfile and "/usr/local/bin/offsite.sh" in dockerfile
