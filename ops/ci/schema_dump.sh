#!/bin/sh
# Normalised schema-only dump of one database in a running PostgreSQL container. The output is the text that
# backend/app/migrations/versions/0001_baseline.sql holds: CREATE and ALTER statements for schema "public" and
# nothing else (no SET lines, comments, owners, privileges, extensions data or the alembic_version table). Partial-index
# predicates are written back in their original form (baseline_rewrite.sed).
#
#   ops/ci/schema_dump.sh <postgres container> <database> [user]
set -eu
container=${1:?usage: schema_dump.sh <postgres container> <database> [user]}
database=${2:?usage: schema_dump.sh <postgres container> <database> [user]}
user=${3:-ci}
docker exec "$container" pg_dump -U "$user" -d "$database" --schema-only --no-owner --no-privileges --no-comments \
    --no-tablespaces --no-security-labels -n public -T public.alembic_version \
  | sed -e '/^--/d' -e '/^SET /d' -e '/^SELECT pg_catalog\.set_config/d' -e '/^\\/d' -e '/^CREATE SCHEMA public;$/d' \
  | sed -E -f "$(dirname "$0")/baseline_rewrite.sed" \
  | cat -s \
  | awk 'NF { if (seen) for (i = 0; i < blank; i++) print ""; blank = 0; seen = 1; print; next } { blank++ }'
