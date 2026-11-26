"""The load test tools (ops/loadtest) work as intended, checked against a stand-in HTTP server.

The real measurement is the CI job "Load test (GPS ingestion)"; these tests make sure the tools themselves are right
(counting, refusal handling, gates, the safety guard of the seed script) without a database or the web framework.
"""
import importlib.util
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / 'ops' / 'loadtest'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gps_load = load('gps_load')
seed_tool = load('seed')


class Stub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.lock = threading.Lock()
        self.counts = {}
        self.seen_sample_ids = []

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_address[1]}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def reply(self, status, body, headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length) or b'{}')
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        with self.server.lock:
            self.server.counts[token] = self.server.counts.get(token, 0) + 1
            count = self.server.counts[token]
            self.server.seen_sample_ids.append(body.get('sample_id'))
        if token == 'abuser' and count > 10:
            return self.reply(429, {'detail': 'Too many requests. Try again in 3 seconds.'}, {'Retry-After': '3'})
        if token == 'noheader' and count > 10:  # a refusal the app could not back off from
            return self.reply(429, {'detail': 'Too many requests.'})
        if token == 'dropper' and count > 10:  # the one 429 text that makes the phone delete a GPS point
            return self.reply(429, {'detail': 'Sample interval must be at least 0.7 seconds'}, {'Retry-After': '3'})
        if token == 'limited':
            return self.reply(429, {'detail': 'Too many requests. Try again in 3 seconds.'}, {'Retry-After': '3'})
        if token == 'rejecting':
            return self.reply(200, {'accepted': False, 'reason': 'GPS accuracy worse than 50m'})
        if token == 'broken':
            return self.reply(500, {'detail': 'boom'})
        self.reply(200, {'accepted': True})

    def do_GET(self):
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        with self.server.lock:
            self.server.counts[token] = self.server.counts.get(token, 0) + 1
            count = self.server.counts[token]
        if token == 'servererror':
            return self.reply(500, {'detail': 'boom'})
        if token == 'always429' or count > 2:
            return self.reply(429, {'detail': 'Too many requests. Try again in 1 seconds.'}, {'Retry-After': '1'})
        self.reply(200, b'file-bytes')


@pytest.fixture
def stub():
    server = Stub()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def seed_file(tmp_path, drivers=60, tokens=None, admins=('a0', 'a1')):
    items = [{'token': f't{i}', 'trip_id': 1000 + i} for i in range(drivers)]
    for index, token in (tokens or {}).items():
        items[index]['token'] = token
    path = tmp_path / 'seed.json'
    path.write_text(json.dumps({'company_id': 1, 'drivers': items, 'admin_tokens': list(admins)}))
    return str(path)


def run(stub, tmp_path, *argv, **seed_options):
    out = pathlib.Path(tmp_path) / 'out.json'
    return gps_load.main([*argv, '--base-url', stub.url, '--seed', seed_file(tmp_path, **seed_options)]), out


# ---- helpers ---------------------------------------------------------------------------------------------------------

def test_percentiles_and_summary():
    assert gps_load.percentile([], 0.95) == 0.0
    assert gps_load.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert gps_load.percentile(list(range(101)), 0.95) == 95
    summary = gps_load.summarize([(200, 0.010, True), (200, 0.020, True), (429, 0.5, False)], 1.0)
    assert summary['requests'] == 3 and summary['accepted'] == 2 and summary['statuses'] == {'200': 2, '429': 1}
    assert summary['max_ms'] == 500.0


def test_sample_bodies_are_valid_for_the_api_and_unique():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    bodies = [gps_load.sample_body('x', n, now) for n in range(1, 200)]
    assert len({b['sample_id'] for b in bodies}) == len(bodies)
    for body in bodies:
        assert 8 <= len(body['sample_id']) <= 80
        assert -90 <= body['latitude'] <= 90 and -180 <= body['longitude'] <= 180
        assert 0 <= body['speed_kmh'] <= 350 and body['accuracy_m'] <= 50


# ---- scenarios against the stand-in server -----------------------------------------------------------------------------

def test_steady_counts_every_request_and_passes_its_gate(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'steady', '--drivers', '5', '--seconds', '1.5', '--interval', '0.3', '--gate')
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result['failures'] == []
    assert result['drivers'] == 5 and result['requests'] >= 15
    assert result['statuses'] == {'200': result['requests']} and result['accepted'] == result['requests']
    assert sum(stub.counts.values()) == result['requests']


def test_steady_gate_fails_when_a_normal_driver_gets_an_error(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'steady', '--drivers', '3', '--seconds', '1', '--interval', '0.3', '--gate',
                  tokens={1: 'broken'})
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and any('non-200' in f for f in result['failures'])


def test_steady_gate_can_check_latency(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'steady', '--drivers', '2', '--seconds', '1', '--interval', '0.3', '--gate', '--p95-ms', '0.0001')
    assert code == 1 and 'p95' in json.loads(capsys.readouterr().out)['failures'][0]


def test_replay_sends_every_backlog_sample_in_order_and_expects_all_accepted(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'replay', '--drivers', '4', '--offset', '10', '--samples', '25', '--gate')
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result['accepted'] == 100 and result['requests'] == 100
    ids = [i for i in stub.seen_sample_ids if '-r0-' in i]
    assert ids == sorted(ids) and len(ids) == 25


def test_abuse_is_refused_with_retry_after_while_normal_drivers_are_untouched(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'abuse', '--offset', '40', '--requests', '60', '--steady', '5', '--seconds', '4',
                  '--interval', '0.4', '--gate', tokens={40: 'abuser'})
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert result['abuser']['statuses'] == {'200': 10, '429': 50}
    assert result['abuser']['refused_with_retry_after'] == 50
    assert set(result['normal_drivers']['statuses']) == {'200'}


def test_abuse_gate_fails_when_the_abuser_is_never_refused(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'abuse', '--offset', '40', '--requests', '30', '--steady', '3', '--seconds', '3',
                  '--interval', '0.5', '--gate')
    assert code == 1 and 'refused only 0' in ' '.join(json.loads(capsys.readouterr().out)['failures'])


def test_mixed_counts_gps_and_exports_separately(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'mixed', '--drivers', '4', '--exporters', '2', '--seconds', '3', '--interval', '0.5', '--gate')
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert result['gps']['statuses'] == {'200': result['gps']['requests']}
    assert result['exports']['accepted'] >= 2 and set(result['exports']['statuses']) <= {'200', '429'}


def test_a_seed_file_with_too_few_drivers_is_a_usage_error(stub, tmp_path):
    code, _ = run(stub, tmp_path, 'steady', '--drivers', '99', drivers=5)
    assert code == 2


def test_a_dead_server_counts_as_failures_not_as_a_crash(tmp_path, capsys):
    code = gps_load.main(['steady', '--drivers', '2', '--seconds', '1', '--interval', '0.3', '--gate',
                          '--base-url', 'http://127.0.0.1:9', '--seed', seed_file(tmp_path)])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result['statuses'].get('0', 0) > 0


# ---- the seed script must never touch a real database --------------------------------------------------------------------

def test_the_seed_script_refuses_without_the_explicit_disposable_flag(monkeypatch, capsys):
    monkeypatch.delenv('NUQATI_LOADTEST_DISPOSABLE', raising=False)
    assert seed_tool.main(['--drivers', '3']) == 2
    assert 'NUQATI_LOADTEST_DISPOSABLE=1' in capsys.readouterr().err


def test_the_seed_script_rejects_absurd_sizes(monkeypatch):
    monkeypatch.setenv('NUQATI_LOADTEST_DISPOSABLE', '1')
    assert seed_tool.main(['--drivers', '0']) == 2
    assert seed_tool.main(['--drivers', '100000']) == 2


# ---- every gate really fails when what it guards goes wrong -------------------------------------------------------------

def gate_failures(capsys):
    return ' | '.join(json.loads(capsys.readouterr().out)['failures'])


def test_abuse_gate_fails_when_a_refusal_has_no_retry_after(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'abuse', '--offset', '40', '--requests', '40', '--steady', '3', '--seconds', '3',
                  '--interval', '0.5', '--gate', tokens={40: 'noheader'})
    assert code == 1 and 'Retry-After' in gate_failures(capsys)


def test_abuse_gate_fails_when_a_refusal_uses_the_text_that_makes_the_phone_drop_the_point(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'abuse', '--offset', '40', '--requests', '40', '--steady', '3', '--seconds', '3',
                  '--interval', '0.5', '--gate', tokens={40: 'dropper'})
    assert code == 1 and 'Retry-After' in gate_failures(capsys)


def test_abuse_gate_fails_when_normal_drivers_are_hurt_meanwhile(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'abuse', '--offset', '40', '--requests', '40', '--steady', '3', '--seconds', '3',
                  '--interval', '0.5', '--gate', tokens={40: 'abuser', 1: 'broken'})
    assert code == 1 and 'normal drivers were affected' in gate_failures(capsys)


def test_replay_gate_fails_when_a_backlog_is_limited(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'replay', '--drivers', '2', '--offset', '10', '--samples', '5', '--gate', tokens={10: 'limited'})
    assert code == 1 and 'must not be limited' in gate_failures(capsys)


def test_replay_gate_fails_when_samples_are_answered_but_not_accepted(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'replay', '--drivers', '2', '--offset', '10', '--samples', '5', '--gate', tokens={10: 'rejecting'})
    assert code == 1 and 'expected 10 accepted samples, got 5' in gate_failures(capsys)


def test_mixed_gate_fails_when_no_export_completes(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'mixed', '--drivers', '3', '--exporters', '1', '--seconds', '2', '--interval', '0.5', '--gate',
                  admins=('always429',))
    assert code == 1 and 'no export completed' in gate_failures(capsys)


def test_mixed_gate_fails_when_an_export_errors(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'mixed', '--drivers', '3', '--exporters', '1', '--seconds', '2', '--interval', '0.5', '--gate',
                  admins=('servererror',))
    assert code == 1 and 'exports failed' in gate_failures(capsys)


def test_mixed_gate_fails_when_gps_breaks_while_exports_run(stub, tmp_path, capsys):
    code, _ = run(stub, tmp_path, 'mixed', '--drivers', '3', '--exporters', '1', '--seconds', '2', '--interval', '0.5', '--gate',
                  tokens={0: 'broken'})
    assert code == 1 and 'GPS requests failed while exports ran' in gate_failures(capsys)


# ---- summary and whole-run checks --------------------------------------------------------------------------------------

summary_tool = load('summary')


def stats(requests=100, accepted=100, statuses=None, **extra):
    return {'requests': requests, 'per_second': 25.0, 'accepted': accepted, 'statuses': statuses or {'200': requests},
            'p50_ms': 10.0, 'p95_ms': 30.0, 'p99_ms': 50.0, 'max_ms': 80.0, **extra}


def full_run():
    return [
        {'scenario': 'steady', 'label': 'ramp 50', 'drivers': 50, **stats(), 'api_cpu': '40%', 'api_mem': '120MiB', 'db_connections': 7},
        {'scenario': 'steady', 'label': 'ramp 400', 'drivers': 400, **stats(1000, 1000)},
        {'scenario': 'replay', 'label': 'replay', 'drivers': 20, **stats(2000, 2000)},
        {'scenario': 'abuse', 'label': 'abuse', 'abuser': {**stats(700, 300, {'200': 300, '429': 400}), 'refused_with_retry_after': 400},
         'normal_drivers': {'drivers': 50, **stats(500, 500)}},
        {'scenario': 'mixed', 'label': 'mixed', 'drivers': 50, 'exporters': 2, 'gps': stats(300, 300), 'exports': stats(20, 12, {'200': 12, '429': 8})},
    ]


def test_accepted_total_counts_every_scenario_once():
    assert summary_tool.accepted_total(full_run()) == 100 + 1000 + 2000 + 300 + 500 + 300


def test_a_clean_run_has_no_problems_and_a_table_row_per_group():
    run = full_run()
    assert summary_tool.problems(run, db_rows=summary_tool.accepted_total(run), refused_logged=3, tracebacks=0) == []
    table = summary_tool.markdown(run)
    assert table.count('\n') == 2 + 7 - 1  # header, rule, then seven measured groups
    assert 'ramp 50' in table and '40%' in table and 'abuse (abusive client)' in table and '429: 400' in table


def test_lost_samples_are_reported():
    run = full_run()
    found = summary_tool.problems(run, summary_tool.accepted_total(run) - 7, 1, 0)
    assert len(found) == 1 and 'samples were lost' in found[0]


def test_rows_beyond_what_the_client_could_not_know_are_reported_but_a_lost_answer_is_tolerated():
    run = full_run()
    total = summary_tool.accepted_total(run)
    assert summary_tool.uncertain_total(run) == 0
    assert any('rows nobody asked for' in f for f in summary_tool.problems(run, total + 1, 1, 0))

    # one failed connection and two answers that were not "stored" (duplicates): the server may have stored any of them
    run[0]['statuses'] = {'200': 99, '0': 1}
    run[0]['accepted'] = 97
    total, uncertain = summary_tool.accepted_total(run), summary_tool.uncertain_total(run)
    assert uncertain == 3

    def database_messages(rows):
        return [f for f in summary_tool.problems(run, rows, 1, 0) if 'database' in f]

    assert database_messages(total + uncertain) == []
    assert database_messages(total) == []
    assert any('rows nobody asked for' in f for f in database_messages(total + uncertain + 1))
    assert any('samples were lost' in f for f in database_messages(total - 1))


def test_a_refused_normal_driver_is_a_failure_at_any_size():
    run = full_run()
    run[1]['statuses'] = {'200': 990, '429': 10}
    assert any('limit too tight' in f for f in summary_tool.problems(run, summary_tool.accepted_total(run), 1, 0))


def test_server_errors_fail_small_steps_but_only_report_for_large_ones():
    run = full_run()
    run[1]['statuses'], run[1]['accepted'] = {'200': 900, '500': 100}, 900  # 400 drivers: reported only
    assert summary_tool.problems(run, summary_tool.accepted_total(run), 1, 0) == []
    run[0]['statuses'], run[0]['accepted'] = {'200': 99, '0': 1}, 99  # 50 drivers: a failed connection is a failure
    assert any('failed connections' in f for f in summary_tool.problems(run, summary_tool.accepted_total(run), 1, 0))


def test_no_logged_refusal_and_tracebacks_are_failures():
    run = full_run()
    total = summary_tool.accepted_total(run)
    assert any('rate_limit REFUSED' in f for f in summary_tool.problems(run, total, 0, 0))
    assert any('traceback' in f for f in summary_tool.problems(run, total, 1, 2))
    assert summary_tool.problems([], 0, 1, 0) == ['no results were recorded']


def test_summary_command_line(tmp_path, capsys):
    path = tmp_path / 'r.jsonl'
    run = full_run()
    path.write_text('\n'.join(json.dumps(r) for r in run) + '\n')
    total = summary_tool.accepted_total(run)
    assert summary_tool.main([str(path), '--db-rows', str(total), '--refused-logged', '5', '--tracebacks', '0']) == 0
    assert '| ramp 50 |' in capsys.readouterr().out
    assert summary_tool.main([str(path), '--db-rows', str(total - 1), '--refused-logged', '5', '--tracebacks', '0']) == 1


def test_only_stored_samples_count_as_accepted():
    ok = json.dumps({'accepted': True, 'events': []}).encode()
    assert gps_load.accepted(200, ok) is True
    assert gps_load.accepted(200, json.dumps({'accepted': True, 'duplicate': True}).encode()) is False
    assert gps_load.accepted(200, json.dumps({'accepted': True, 'duplicate': True, 'filtered_short_interval': True}).encode()) is False
    assert gps_load.accepted(200, json.dumps({'accepted': False, 'reason': 'GPS accuracy worse than 50m'}).encode()) is False
    assert gps_load.accepted(429, ok) is False
    assert gps_load.accepted(200, b'not json') is False
