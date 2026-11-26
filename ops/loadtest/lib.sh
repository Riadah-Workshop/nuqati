# Helpers for CI job "Load test (GPS ingestion)" (.github/workflows/ci.yml). Source this file; it changes nothing by itself.
# Needs the containers nq-lapi (the API, published on host port 18000) and nq-ldb (PostgreSQL), the file seed.json and jq.

BASE=${BASE:-http://127.0.0.1:18000}
API_CONTAINER=${API_CONTAINER:-nq-lapi}
SCENARIO_LIMIT=${SCENARIO_LIMIT:-300}   # seconds; a scenario that is still running then is killed and recorded as "failed"

# measure <label> <seconds before sampling> <gps_load.py arguments...>
#   Runs one scenario in the background, samples the API's CPU and memory and the number of database connections while it
#   runs, waits for it, appends one JSON line to results.jsonl and returns the scenario's own exit status.
#   Use BASE=... API_CONTAINER=... measure ... to measure another API container.
measure() {
  local label="$1" delay="$2"; shift 2
  local rc=0 stats conns pid
  : > one.json
  timeout "$SCENARIO_LIMIT" python3 ops/loadtest/gps_load.py "$@" --base-url "$BASE" --seed seed.json --tag "$label" > one.json &
  pid=$!
  sleep "$delay"
  stats=$(docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}' "$API_CONTAINER")
  conns=$(docker exec nq-ldb psql -U ci -d ci -Atc "SELECT count(*) FROM pg_stat_activity WHERE datname='ci'")
  wait "$pid" || rc=$?
  if [ -s one.json ]; then
    jq -c --arg label "$label" --arg cpu "${stats%%|*}" --arg mem "${stats#*|}" --argjson conns "$conns" \
      '. + {label: $label, api_cpu: $cpu, api_mem: $mem, db_connections: $conns}' one.json >> results.jsonl
  else
    echo "scenario $label produced no result (exit status $rc)"
    jq -cn --arg label "$label" '{scenario: "failed", label: $label}' >> results.jsonl
  fi
  return "$rc"
}
