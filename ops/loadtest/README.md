# GPS ingestion load test

Measures the real API container (one process, as in `compose.yml`) with a real PostgreSQL 16 and simulated driver phones.
It runs as the CI job **Load test (GPS ingestion)** on every pull request. Standard library only, no packages to install.

| File | What it does |
|---|---|
| `seed.py` | Run inside the API image. Creates one company with N drivers (user, device session, vehicle, active trip) and a few administrators and prints their signed tokens as JSON. Refuses to run unless `NUQATI_LOADTEST_DISPOSABLE=1`, so it cannot be pointed at production by accident. |
| `gps_load.py` | The load generator. Scenarios: `steady` (N phones, one sample every 2 s, like the app), `replay` (phones that were offline send 100 queued samples back to back), `abuse` (one client as fast as it can while normal phones keep working), `mixed` (normal phones while administrators export monthly reports). `--gate` makes it exit 1 when the scenario's expectations fail. |
| `summary.py` | Turns the results into a table and checks the whole run: every accepted sample is in the database, no normal phone was ever refused, the abusive client's refusals were logged, no Python traceback in the API log. |
| `lib.sh` | `measure`: runs one scenario while sampling the API's CPU and memory and the number of database connections. |

**One set of drivers per scenario.** Give every scenario its own slice of the seeded drivers (`--offset`). A driver that already
sent samples would see its first new sample arrive less than 0.7 s after its last one from the previous scenario, and the API
answers such a sample (`filtered_short_interval`) without storing it. The CI job seeds 1,200 drivers and hands out disjoint slices.

**What the numbers mean.** A shared GitHub runner (4 vCPU) is not your server. Throughput and latency show where this design
starts to slow down and whether anything breaks or gets lost; they are not a promise about production. The CI job fails on
errors (a failed request, a Python traceback in the API log), refused normal phones, lost samples and a slow first step (p95
above 1.5 s at 50 phones), not on the larger steps' speed, which is only reported. Past what one process can serve (about
170 samples per second on the runner, 400 phones) requests wait their turn: latency grows, nothing fails.

**The burst scenario** (`burst`, 300 phones sending at the same instant, three rounds, on a second API container) reproduces
what happens when every phone uploads at once after an API restart. Before the request limit of Phase 4.1 (`docs/OPERATIONS.md`
section 8) it made the API stall: 600 of 900 requests failed (`QueuePool limit of size 5 overflow 10 reached`); with the
limit switched off in a control run, 731 of 900 failed with 107 pool errors; with it, 0 of 900 failed (p95 1.6 s). The table is in the job's summary page.

**Running it by hand** against a disposable database (never production): see the job `loadtest` in `.github/workflows/ci.yml`.
Choose another size with `--drivers`, `--seconds` and `--interval`.
