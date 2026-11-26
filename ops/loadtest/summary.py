#!/usr/bin/env python3
"""Turns the load test results (one JSON object per line) into a Markdown table and checks the run as a whole.

    python3 ops/loadtest/summary.py results.jsonl --db-rows N --refused-logged M --tracebacks T

The whole-run checks (exit status 1 when one fails):
  - every sample the API said it accepted is in the database (nothing is lost under load), and there are no unexplained extra rows;
  - no normal driver was ever refused (HTTP 429) at any step, and no step up to 100 drivers saw a server error;
  - the abusive client's refusals were logged by the API (enforce mode really ran);
  - the API log contains no Python traceback.
Latency and throughput are reported, not judged: a shared CI runner is not your server.
"""
import argparse
import json
import sys

SMALL_STEP = 100  # drivers: up to this size an error is a failure; above it the run only reports


def gps_groups(results):
    """The measured groups that send GPS samples (exports are not samples)."""
    for r in results:
        if r['scenario'] in ('steady', 'replay'):
            yield r
        elif r['scenario'] == 'abuse':
            yield r['abuser']
            yield r['normal_drivers']
        elif r['scenario'] == 'mixed':
            yield r['gps']


def accepted_total(results):
    """Samples the API answered with accepted=true and stored."""
    return sum(group['accepted'] for group in gps_groups(results))


def uncertain_total(results):
    """Requests whose outcome the client cannot know: a failed connection (the server may still have stored the sample),
    and 200 answers that were not 'stored' (duplicates, which a retry after a lost answer produces). The database may hold
    up to this many rows more than the accepted count; it must never hold fewer."""
    return sum(group['statuses'].get('0', 0) + group['statuses'].get('200', 0) - group['accepted'] for group in gps_groups(results))


def rows(results):
    """(label, drivers, stats-dict) for every measured group."""
    for r in results:
        label = r.get('label', r['scenario'])
        if r['scenario'] in ('steady', 'replay'):
            yield label, r['drivers'], r, r
        elif r['scenario'] == 'abuse':
            yield label + ' (normal drivers)', r['normal_drivers']['drivers'], r['normal_drivers'], r
            yield label + ' (abusive client)', 1, r['abuser'], r
        elif r['scenario'] == 'mixed':
            yield label + ' (GPS)', r['drivers'], r['gps'], r
            yield label + ' (exports)', r['exporters'], r['exports'], r


def markdown(results):
    lines = ['| Scenario | Clients | Requests | per second | p50 ms | p95 ms | p99 ms | max ms | Answers | API CPU | API memory | DB connections |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for label, clients, stats, whole in rows(results):
        answers = ', '.join(f'{k}: {v}' for k, v in stats['statuses'].items())
        lines.append(f"| {label} | {clients} | {stats['requests']} | {stats['per_second']} | {stats['p50_ms']} | {stats['p95_ms']} | "
                     f"{stats['p99_ms']} | {stats['max_ms']} | {answers} | {whole.get('api_cpu', '')} | {whole.get('api_mem', '')} | "
                     f"{whole.get('db_connections', '')} |")
    return '\n'.join(lines)


def problems(results, db_rows, refused_logged, tracebacks):
    found = []
    expected = accepted_total(results)
    if db_rows < expected:
        found.append(f'the API accepted {expected} samples but the database holds only {db_rows}: samples were lost')
    elif db_rows > expected + uncertain_total(results):
        found.append(f'the database holds {db_rows} samples, more than the {expected} accepted plus '
                     f'{uncertain_total(results)} uncertain ones: rows nobody asked for')
    for r in results:
        if r['scenario'] != 'steady':
            continue
        statuses = r['statuses']
        if statuses.get('429'):
            found.append(f"{r.get('label', 'steady')}: {statuses['429']} normal-driver requests were refused with 429 (limit too tight)")
        errors = sum(v for k, v in statuses.items() if k == '0' or k.startswith('5'))
        if errors and r['drivers'] <= SMALL_STEP:
            found.append(f"{r.get('label', 'steady')}: {errors} server errors or failed connections at only {r['drivers']} drivers")
    if refused_logged < 1:
        found.append('the API log has no "rate_limit REFUSED" line although an abusive client was refused')
    if tracebacks:
        found.append(f'the API log contains {tracebacks} Python traceback(s)')
    if not results:
        found.append('no results were recorded')
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('results')
    parser.add_argument('--db-rows', type=int, required=True)
    parser.add_argument('--refused-logged', type=int, required=True)
    parser.add_argument('--tracebacks', type=int, required=True)
    args = parser.parse_args(argv)
    with open(args.results, encoding='utf-8') as handle:
        results = [json.loads(line) for line in handle if line.strip()]
    print(markdown(results) if results else '(no results)')
    found = problems(results, args.db_rows, args.refused_logged, args.tracebacks)
    for item in found:
        print('FAIL: ' + item, file=sys.stderr)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
