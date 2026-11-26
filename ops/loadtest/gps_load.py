#!/usr/bin/env python3
"""Load generator for the GPS ingestion route and for exports (standard library only).

Each simulated driver behaves like the driver app: one POST /api/v1/mobile/trips/{id}/sample every --interval seconds
over a keep-alive connection. Data comes from ops/loadtest/seed.py (--seed file). Scenarios:

  steady   N drivers send in real time for --seconds.
  replay   K drivers each send a backlog of --samples samples back to back (what the app does after being offline).
  abuse    one client sends --requests samples as fast as it can while --steady normal drivers keep working:
           the abuser must be refused (HTTP 429 with Retry-After) and the normal drivers must not notice.
  mixed    --drivers normal drivers while --exporters administrators keep generating monthly report exports.

Results are printed as one JSON object on stdout and a short table row on stderr. With --gate the process exits with
status 1 when the scenario's expectations are not met (see the code: they are deliberately loose, errors and refusals of
normal drivers are failures; latency is only checked where --p95-ms is given).
"""
import argparse
import http.client
import json
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


class Client:
    """One keep-alive connection. status 0 means the connection itself failed."""

    def __init__(self, base_url: str):
        parts = urlsplit(base_url)
        self.host, self.port, self.conn = parts.hostname, parts.port or 80, None

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None

    def request(self, method: str, path: str, token: str, body=None, timeout: float = 60.0):
        started = time.perf_counter()
        payload = json.dumps(body) if body is not None else None
        for attempt in (1, 2):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
                self.conn.request(method, path, body=payload,
                                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                response = self.conn.getresponse()
                data = response.read()
                headers = {k.lower(): v for k, v in response.getheaders()}
                return response.status, headers, data, time.perf_counter() - started
            except (http.client.HTTPException, OSError):
                self.close()
                if attempt == 2:
                    return 0, {}, b'', time.perf_counter() - started
        return 0, {}, b'', time.perf_counter() - started


def sample_body(tag: str, n: int, captured: datetime) -> dict:
    return {'sample_id': f'lt-{tag}-{n:06d}', 'captured_at': iso(captured),
            'latitude': 24.70 + (n % 3000) * 0.0003, 'longitude': 46.70 + (n % 7) * 0.0001,
            'accuracy_m': 5.0, 'speed_kmh': 130.0 if n % 40 == 0 else 40.0 + (n % 5) * 10.0,  # every 40th sample speeds
            'acceleration_ms2': 0.0}


def accepted(status: int, data: bytes) -> bool:
    """True when the API stored the sample. A duplicate or a too-close sample is answered 200 with accepted=true but
    is not stored (the server acknowledges it without writing), so it does not count: the run's database check compares
    this number with the rows in driver_locations."""
    if status != 200:
        return False
    try:
        body = json.loads(data)
    except ValueError:
        return False
    return body.get('accepted') is True and not body.get('duplicate') and not body.get('filtered_short_interval')


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]


def summarize(records, seconds):
    """records: list of (status, seconds, accepted_flag)."""
    latencies = sorted(r[1] * 1000.0 for r in records)
    statuses = {}
    for status, _, _ in records:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    return {
        'requests': len(records),
        'per_second': round(len(records) / seconds, 1) if seconds > 0 else 0.0,
        'accepted': sum(1 for r in records if r[2]),
        'statuses': dict(sorted(statuses.items())),
        'p50_ms': round(percentile(latencies, 0.50), 1), 'p95_ms': round(percentile(latencies, 0.95), 1),
        'p99_ms': round(percentile(latencies, 0.99), 1), 'max_ms': round(latencies[-1], 1) if latencies else 0.0,
    }


def run_steady(base, drivers, seconds, interval, tag, stop_event=None):
    """Real-time drivers. Returns (records, late_count)."""
    results, late, lock = [], [0], threading.Lock()
    end = time.monotonic() + seconds

    def worker(driver, index):
        client, mine, behind, n = Client(base), [], 0, 0
        next_at = time.monotonic() + random.uniform(0, interval)
        while time.monotonic() < end and not (stop_event and stop_event.is_set()):
            pause = next_at - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                behind += 1
            n += 1
            status, _, data, took = client.request('POST', f'/api/v1/mobile/trips/{driver["trip_id"]}/sample',
                                                   driver['token'], sample_body(f'{tag}-{index}', n, datetime.now(timezone.utc)))
            mine.append((status, took, accepted(status, data)))
            next_at += interval
        client.close()
        with lock:
            results.extend(mine)
            late[0] += behind

    threads = [threading.Thread(target=worker, args=(d, i)) for i, d in enumerate(drivers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, late[0]


def scenario_steady(args, seed):
    drivers = seed['drivers'][args.offset:args.offset + args.drivers]
    started = time.monotonic()
    records, late = run_steady(args.base_url, drivers, args.seconds, args.interval, f'{args.tag}')
    elapsed = time.monotonic() - started
    result = {'scenario': 'steady', 'drivers': len(drivers), 'seconds': round(elapsed, 1), 'interval_s': args.interval,
              'late_sends': late, **summarize(records, elapsed)}
    failures = []
    if args.gate:
        bad = [s for s in result['statuses'] if s != '200']
        if bad:
            failures.append(f'normal drivers got non-200 answers: {result["statuses"]}')
        if result['accepted'] != result['requests']:
            failures.append('some samples were not accepted')
        if args.p95_ms and result['p95_ms'] > args.p95_ms:
            failures.append(f'p95 {result["p95_ms"]} ms is above {args.p95_ms} ms')
    return result, failures


def scenario_replay(args, seed):
    drivers = seed['drivers'][args.offset:args.offset + args.drivers]
    base_time = datetime.now(timezone.utc) - timedelta(hours=2)
    results, lock = [], threading.Lock()

    def worker(driver, index):
        client, mine = Client(args.base_url), []
        for n in range(1, args.samples + 1):
            status, _, data, took = client.request('POST', f'/api/v1/mobile/trips/{driver["trip_id"]}/sample', driver['token'],
                                                   sample_body(f'{args.tag}-r{index}', n, base_time + timedelta(seconds=2 * n)))
            mine.append((status, took, accepted(status, data)))
        client.close()
        with lock:
            results.extend(mine)

    started = time.monotonic()
    threads = [threading.Thread(target=worker, args=(d, i)) for i, d in enumerate(drivers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started
    result = {'scenario': 'replay', 'drivers': len(drivers), 'samples_each': args.samples, 'seconds': round(elapsed, 1),
              **summarize(results, elapsed)}
    failures = []
    if args.gate:
        if result['accepted'] != len(drivers) * args.samples:
            failures.append(f'expected {len(drivers) * args.samples} accepted samples, got {result["accepted"]}: {result["statuses"]}')
        if '429' in result['statuses']:
            failures.append('a backlog replay of this size must not be limited')
    return result, failures


def scenario_abuse(args, seed):
    abuser = seed['drivers'][args.offset]
    steady_drivers = seed['drivers'][:args.steady]
    stop, steady_out = threading.Event(), {}

    def steady_thread():
        steady_out['records'], steady_out['late'] = run_steady(args.base_url, steady_drivers, args.seconds, args.interval,
                                                                f'{args.tag}-n', stop)

    thread = threading.Thread(target=steady_thread)
    thread.start()
    time.sleep(2)
    client, mine, retry_after_ok = Client(args.base_url), [], 0
    base_time = datetime.now(timezone.utc) - timedelta(hours=1)
    started = time.monotonic()
    for n in range(1, args.requests + 1):
        status, headers, data, took = client.request('POST', f'/api/v1/mobile/trips/{abuser["trip_id"]}/sample', abuser['token'],
                                                     sample_body(f'{args.tag}-abuse', n, base_time + timedelta(seconds=n)))
        mine.append((status, took, accepted(status, data)))
        if status == 429 and headers.get('retry-after', '').isdigit() and int(headers['retry-after']) >= 1 \
                and b'Sample interval' not in data:
            retry_after_ok += 1
    abuse_seconds = time.monotonic() - started
    client.close()
    thread.join()
    normal = summarize(steady_out['records'], args.seconds)
    result = {'scenario': 'abuse', 'abuser': {**summarize(mine, abuse_seconds), 'refused_with_retry_after': retry_after_ok},
              'normal_drivers': {'drivers': len(steady_drivers), **normal}}
    failures = []
    if args.gate:
        refused = result['abuser']['statuses'].get('429', 0)
        if refused < args.requests // 4:
            failures.append(f'the abuser was refused only {refused} times out of {args.requests}')
        if retry_after_ok != refused:
            failures.append('every 429 must carry Retry-After (>= 1) and a text the app does not treat as a dropped point')
        if set(normal['statuses']) - {'200'}:
            failures.append(f'normal drivers were affected during the abuse: {normal["statuses"]}')
    return result, failures


def scenario_mixed(args, seed):
    drivers = seed['drivers'][:args.drivers]
    now = datetime.now(timezone.utc)
    paths = [f'/api/v1/fleet/monthly-reports/export?year={now.year}&month={now.month}&format={fmt}&kind=rag'
             for fmt in ('xlsx', 'pdf', 'csv')]
    stop, export_records, lock = threading.Event(), [], threading.Lock()

    def exporter(index):
        client, mine, n = Client(args.base_url), [], 0
        token = seed['admin_tokens'][index % len(seed['admin_tokens'])]
        while not stop.is_set():
            status, headers, data, took = client.request('GET', paths[n % len(paths)], token)
            n += 1
            mine.append((status, took, status == 200 and len(data) > 0))
            if status == 429:  # an exporter that respects Retry-After, like a person clicking again later
                stop.wait(min(5.0, float(headers.get('retry-after', '1') or 1)))
        client.close()
        with lock:
            export_records.extend(mine)

    threads = [threading.Thread(target=exporter, args=(i,)) for i in range(args.exporters)]
    for t in threads:
        t.start()
    started = time.monotonic()
    records, late = run_steady(args.base_url, drivers, args.seconds, args.interval, f'{args.tag}-m')
    elapsed = time.monotonic() - started
    stop.set()
    for t in threads:
        t.join()
    result = {'scenario': 'mixed', 'drivers': len(drivers), 'exporters': args.exporters, 'late_sends': late,
              'gps': summarize(records, elapsed), 'exports': summarize(export_records, elapsed)}
    failures = []
    if args.gate:
        if set(result['gps']['statuses']) - {'200'}:
            failures.append(f'GPS requests failed while exports ran: {result["gps"]["statuses"]}')
        if set(result['exports']['statuses']) - {'200', '429'}:
            failures.append(f'exports failed: {result["exports"]["statuses"]}')
        if not result['exports']['accepted']:
            failures.append('no export completed')
    return result, failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('scenario', choices=['steady', 'replay', 'abuse', 'mixed'])
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--seed', required=True, help='JSON file written by ops/loadtest/seed.py')
    parser.add_argument('--drivers', type=int, default=50)
    parser.add_argument('--offset', type=int, default=0, help='first driver of the seed list to use')
    parser.add_argument('--seconds', type=float, default=30.0)
    parser.add_argument('--interval', type=float, default=2.0, help='seconds between samples of one driver (the app uses about 2)')
    parser.add_argument('--samples', type=int, default=100, help='replay: samples per driver')
    parser.add_argument('--requests', type=int, default=700, help='abuse: requests from the abusive client')
    parser.add_argument('--steady', type=int, default=50, help='abuse: normal drivers running alongside')
    parser.add_argument('--exporters', type=int, default=2, help='mixed: administrators exporting reports')
    parser.add_argument('--tag', default=str(int(time.time())), help='makes sample ids unique per run')
    parser.add_argument('--gate', action='store_true', help='exit 1 when the scenario fails its expectations')
    parser.add_argument('--p95-ms', type=float, default=0.0, help='steady: fail above this 95th percentile (needs --gate)')
    args = parser.parse_args(argv)
    with open(args.seed, encoding='utf-8') as handle:
        seed = json.load(handle)
    needed = {'steady': args.offset + args.drivers, 'replay': args.offset + args.drivers, 'abuse': max(args.offset + 1, args.steady),
              'mixed': args.drivers}[args.scenario]
    if needed > len(seed['drivers']):
        print(f'the seed file has {len(seed["drivers"])} drivers, this run needs {needed}', file=sys.stderr)
        return 2
    scenario = {'steady': scenario_steady, 'replay': scenario_replay, 'abuse': scenario_abuse, 'mixed': scenario_mixed}[args.scenario]
    result, failures = scenario(args, seed)
    result['failures'] = failures
    print(json.dumps(result))
    for failure in failures:
        print('FAIL: ' + failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
