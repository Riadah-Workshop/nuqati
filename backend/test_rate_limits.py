"""Rate limits (Phase 4.1, finding S9): the limiter itself, its settings, and that the right routes use it.

These tests need only the standard library (no web framework, no database).
Behaviour on a real application and database is in test_rate_limits_postgres.py.
"""
import ast
import logging
import pathlib
import threading

import pytest

from app import rate_limits as rl

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / 'backend' / 'app'


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in rl.GROUP_ENV.values():
        monkeypatch.delenv(name, raising=False)


def make(capacity=3, refill=1.0, max_buckets=1000):
    clock = Clock()
    return rl.RateLimiter(clock=clock, max_buckets=max_buckets), clock, rl.Rule(capacity, refill, 'reports')


# ---- token bucket ----------------------------------------------------------------------------------------------------

def test_burst_is_allowed_then_refused_with_the_exact_wait():
    limiter, clock, rule = make(capacity=3, refill=1.0)
    assert [limiter.take('export', 1, rule) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.take('export', 1, rule) == pytest.approx(1.0)
    clock.now += 0.25
    assert limiter.take('export', 1, rule) == pytest.approx(0.75)  # waiting does not lose progress


def test_tokens_come_back_at_the_refill_rate_and_never_exceed_capacity():
    limiter, clock, rule = make(capacity=3, refill=2.0)
    for _ in range(3):
        limiter.take('export', 1, rule)
    clock.now += 1.0  # 2 tokens
    assert limiter.take('export', 1, rule) == 0.0
    assert limiter.take('export', 1, rule) == 0.0
    assert limiter.take('export', 1, rule) > 0.0
    clock.now += 3600  # a long idle time refills to capacity, not beyond
    assert [limiter.take('export', 1, rule) for _ in range(4)][:3] == [0.0, 0.0, 0.0]
    assert limiter.take('export', 1, rule) > 0.0


def test_users_and_scopes_are_counted_separately():
    limiter, _, rule = make(capacity=1, refill=0.1)
    assert limiter.take('export', 1, rule) == 0.0
    assert limiter.take('export', 1, rule) > 0.0
    assert limiter.take('export', 2, rule) == 0.0, 'another user must not be affected'
    assert limiter.take('report', 1, rule) == 0.0, 'another scope must not be affected'


def test_a_clock_that_goes_backwards_neither_adds_tokens_nor_creates_a_debt():
    limiter, clock, rule = make(capacity=1, refill=1.0)
    assert limiter.take('export', 1, rule) == 0.0
    clock.now -= 50
    assert limiter.take('export', 1, rule) > 0.0, 'going back in time must not refill the bucket'
    clock.now += 50.5  # 0.5 s after the step back: no debt is carried over from the backwards jump
    assert limiter.take('export', 1, rule) == 0.0


def test_the_clock_is_read_while_the_lock_is_held():
    holder = {}

    def clock():
        holder['locked'] = limiter._lock.locked()
        return 1000.0

    limiter = rl.RateLimiter(clock=clock)
    rule = rl.Rule(2, 1.0, 'reports')
    limiter.take('export', 1, rule)
    assert holder['locked'] is True
    holder.clear()
    limiter.should_log('export', 1)
    assert holder['locked'] is True


def test_memory_is_bounded_and_the_oldest_buckets_are_dropped_first():
    limiter, clock, rule = make(capacity=5, refill=1.0, max_buckets=50)
    for user in range(500):
        clock.now += 0.001
        limiter.take('export', user, rule)
        assert limiter.size() <= 50
    assert limiter.size() > 0


def test_concurrent_requests_never_get_more_than_the_burst():
    limiter, _, rule = make(capacity=50, refill=0.000001)
    allowed = []

    def worker():
        count = 0
        for _ in range(100):
            if limiter.take('export', 7, rule) == 0.0:
                count += 1
        allowed.append(count)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) == 50


def test_log_line_is_rate_limited_to_one_per_minute_per_user_and_scope():
    limiter, clock, rule = make(capacity=1, refill=0.001)
    limiter.take('export', 1, rule)
    limiter.take('export', 1, rule)
    assert limiter.should_log('export', 1) is True
    assert limiter.should_log('export', 1) is False
    clock.now += 59
    assert limiter.should_log('export', 1) is False
    clock.now += 2
    assert limiter.should_log('export', 1) is True
    assert limiter.should_log('export', 2) is False, 'no bucket, nothing to log'


# ---- modes -----------------------------------------------------------------------------------------------------------

def test_defaults_log_for_ingestion_and_enforce_for_reports():
    assert rl.mode_for('ingest') == 'log'
    assert rl.mode_for('reports') == 'enforce'


@pytest.mark.parametrize('value,expected', [('off', 'off'), ('LOG', 'log'), (' enforce ', 'enforce')])
def test_modes_are_read_from_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', value)
    assert rl.mode_for('ingest') == expected


def test_an_unknown_value_keeps_the_default_so_a_typo_cannot_switch_protection_off(monkeypatch, caplog):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'enforced')
    with caplog.at_level(logging.WARNING, logger='nuqati.rate_limits'):
        assert rl.mode_for('reports') == 'enforce'
    assert 'NUQATI_RATE_LIMIT_REPORTS' in caplog.text


def tiny_rules(monkeypatch, scope, capacity=2):
    monkeypatch.setitem(rl.RULES, scope, rl.Rule(capacity, 0.001, rl.RULES[scope].group))


def test_enforce_refuses_after_the_burst_with_a_retry_after(monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'enforce')
    tiny_rules(monkeypatch, 'export')
    limiter = rl.RateLimiter()
    results = [rl.evaluate('export', 5, limiter) for _ in range(3)]
    assert [r.refuse for r in results] == [False, False, True]
    assert results[2].exceeded and results[2].retry_after >= 1
    assert rl.evaluate('export', 6, limiter).refuse is False


def test_log_mode_counts_and_logs_but_never_refuses(monkeypatch, caplog):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', 'log')
    tiny_rules(monkeypatch, 'gps_sample')
    limiter = rl.RateLimiter()
    with caplog.at_level(logging.WARNING, logger='nuqati.rate_limits'):
        results = [rl.evaluate('gps_sample', 9, limiter) for _ in range(5)]
    assert not any(r.refuse for r in results)
    assert [r.exceeded for r in results] == [False, False, True, True, True]
    assert caplog.text.count('WOULD_REFUSE') == 1, 'one line per minute, not one per request'
    assert 'scope=gps_sample' in caplog.text and 'user=9' in caplog.text


def test_off_mode_does_not_even_create_a_bucket(monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'off')
    limiter = rl.RateLimiter()
    for _ in range(1000):
        assert rl.evaluate('export', 1, limiter) == rl.Decision(False, False, 0)
    assert limiter.size() == 0


def test_log_lines_contain_no_personal_data(monkeypatch, caplog):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'enforce')
    tiny_rules(monkeypatch, 'export', capacity=1)
    limiter = rl.RateLimiter()
    with caplog.at_level(logging.WARNING, logger='nuqati.rate_limits'):
        rl.evaluate('export', 31337, limiter)
        rl.evaluate('export', 31337, limiter)
    assert 'user=31337' in caplog.text
    assert '@' not in caplog.text


def test_every_rule_belongs_to_a_known_group_and_is_usable():
    for scope, rule in rl.RULES.items():
        assert rule.group in rl.GROUP_ENV and rule.group in rl.GROUP_DEFAULT, scope
        assert rule.capacity >= 1 and rule.refill_per_second > 0, scope


def test_unknown_scope_is_a_programming_error_found_at_import_time():
    with pytest.raises(KeyError):
        rl.limit('no_such_scope')


# ---- the driver app must keep its GPS points when it is limited ------------------------------------------------------

DRIVER_DROP_PHRASE = 'Sample interval must be at least 0.7 seconds'


def test_the_429_text_never_contains_the_phrase_that_makes_the_phone_delete_a_gps_point():
    for seconds in (1, 7, 3600):
        assert DRIVER_DROP_PHRASE not in rl.refusal_text(seconds)
        assert 'Sample interval' not in rl.refusal_text(seconds)


def test_the_phrase_checked_here_is_still_the_one_the_driver_app_looks_for():
    main_dart = (ROOT / 'driver_app' / 'main.dart').read_text(encoding='utf-8')
    assert f"r.statusCode==429 && r.body.contains('{DRIVER_DROP_PHRASE}')" in main_dart, (
        'driver_app/main.dart changed how it treats 429: update rate_limits.py and this test together')


def test_the_server_itself_never_sends_that_phrase():
    for path in APP.rglob('*.py'):
        assert DRIVER_DROP_PHRASE not in path.read_text(encoding='utf-8'), path


# ---- the right routes use the limiter (source level, no framework needed) --------------------------------------------

EXPECTED = {
    ('POST', '/api/v1/mobile/trips/{trip_id}/sample'): 'gps_sample',
    ('POST', '/api/v1/mobile/trips/{trip_id}/safety-event'): 'safety_event',
    ('POST', '/api/v1/mobile/tracking-heartbeat'): 'heartbeat',
    ('GET', '/api/v1/fleet/report'): 'report',
    ('GET', '/api/v1/fleet/monthly-reports'): 'report',
    ('GET', '/api/v1/fleet/monthly-reports/export'): 'export',
    ('GET', '/api/v1/fleet/concept-reports/{kind}'): 'report',
    ('GET', '/api/v1/fleet/concept-reports/{kind}/export'): 'export',
    ('GET', '/assignments/{assignment_id}/report'): 'export',  # router prefix is added by vehicle_handover.py
}


def limited_routes():
    """(method, path) -> scope for every route decorator that carries dependencies=[Depends(limit('...'))]."""
    found, decorated = {}, {}
    for path in list(APP.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                        and deco.func.attr in ('get', 'post', 'put', 'patch', 'delete') and deco.args
                        and isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str)):
                    continue
                key = (deco.func.attr.upper(), deco.args[0].value)
                decorated[key] = path.name
                for kw in deco.keywords:
                    if kw.arg != 'dependencies':
                        continue
                    for dep in ast.walk(kw.value):
                        if (isinstance(dep, ast.Call) and getattr(dep.func, 'id', '') == 'limit'
                                and dep.args and isinstance(dep.args[0], ast.Constant)):
                            found[key] = dep.args[0].value
    return found, decorated


def test_every_expected_route_exists_and_uses_its_scope():
    found, decorated = limited_routes()
    for route, scope in EXPECTED.items():
        assert route in decorated, f'{route} no longer exists: update EXPECTED and docs/OPERATIONS.md'
        assert found.get(route) == scope, f'{route} must use limit({scope!r}), has {found.get(route)!r}'


def test_no_other_route_uses_the_limiter_by_accident():
    found, _ = limited_routes()
    assert set(found) == set(EXPECTED)


def test_the_limiter_is_not_attached_to_login_or_tracker_routes():
    # authentication has its own database-backed throttling (auth_limits.py); the tracker receiver is not an HTTP route
    found, _ = limited_routes()
    assert not [route for route in found if '/auth/' in route[1] or 'teltonika' in route[1]]


# ---- configuration and documentation agree with the code ---------------------------------------------------------------

def test_compose_env_example_and_operations_guide_agree_with_the_defaults_in_code():
    compose = (ROOT / 'compose.yml').read_text(encoding='utf-8')
    for group, name in rl.GROUP_ENV.items():
        assert f'{name}: ${{{name}:-{rl.GROUP_DEFAULT[group]}}}' in compose, f'{name} default in compose.yml differs from the code'
        assert name in (ROOT / '.env.example').read_text(encoding='utf-8')
        assert name in (ROOT / 'docs' / 'OPERATIONS.md').read_text(encoding='utf-8')


def test_the_operations_guide_states_the_burst_and_rate_of_every_rule():
    guide = (ROOT / 'docs' / 'OPERATIONS.md').read_text(encoding='utf-8')
    section = guide[guide.index('## 7. Rate limits'):]
    for scope, rule in rl.RULES.items():
        burst = f'{rule.capacity:g}, then {rule.refill_per_second:g}'
        assert burst in section, f'docs/OPERATIONS.md section 7 must state "{burst}" for {scope}'
