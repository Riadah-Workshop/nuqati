#!/bin/sh
# Nuqati scheduled PostgreSQL backup. POSIX sh: it runs on Alpine (busybox), so no bash-only features.
#
#   backup.sh loop    run forever: one backup at start if none is recent, then one per day (default)
#   backup.sh once    take one backup now and exit (0 = ok, 1 = failed)
#   backup.sh health  exit 0 only if the last successful backup is recent (used by the container healthcheck)
#
# Connection settings come from the standard libpq variables (PGHOST, PGUSER, PGPASSWORD, PGDATABASE).
# A dump only counts as successful after `pg_restore --list` has read it back. It is written under a
# temporary name and renamed at the end, so a half-written file is never mistaken for a backup.
set -u

DIR="${BACKUP_DIR:-/backups}"
HOUR="${NUQATI_BACKUP_HOUR_UTC:-23}"          # 23:00 UTC = 02:00 in Riyadh
KEEP_DAYS="${NUQATI_BACKUP_KEEP_DAYS:-14}"    # dumps older than this are deleted ...
MIN_KEEP="${NUQATI_BACKUP_MIN_KEEP:-3}"       # ... but the newest N are always kept
MAX_AGE_H="${NUQATI_BACKUP_MAX_AGE_HOURS:-26}" # health fails when the last good backup is older
RETRY_SECONDS="${NUQATI_BACKUP_RETRY_SECONDS:-3600}"

log() { printf '%s backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

is_number() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

for pair in "NUQATI_BACKUP_HOUR_UTC=$HOUR" "NUQATI_BACKUP_KEEP_DAYS=$KEEP_DAYS" "NUQATI_BACKUP_MIN_KEEP=$MIN_KEEP" \
            "NUQATI_BACKUP_MAX_AGE_HOURS=$MAX_AGE_H" "NUQATI_BACKUP_RETRY_SECONDS=$RETRY_SECONDS"; do
  if ! is_number "${pair#*=}"; then
    log "ERROR ${pair%%=*} must be a whole number, got '${pair#*=}'"
    exit 2
  fi
done
if [ "$HOUR" -gt 23 ] || [ "$KEEP_DAYS" -lt 1 ] || [ "$MIN_KEEP" -lt 1 ]; then
  log "ERROR NUQATI_BACKUP_HOUR_UTC must be 0-23, NUQATI_BACKUP_KEEP_DAYS and NUQATI_BACKUP_MIN_KEEP at least 1"
  exit 2
fi

fail() { log "ERROR $*"; return 1; }

# Sleep that reacts to `docker stop` at once (a plain foreground sleep would delay the signal handler).
nap() { sleep "$1" & wait $!; }

hours_since() { # age of a file in whole hours
  _now=$(date +%s)
  _mtime=$(stat -c %Y "$1" 2>/dev/null || echo 0)
  echo $(( (_now - _mtime) / 3600 ))
}

fresh_enough() { # last good backup younger than $1 hours?
  [ -f "$DIR/LAST_OK" ] && [ "$(hours_since "$DIR/LAST_OK")" -lt "$1" ]
}

prune() {
  _n=0
  for _f in $(ls -1t "$DIR"/nuqati-*.dump 2>/dev/null); do
    _n=$((_n + 1))
    [ "$_n" -le "$MIN_KEEP" ] && continue
    if [ -n "$(find "$_f" -mtime +"$KEEP_DAYS" 2>/dev/null)" ]; then
      rm -f "$_f" && log "removed old backup $(basename "$_f")"
    fi
  done
}

run_backup() {
  mkdir -p "$DIR" || { fail "cannot create $DIR"; return 1; }
  _stamp=$(date -u +%Y%m%dT%H%M%SZ)
  _part="$DIR/.nuqati-$_stamp.dump.partial"
  _final="$DIR/nuqati-$_stamp.dump"
  _start=$(date +%s)
  _previous=$(ls -1t "$DIR"/nuqati-*.dump 2>/dev/null | head -n 1)

  if ! pg_dump -Fc -Z 6 -f "$_part"; then
    rm -f "$_part"; fail "pg_dump failed (database unreachable or wrong credentials?)"; return 1
  fi
  _size=$(stat -c %s "$_part" 2>/dev/null || echo 0)
  if [ "$_size" -lt 1 ]; then
    rm -f "$_part"; fail "the dump is empty"; return 1
  fi
  if ! pg_restore --list "$_part" >/dev/null 2>&1; then
    rm -f "$_part"; fail "the dump cannot be read back, it was discarded"; return 1
  fi
  mv "$_part" "$_final" || { rm -f "$_part"; fail "cannot move the dump into place"; return 1; }

  _secs=$(( $(date +%s) - _start ))
  printf '%s %s %s\n' "$_stamp" "$_size" "$_secs" > "$DIR/.last_ok.tmp" && mv "$DIR/.last_ok.tmp" "$DIR/LAST_OK"
  log "OK $(basename "$_final") ${_size} bytes in ${_secs}s"

  if [ -n "$_previous" ]; then
    _prev_size=$(stat -c %s "$_previous" 2>/dev/null || echo 0)
    if [ "$_prev_size" -gt 0 ] && [ $(( _size * 2 )) -lt "$_prev_size" ]; then
      log "WARNING this dump is less than half the size of the previous one ($(basename "$_previous"), ${_prev_size} bytes): check that no data was lost"
    fi
  fi
  prune
  return 0
}

wait_for_db() {
  until pg_isready -q; do
    log "waiting for the database"
    nap 5
  done
}

seconds_until_next_run() {
  _now=$(date -u +%s)
  _midnight=$(( _now - _now % 86400 ))
  _target=$(( _midnight + HOUR * 3600 ))
  [ "$_target" -le "$_now" ] && _target=$(( _target + 86400 ))
  echo $(( _target - _now ))
}

health() {
  if [ ! -f "$DIR/LAST_OK" ]; then echo "no successful backup yet"; exit 1; fi
  _age=$(hours_since "$DIR/LAST_OK")
  if [ "$_age" -ge "$MAX_AGE_H" ]; then echo "the last successful backup is ${_age} hours old (limit ${MAX_AGE_H})"; exit 1; fi
  echo "ok: last successful backup ${_age} hours ago"
}

loop() {
  trap 'log "stopping"; exit 0' TERM INT
  log "started: daily at ${HOUR}:00 UTC, keeping ${KEEP_DAYS} days (never fewer than ${MIN_KEEP} dumps)"
  mkdir -p "$DIR" && rm -f "$DIR"/.nuqati-*.partial "$DIR"/.last_ok.tmp
  wait_for_db
  if ! fresh_enough 20; then
    until run_backup; do log "retrying in ${RETRY_SECONDS}s"; nap "$RETRY_SECONDS"; done
  fi
  while :; do
    _wait=$(seconds_until_next_run)
    log "next backup in ${_wait}s"
    while [ "$_wait" -gt 0 ]; do
      _chunk=60; [ "$_wait" -lt 60 ] && _chunk=$_wait
      nap "$_chunk"
      _wait=$(( _wait - _chunk ))
    done
    until run_backup; do log "retrying in ${RETRY_SECONDS}s"; nap "$RETRY_SECONDS"; done
  done
}

case "${1:-loop}" in
  loop)   loop ;;
  once)   run_backup; exit $? ;;
  health) health ;;
  *)      echo "usage: backup.sh [loop|once|health]" >&2; exit 2 ;;
esac
