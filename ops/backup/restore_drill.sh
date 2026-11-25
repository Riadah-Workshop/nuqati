#!/bin/sh
# Nuqati restore drill: restores a backup into a throw-away database on the same PostgreSQL server,
# compares it with the live database, prints a result line for the drill log, and drops the copy again.
#
#   restore_drill.sh [path-to-dump]     (default: the newest dump in /backups)
#
# Run it from the backup container, ideally outside working hours (the restore uses CPU and disk):
#   docker exec <db_backup-container> /usr/local/bin/restore_drill.sh
#
# The live database is only read. The copy contains real personal data, so it is always dropped at the end.
# Connection settings come from PGHOST, PGUSER, PGPASSWORD, PGDATABASE. The user must be allowed to create
# databases (the PostgreSQL superuser created by the official image is).
set -u

DIR="${BACKUP_DIR:-/backups}"
DRILL_DB="${NUQATI_DRILL_DB:-nuqati_restore_drill}"
LIVE_DB="${PGDATABASE:-}"

say() { printf '%s\n' "$*"; }
die() { say "RESULT: FAILED - $*"; exit 1; }

[ -n "$LIVE_DB" ] || die "PGDATABASE is not set"
[ "$DRILL_DB" != "$LIVE_DB" ] || die "the drill database must not be the live database"
case "$DRILL_DB" in *[!A-Za-z0-9_]*|'') die "NUQATI_DRILL_DB may only contain letters, digits and underscores" ;; esac

DUMP="${1:-}"
[ -n "$DUMP" ] || DUMP=$(ls -1t "$DIR"/nuqati-*.dump 2>/dev/null | head -n 1)
[ -n "$DUMP" ] && [ -f "$DUMP" ] || die "no dump found in $DIR"

admin_sql() { psql -d postgres -v ON_ERROR_STOP=1 -X -q -c "$1"; }
cleanup() {
  admin_sql "DROP DATABASE IF EXISTS \"$DRILL_DB\"" >/dev/null 2>&1 && say "cleanup: the restored copy \"$DRILL_DB\" was dropped"
}
trap cleanup EXIT

START=$(date +%s)
say "drill: restoring $(basename "$DUMP") ($(stat -c %s "$DUMP") bytes) into \"$DRILL_DB\""
admin_sql "DROP DATABASE IF EXISTS \"$DRILL_DB\"" || die "cannot prepare the drill database"
admin_sql "CREATE DATABASE \"$DRILL_DB\"" || die "cannot create the drill database (is the user allowed to create databases?)"
pg_restore -d "$DRILL_DB" --no-owner --exit-on-error "$DUMP" || die "pg_restore reported errors"
SECS=$(( $(date +%s) - START ))

q_live() { psql -d "$LIVE_DB" -X -At -c "$1" 2>/dev/null; }
q_copy() { psql -d "$DRILL_DB" -X -At -c "$1" 2>/dev/null; }

TABLES_COPY=$(q_copy "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
TABLES_LIVE=$(q_live "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "${TABLES_COPY:-0}" -gt 0 ] 2>/dev/null || die "the restored database has no tables"

STATUS=OK
WARNINGS=""
say ""
say "table              live   restored"
for T in companies users drivers vehicles trips security_audit telematics_points; do
  IN_LIVE=$(q_live "SELECT to_regclass('public.$T') IS NOT NULL")
  IN_COPY=$(q_copy "SELECT to_regclass('public.$T') IS NOT NULL")
  if [ "$IN_LIVE" != "t" ] && [ "$IN_COPY" != "t" ]; then continue; fi
  if [ "$IN_COPY" != "t" ]; then
    case "$T" in
      companies|users) STATUS=FAILED; say "$T: MISSING in the restored copy" ;;
      *) WARNINGS="$WARNINGS $T(missing: created after this dump?)" ; say "$T: missing in the restored copy" ;;
    esac
    continue
  fi
  N_LIVE=$(q_live "SELECT count(*) FROM $T"); N_COPY=$(q_copy "SELECT count(*) FROM $T")
  printf '%-18s %-6s %s\n' "$T" "${N_LIVE:--}" "${N_COPY:--}"
  if [ -n "${N_LIVE:-}" ] && [ -n "${N_COPY:-}" ] && [ "$N_COPY" -gt "$N_LIVE" ]; then
    WARNINGS="$WARNINGS $T(restored has more rows than live)"
  fi
done

NEWEST_AUDIT=$(q_copy "SELECT max(created_at) FROM security_audit")
NEWEST_POINT=$(q_copy "SELECT max(recorded_at) FROM telematics_points")
say ""
say "newest security_audit row in the copy:   ${NEWEST_AUDIT:--}"
say "newest telematics point in the copy:     ${NEWEST_POINT:--}"
say "tables in public schema: live ${TABLES_LIVE:--}, restored ${TABLES_COPY}"
[ -z "$WARNINGS" ] || say "WARNINGS:$WARNINGS"

say ""
say "RESULT: $STATUS | dump=$(basename "$DUMP") | restore_seconds=$SECS | tables=$TABLES_COPY | $(date -u +%Y-%m-%dT%H:%M:%SZ)"
[ "$STATUS" = "OK" ]
