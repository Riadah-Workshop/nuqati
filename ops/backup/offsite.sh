#!/bin/sh
# Nuqati off-server backup copy. POSIX sh: it runs on Alpine (busybox), so no bash-only features.
#
# Copies each database dump to storage on another provider (Google Drive, or a folder for tests / a second disk),
# ENCRYPTED on this server first, so the destination only ever holds data it cannot read. Uses rclone with its
# "crypt" layer (NaCl secretbox: XSalsa20 + Poly1305, key derived from two passphrases with scrypt).
#
#   offsite.sh push [dump]            encrypt + upload the newest dump (or the named one), verify it, prune old copies
#   offsite.sh pending                exit 0 if the newest dump on this server has not been copied yet
#   offsite.sh status                 one line; exit 1 when the copy is configured but missing, failing or too old
#   offsite.sh list                   the copies in the destination (size, name)
#   offsite.sh fetch [name|latest] [dir]   download + decrypt a copy into dir (default: a new private temp directory);
#                                     prints the path of the dump on its last line
#   offsite.sh test                   upload a small test file, read it back, check it is unreadable at the destination,
#                                     delete it: proves the credentials and the passphrases
#   offsite.sh check-config           print what is wrong with the settings (exit 1) or say they are fine
#
# It is off unless NUQATI_OFFSITE is `drive` or `local`. Settings are environment variables (see .env.example):
#   NUQATI_OFFSITE=drive|local   NUQATI_OFFSITE_PATH   NUQATI_OFFSITE_PASSWORD   NUQATI_OFFSITE_PASSWORD2
#   NUQATI_OFFSITE_KEEP_DAYS (30)  NUQATI_OFFSITE_MIN_KEEP (3)  NUQATI_OFFSITE_MAX_AGE_HOURS (50)
#   Google Drive, one of two ways:
#     a service account on a Shared Drive: NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON, NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID
#     your own OAuth client:               NUQATI_OFFSITE_DRIVE_CLIENT_ID, _CLIENT_SECRET, _TOKEN
#
# Secrets are never printed and never put on a command line; rclone is never run with debug logging (it shows credentials).
set -u

DIR="${BACKUP_DIR:-/backups}"
MODE="${NUQATI_OFFSITE:-}"
DEST_PATH="${NUQATI_OFFSITE_PATH:-nuqati-backups}"
KEEP_DAYS="${NUQATI_OFFSITE_KEEP_DAYS:-30}"      # copies older than this are deleted at the destination ...
MIN_KEEP="${NUQATI_OFFSITE_MIN_KEEP:-3}"         # ... but the newest N are always kept
MAX_AGE_H="${NUQATI_OFFSITE_MAX_AGE_HOURS:-50}"  # status fails when the last good copy is older
PASS1="${NUQATI_OFFSITE_PASSWORD:-}"
PASS2="${NUQATI_OFFSITE_PASSWORD2:-}"
LOCK="$DIR/.offsite.lock"
RC_FLAGS="--log-level ERROR --retries 3 --low-level-retries 5 --contimeout 1m --timeout 10m --drive-chunk-size 64M"

log() { printf '%s offsite: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
elog() { log "$@" >&2; }

is_number() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

hours_since() { # age of a file in whole hours
  _now=$(date +%s)
  _mtime=$(stat -c %Y "$1" 2>/dev/null || echo 0)
  echo $(( (_now - _mtime) / 3600 ))
}

newest_dump() { ls -1t "$DIR"/nuqati-*.dump 2>/dev/null | head -n 1; }

# ---------------------------------------------------------------------------------------------------- settings

CONFIG_ERROR=""

# Pure shell checks, no rclone needed (the container healthcheck uses this every 10 minutes).
# Returns 0 = usable, 1 = configured but wrong (CONFIG_ERROR says why), 2 = switched off.
validate() {
  CONFIG_ERROR=""
  case "$MODE" in
    ''|off) return 2 ;;
    drive|local) ;;
    *) CONFIG_ERROR="NUQATI_OFFSITE must be empty, drive or local (got '$MODE')"; return 1 ;;
  esac
  for _pair in "NUQATI_OFFSITE_KEEP_DAYS=$KEEP_DAYS" "NUQATI_OFFSITE_MIN_KEEP=$MIN_KEEP" "NUQATI_OFFSITE_MAX_AGE_HOURS=$MAX_AGE_H"; do
    if ! is_number "${_pair#*=}"; then CONFIG_ERROR="${_pair%%=*} must be a whole number (got '${_pair#*=}')"; return 1; fi
  done
  if [ "$KEEP_DAYS" -lt 1 ] || [ "$MIN_KEEP" -lt 1 ] || [ "$MAX_AGE_H" -lt 1 ]; then
    CONFIG_ERROR="NUQATI_OFFSITE_KEEP_DAYS, _MIN_KEEP and _MAX_AGE_HOURS must be at least 1"; return 1
  fi
  if [ "${#PASS1}" -lt 16 ] || [ "${#PASS2}" -lt 16 ]; then
    CONFIG_ERROR="NUQATI_OFFSITE_PASSWORD and NUQATI_OFFSITE_PASSWORD2 must both be set, at least 16 characters each (the encryption key)"; return 1
  fi
  if [ "$PASS1" = "$PASS2" ]; then
    CONFIG_ERROR="NUQATI_OFFSITE_PASSWORD and NUQATI_OFFSITE_PASSWORD2 must differ"; return 1
  fi
  case "$MODE" in
    local)
      case "$DEST_PATH" in /*) ;; *) CONFIG_ERROR="NUQATI_OFFSITE_PATH must be an absolute folder when NUQATI_OFFSITE=local"; return 1 ;; esac ;;
    drive)
      case "$DEST_PATH" in
        /*|*..*|*[!A-Za-z0-9._/-]*|'') CONFIG_ERROR="NUQATI_OFFSITE_PATH must be a folder name like nuqati-backups (letters, digits, . _ - and /; no spaces, no leading slash)"; return 1 ;;
      esac
      _sa="${NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON:-}"
      _tok="${NUQATI_OFFSITE_DRIVE_TOKEN:-}"
      if [ -n "$_sa" ] && [ -n "$_tok" ]; then
        CONFIG_ERROR="set either the Drive service account or the OAuth token, not both"; return 1
      fi
      if [ -z "$_sa" ] && [ -z "$_tok" ]; then
        CONFIG_ERROR="Google Drive needs credentials: NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON (+ _SHARED_DRIVE_ID), or _CLIENT_ID + _CLIENT_SECRET + _TOKEN"; return 1
      fi
      if [ -n "$_sa" ]; then
        case "$_sa" in '{'*'}') ;; *) CONFIG_ERROR="NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON must be the JSON key file on one line"; return 1 ;; esac
        if [ -z "${NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID:-}" ]; then
          CONFIG_ERROR="a service account has no storage of its own: set NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID (a Shared Drive it is a member of)"; return 1
        fi
      else
        case "$_tok" in '{'*'}') ;; *) CONFIG_ERROR="NUQATI_OFFSITE_DRIVE_TOKEN must be the token JSON from rclone"; return 1 ;; esac
        if [ -z "${NUQATI_OFFSITE_DRIVE_CLIENT_ID:-}" ] || [ -z "${NUQATI_OFFSITE_DRIVE_CLIENT_SECRET:-}" ]; then
          CONFIG_ERROR="NUQATI_OFFSITE_DRIVE_CLIENT_ID and _CLIENT_SECRET are required with a token (create your own Google OAuth client)"; return 1
        fi
      fi ;;
  esac
  return 0
}

# validate + hand the settings to rclone through its environment (no config file, no secrets on a command line).
configure() {
  validate; _rc=$?
  [ "$_rc" -eq 0 ] || return "$_rc"
  if ! command -v rclone >/dev/null 2>&1; then CONFIG_ERROR="rclone is not installed in this image"; return 1; fi
  _o1=$(printf '%s\n' "$PASS1" | rclone obscure -) && _o2=$(printf '%s\n' "$PASS2" | rclone obscure -) \
    || { CONFIG_ERROR="rclone could not prepare the encryption key"; return 1; }
  export RCLONE_CONFIG="${NUQATI_OFFSITE_RCLONE_CONFIG:-/tmp/nuqati-rclone.conf}"
  case "$MODE" in
    local)
      export RCLONE_CONFIG_NQOFFSITE_TYPE=local ;;
    drive)
      export RCLONE_CONFIG_NQOFFSITE_TYPE=drive
      if [ -n "${NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON:-}" ]; then
        export RCLONE_CONFIG_NQOFFSITE_SCOPE=drive
        export RCLONE_CONFIG_NQOFFSITE_SERVICE_ACCOUNT_CREDENTIALS="$NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON"
        export RCLONE_CONFIG_NQOFFSITE_TEAM_DRIVE="$NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID"
      else
        # drive.file: this key can only see files it created itself, never the rest of the Drive
        export RCLONE_CONFIG_NQOFFSITE_SCOPE=drive.file
        export RCLONE_CONFIG_NQOFFSITE_CLIENT_ID="$NUQATI_OFFSITE_DRIVE_CLIENT_ID"
        export RCLONE_CONFIG_NQOFFSITE_CLIENT_SECRET="$NUQATI_OFFSITE_DRIVE_CLIENT_SECRET"
        export RCLONE_CONFIG_NQOFFSITE_TOKEN="$NUQATI_OFFSITE_DRIVE_TOKEN"
      fi ;;
  esac
  export RCLONE_CONFIG_NQCRYPT_TYPE=crypt
  export RCLONE_CONFIG_NQCRYPT_REMOTE="nqoffsite:$DEST_PATH"
  export RCLONE_CONFIG_NQCRYPT_PASSWORD="$_o1"
  export RCLONE_CONFIG_NQCRYPT_PASSWORD2="$_o2"
  # File names stay readable (they are only a timestamp) so the folder can be managed by hand; contents are encrypted.
  export RCLONE_CONFIG_NQCRYPT_FILENAME_ENCRYPTION=off
  export RCLONE_CONFIG_NQCRYPT_DIRECTORY_NAME_ENCRYPTION=false
  export RCLONE_CONFIG_NQCRYPT_SUFFIX=.bin
  return 0
}

need_config() { # for commands that talk to the destination
  configure; _rc=$?
  case "$_rc" in
    0) return 0 ;;
    2) elog "the off-server copy is switched off (NUQATI_OFFSITE is empty)"; exit 2 ;;
    *) elog "ERROR $CONFIG_ERROR"; exit 1 ;;
  esac
}

rc() { rclone "$@" $RC_FLAGS; }

last_line() { printf '%s\n' "$1" | grep -v '^$' | tail -n 1 | cut -c1-300; }

# ---------------------------------------------------------------------------------------------------- state files

record_failure() {
  printf '%s %s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$1" > "$DIR/.offsite_failed.tmp" && mv "$DIR/.offsite_failed.tmp" "$DIR/OFFSITE_FAILED"
  elog "ERROR $1"
}

take_lock() {
  if mkdir "$LOCK" 2>/dev/null; then trap 'rmdir "$LOCK" 2>/dev/null' EXIT; return 0; fi
  # a lock left behind by a crashed run goes stale after 6 hours
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null && { trap 'rmdir "$LOCK" 2>/dev/null' EXIT; return 0; }
  fi
  return 1
}

# ---------------------------------------------------------------------------------------------------- commands

prune_remote() {
  _listing=$(rc lsf --files-only nqcrypt: 2>/dev/null) || { log "WARNING cannot list the destination, nothing was pruned"; return 0; }
  _names=$(printf '%s\n' "$_listing" | grep -E '^nuqati-[0-9]{8}T[0-9]{6}Z\.dump$' | sort -r)
  [ -n "$_names" ] || return 0   # an empty or unreadable listing never deletes anything
  _cutoff=$(date -u -d "@$(( $(date +%s) - KEEP_DAYS * 86400 ))" +%Y%m%dT%H%M%SZ 2>/dev/null) \
    || { log "WARNING cannot compute the cut-off date, nothing was pruned"; return 0; }
  _n=0
  for _f in $_names; do
    _n=$((_n + 1))
    [ "$_n" -le "$MIN_KEEP" ] && continue
    _stamp=${_f#nuqati-}; _stamp=${_stamp%.dump}
    [ "$_stamp" = "$_cutoff" ] && continue
    if [ "$(printf '%s\n%s\n' "$_stamp" "$_cutoff" | sort | head -n 1)" = "$_stamp" ]; then
      if rc deletefile "nqcrypt:$_f" >/dev/null 2>&1; then log "removed old off-server copy $_f"; else log "WARNING could not remove $_f"; fi
    fi
  done
  return 0
}

push() {
  need_config
  _dump="${1:-}"
  [ -n "$_dump" ] || _dump=$(newest_dump)
  if [ -z "$_dump" ] || [ ! -s "$_dump" ]; then record_failure "there is no dump to copy in $DIR"; return 1; fi
  _name=$(basename "$_dump")
  case "$_name" in
    nuqati-[0-9]*T[0-9]*Z.dump) ;;
    *) record_failure "$_name is not a dump made by backup.sh"; return 1 ;;
  esac
  mkdir -p "$DIR" 2>/dev/null
  if ! take_lock; then log "another off-server copy is running, skipping"; return 1; fi
  touch "$DIR/OFFSITE_LAST_ATTEMPT" 2>/dev/null
  _start=$(date +%s)
  _size=$(stat -c %s "$_dump" 2>/dev/null || echo 0)
  # --ignore-times: a retry must upload again even if size and time look equal (a damaged copy has to be replaced)
  if ! _out=$(rc copyto --ignore-times "$_dump" "nqcrypt:$_name" 2>&1); then
    record_failure "the upload of $_name failed: $(last_line "$_out")"; return 1
  fi
  # Read the checksum the destination holds for the encrypted file and compare it with this file encrypted the same way.
  _report=$(rc cryptcheck --one-way --include "/$_name" --combined - "$(dirname "$_dump")" nqcrypt: 2>/dev/null)
  if ! printf '%s\n' "$_report" | grep -qx "= $_name"; then
    record_failure "the copy of $_name was uploaded but could not be verified at the destination"; return 1
  fi
  _secs=$(( $(date +%s) - _start ))
  printf '%s %s %s %s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$_name" "$_size" "$_secs" > "$DIR/.offsite_ok.tmp" && mv "$DIR/.offsite_ok.tmp" "$DIR/OFFSITE_OK"
  rm -f "$DIR/OFFSITE_FAILED"
  log "OK $_name ${_size} bytes encrypted and verified at the destination in ${_secs}s"
  prune_remote
  return 0
}

pending() {
  _newest=$(newest_dump)
  [ -n "$_newest" ] || return 1
  _last=$(cut -d' ' -f2 "$DIR/OFFSITE_OK" 2>/dev/null)
  [ "$(basename "$_newest")" != "$_last" ]
}

status() {
  validate; _rc=$?
  case "$_rc" in
    2) echo "off-server copy: not configured"; return 0 ;;
    1) echo "off-server copy: invalid settings: $CONFIG_ERROR"; return 1 ;;
  esac
  if [ ! -f "$DIR/OFFSITE_OK" ]; then
    echo "off-server copy: none yet$( [ -f "$DIR/OFFSITE_FAILED" ] && printf ' (last attempt failed: %s)' "$(cut -d' ' -f2- "$DIR/OFFSITE_FAILED")" )"
    return 1
  fi
  _age=$(hours_since "$DIR/OFFSITE_OK")
  if [ "$_age" -ge "$MAX_AGE_H" ]; then
    echo "off-server copy: the last good copy is ${_age} hours old (limit ${MAX_AGE_H})$( [ -f "$DIR/OFFSITE_FAILED" ] && printf ' (last attempt failed: %s)' "$(cut -d' ' -f2- "$DIR/OFFSITE_FAILED")" )"
    return 1
  fi
  echo "ok: last off-server copy ${_age} hours ago ($(cut -d' ' -f2 "$DIR/OFFSITE_OK"))"
}

list_copies() {
  need_config
  rc lsf --files-only --format sp --separator ' ' nqcrypt: || { elog "ERROR cannot list the destination"; return 1; }
}

fetch() {
  need_config
  _want="${1:-latest}"
  _dest="${2:-}"
  if [ -z "$_dest" ]; then
    _dest=$(mktemp -d "${TMPDIR:-/tmp}/nuqati-offsite.XXXXXX") || { elog "ERROR cannot create a temporary directory"; return 1; }
  fi
  mkdir -p "$_dest" && chmod 700 "$_dest" || { elog "ERROR cannot use $_dest"; return 1; }
  if [ "$_want" = "latest" ]; then
    _all=$(rc lsf --files-only nqcrypt: 2>/dev/null) || { elog "ERROR cannot list the destination"; return 1; }
    _want=$(printf '%s\n' "$_all" | grep -E '^nuqati-[0-9]{8}T[0-9]{6}Z\.dump$' | sort -r | head -n 1)
    [ -n "$_want" ] || { elog "ERROR the destination holds no backup"; return 1; }
  fi
  case "$_want" in
    nuqati-[0-9]*T[0-9]*Z.dump) ;;
    *) elog "ERROR '$_want' is not a backup name (nuqati-<date>T<time>Z.dump)"; return 1 ;;
  esac
  if ! _out=$(rc copyto "nqcrypt:$_want" "$_dest/.$_want.part" 2>&1); then
    rm -f "$_dest/.$_want.part"
    elog "ERROR download or decryption of $_want failed (wrong passphrases?): $(last_line "$_out")"
    return 1
  fi
  if command -v pg_restore >/dev/null 2>&1 && ! pg_restore --list "$_dest/.$_want.part" >/dev/null 2>&1; then
    rm -f "$_dest/.$_want.part"
    elog "ERROR $_want was downloaded but is not a readable dump (wrong passphrases, or a damaged copy)"
    return 1
  fi
  mv "$_dest/.$_want.part" "$_dest/$_want" || return 1
  elog "OK downloaded and decrypted $_want ($(stat -c %s "$_dest/$_want") bytes)"
  printf '%s\n' "$_dest/$_want"
}

self_test() {
  need_config
  _tmp=$(mktemp -d "${TMPDIR:-/tmp}/nuqati-offsite-test.XXXXXX") || return 1
  _stamp=$(date -u +%Y%m%dT%H%M%SZ)
  _file="nuqati-selftest-$_stamp.txt"
  trap 'rm -rf "$_tmp"; rmdir "$LOCK" 2>/dev/null' EXIT
  { printf 'NUQATI-OFFSITE-SELFTEST-MARKER\n'; head -c 50000 /dev/urandom; } > "$_tmp/$_file"
  if ! _out=$(rc copyto "$_tmp/$_file" "nqcrypt:$_file" 2>&1); then
    elog "TEST FAILED: upload: $(last_line "$_out")"; return 1
  fi
  _cleanup() { rc deletefile "nqcrypt:$_file" >/dev/null 2>&1; }
  if ! rc copyto "nqcrypt:$_file" "$_tmp/back.txt" >/dev/null 2>&1 || ! cmp -s "$_tmp/$_file" "$_tmp/back.txt"; then
    _cleanup; elog "TEST FAILED: the file came back different or could not be decrypted"; return 1
  fi
  # what the destination really holds must not contain the plain text
  if rc cat "nqoffsite:$DEST_PATH/$_file.bin" 2>/dev/null | grep -aq 'NUQATI-OFFSITE-SELFTEST-MARKER'; then
    _cleanup; elog "TEST FAILED: the destination holds the file UNENCRYPTED"; return 1
  fi
  _cleanup
  log "TEST OK: uploaded, read back identical, unreadable at the destination, deleted"
}

case "${1:-}" in
  push)         shift; push "$@"; exit $? ;;
  pending)      pending; exit $? ;;
  status)       status; exit $? ;;
  list)         list_copies; exit $? ;;
  fetch)        shift; fetch "$@"; exit $? ;;
  test)         self_test; exit $? ;;
  check-config) validate; _r=$?
                case "$_r" in 0) echo "the off-server copy settings look fine" ;; 2) echo "the off-server copy is switched off" ;; *) echo "$CONFIG_ERROR" ;; esac
                [ "$_r" -ne 1 ]; exit $? ;;
  *)            echo "usage: offsite.sh push [dump] | pending | status | list | fetch [name|latest] [dir] | test | check-config" >&2; exit 2 ;;
esac
