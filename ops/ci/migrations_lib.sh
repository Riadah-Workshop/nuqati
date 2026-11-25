# Helpers for CI job "Migrations" (.github/workflows/ci.yml). Source this file; it changes nothing by itself.
# Needs a PostgreSQL container named nq-mdb on the docker network nq-m and the image nuqati-api:ci.

MDB=nq-mdb
NET=nq-m
SECRET=ci-only-secret-at-least-32-characters-long-0000

# sql <database> "<statement>"  -> prints the plain result (no headers, no alignment)
sql() { docker exec -i "$MDB" psql -U ci -d "$1" -v ON_ERROR_STOP=1 -Atq -c "$2"; }
# newdb <name> | copydb <template> <name>
newdb() { docker exec "$MDB" psql -U ci -d postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE $1"; }
copydb() { docker exec "$MDB" psql -U ci -d postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE $2 TEMPLATE $1"; }
# fingerprint <database>  -> sorted list of every schema object (ops/ci/schema_fingerprint.sql)
fingerprint() { docker exec -i "$MDB" psql -U ci -d "$1" -v ON_ERROR_STOP=1 -Atq -f - < ops/ci/schema_fingerprint.sql; }
# api <database> [docker run options] <image> <command...>   (the first argument after the database name is passed on as is)
api() {
  local database="$1"; shift
  docker run --rm --network "$NET" -e "DATABASE_URL=postgresql+psycopg2://ci:ci-only@$MDB:5432/$database" -e "NUQATI_AUTH_SECRET=$SECRET" "$@"
}
# expect_exit <code> <description> -- <command...>  -> runs the command, keeps its output in $OUT, fails if the exit code differs
expect_exit() {
  local want="$1" what="$2"; shift 3
  set +e; OUT=$("$@" 2>&1); local got=$?; set -e
  printf '%s\n' "$OUT" | sed 's/^/    | /'
  if [ "$got" != "$want" ]; then echo "FAIL: $what: exit code $got, expected $want"; exit 1; fi
  echo "ok: $what (exit $got)"
}
# must_not <command...>  -> fails the step if the command succeeds (a bare `! cmd` is ignored by `set -e`)
must_not() { if "$@"; then echo "FAIL: this must not succeed: $*"; exit 1; fi; }
version_of() { sql "$1" "SELECT version_num FROM alembic_version"; }
has_version_table() { [ -n "$(sql "$1" "SELECT to_regclass('public.alembic_version')")" ]; }
# ready <container>  -> succeeds when the API in the container answers /api/v1/ready (waits up to two minutes)
ready() {
  for i in $(seq 1 60); do
    docker exec "$1" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4)" 2>/dev/null && return 0
    [ "$(docker inspect -f '{{.State.Running}}' "$1")" = "true" ] || return 1
    sleep 2
  done
  return 1
}
# start_api <container> <database> [NUQATI_RUN_MIGRATIONS value]  -> starts the API image the way compose does (default CMD).
# Without a value the variable is not set at all, which is the default of the image (migrations on).
start_api() {
  local flag=()
  [ -n "${3:-}" ] && flag=(-e "NUQATI_RUN_MIGRATIONS=$3")
  docker run -d --name "$1" --network "$NET" -e "DATABASE_URL=postgresql+psycopg2://ci:ci-only@$MDB:5432/$2" \
    -e "NUQATI_AUTH_SECRET=$SECRET" "${flag[@]}" nuqati-api:ci
}
