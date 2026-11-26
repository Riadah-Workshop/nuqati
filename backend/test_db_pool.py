"""Connection pool sizing and request admission (Phase 4.1): the API must not stall when many requests arrive at once.

Standard library only. The behaviour on a real API and PostgreSQL is measured by the CI job "Load test (GPS ingestion)",
scenario "burst" (300 phones at the same instant).
"""
import ast
import asyncio
import logging
import pathlib
import threading

import pytest

from app import db_pool

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / 'backend' / 'app'


# ---- settings ---------------------------------------------------------------------------------------------------------

def test_defaults_keep_the_pool_size_sqlalchemy_used_before_and_reserve_five_connections():
    settings = db_pool.load_pool_settings({})
    assert (settings.pool_size, settings.max_overflow, settings.total) == (5, 10, 15)
    assert settings.request_slots == 10


def test_slots_follow_the_pool_size_unless_set_explicitly():
    assert db_pool.load_pool_settings({'NUQATI_DB_POOL_SIZE': '20', 'NUQATI_DB_MAX_OVERFLOW': '10'}).request_slots == 25
    assert db_pool.load_pool_settings({'NUQATI_DB_REQUEST_SLOTS': '7'}).request_slots == 7
    assert db_pool.load_pool_settings({'NUQATI_DB_POOL_SIZE': '2', 'NUQATI_DB_MAX_OVERFLOW': '1'}).request_slots == 1, 'never below 1'


def test_a_slot_count_that_can_stall_the_pool_is_reduced_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger='nuqati.db_pool'):
        settings = db_pool.load_pool_settings({'NUQATI_DB_REQUEST_SLOTS': '15'})
    assert settings.request_slots == 14 and 'NUQATI_DB_REQUEST_SLOTS' in caplog.text
    assert db_pool.load_pool_settings({'NUQATI_DB_REQUEST_SLOTS': '14'}).request_slots == 14, 'total - 1 is allowed'


def test_zero_slots_switches_admission_off():
    assert db_pool.load_pool_settings({'NUQATI_DB_REQUEST_SLOTS': '0'}).request_slots == 0


@pytest.mark.parametrize('name,value', [('NUQATI_DB_POOL_SIZE', 'many'), ('NUQATI_DB_POOL_SIZE', '0'), ('NUQATI_DB_POOL_SIZE', '101'),
                                        ('NUQATI_DB_MAX_OVERFLOW', '-1'), ('NUQATI_DB_REQUEST_SLOTS', '1.5'), ('NUQATI_DB_REQUEST_SLOTS', '-3')])
def test_unusable_values_are_ignored_with_a_warning(name, value, caplog):
    with caplog.at_level(logging.WARNING, logger='nuqati.db_pool'):
        settings = db_pool.load_pool_settings({name: value})
    assert (settings.pool_size, settings.max_overflow, settings.request_slots) == (5, 10, 10)
    assert name in caplog.text


def test_empty_values_mean_not_set_so_compose_can_pass_the_variables_through():
    assert db_pool.load_pool_settings({'NUQATI_DB_POOL_SIZE': '', 'NUQATI_DB_MAX_OVERFLOW': ' ', 'NUQATI_DB_REQUEST_SLOTS': ''}) == \
        db_pool.load_pool_settings({})


# ---- admission --------------------------------------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def test_never_more_requests_inside_than_slots_and_all_of_them_finish():
    async def scenario():
        inside = peak = done = 0

        async def request():
            nonlocal inside, peak, done
            async with db_pool.admission(3):
                inside += 1
                peak = max(peak, inside)
                await asyncio.sleep(0.01)
                inside -= 1
                done += 1

        await asyncio.gather(*[request() for _ in range(60)])
        return peak, done

    assert run(scenario()) == (3, 60)


def test_a_failing_request_gives_its_slot_back():
    async def scenario():
        for _ in range(10):
            with pytest.raises(RuntimeError):
                async with db_pool.admission(1):
                    raise RuntimeError('route failed')
        async with db_pool.admission(1):  # would wait forever if a slot had leaked
            return True

    assert run(asyncio.wait_for(scenario(), 5)) is True


def test_waiting_requests_hold_no_thread():
    async def scenario():
        release = asyncio.Event()
        before = threading.active_count()

        async def request():
            async with db_pool.admission(2):
                await release.wait()

        tasks = [asyncio.create_task(request()) for _ in range(200)]
        await asyncio.sleep(0.05)
        during = threading.active_count()
        release.set()
        await asyncio.gather(*tasks)
        return before, during

    before, during = run(scenario())
    assert during == before, '200 waiting requests must not start or occupy any thread'


def test_zero_slots_admits_everything_at_once():
    async def scenario():
        inside = peak = 0

        async def request():
            nonlocal inside, peak
            async with db_pool.admission(0):
                inside += 1
                peak = max(peak, inside)
                await asyncio.sleep(0.01)
                inside -= 1

        await asyncio.gather(*[request() for _ in range(40)])
        return peak

    assert run(scenario()) == 40


def test_each_event_loop_gets_its_own_semaphore():
    async def one(slots):
        async with db_pool.admission(slots):
            return db_pool.admission(slots) is db_pool.admission(slots)

    assert run(one(2)) and run(one(2))  # a second loop must not trip over the first loop's semaphore


def test_changing_the_slot_count_takes_effect():
    async def scenario():
        return db_pool.admission(2) is db_pool.admission(2), db_pool.admission(2) is db_pool.admission(3)

    assert run(scenario()) == (True, False)


# ---- the application really uses it -----------------------------------------------------------------------------------------

def test_get_db_admits_requests_before_it_opens_a_session_and_closes_it_off_the_event_loop():
    tree = ast.parse((APP / 'db.py').read_text(encoding='utf-8'))
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    get_db = functions['get_db']
    assert isinstance(get_db, ast.AsyncFunctionDef), 'get_db must be async so that waiting for a slot holds no thread'
    source = ast.unparse(get_db)
    assert 'admission(POOL.request_slots)' in source
    assert source.index('admission(') < source.index('SessionLocal()'), 'admit first, then open the session'
    assert 'asyncio.shield(asyncio.to_thread(db.close))' in source, 'the close must survive the request being cancelled'
    assert 'run_in_threadpool' not in source, "closing must not need one of the framework's request threads"


def test_the_engine_uses_the_pool_settings_that_the_slots_were_derived_from():
    source = (APP / 'db.py').read_text(encoding='utf-8')
    assert '"pool_size": POOL.pool_size' in source and '"max_overflow": POOL.max_overflow' in source


def test_compose_env_example_and_operations_guide_know_the_settings():
    compose = (ROOT / 'compose.yml').read_text(encoding='utf-8')
    for name in ('NUQATI_DB_POOL_SIZE', 'NUQATI_DB_MAX_OVERFLOW', 'NUQATI_DB_REQUEST_SLOTS'):
        assert f'{name}: ${{{name}:-}}' in compose, f'{name} must be passed through by compose.yml (empty = default)'
        assert name in (ROOT / '.env.example').read_text(encoding='utf-8')
        assert name in (ROOT / 'docs' / 'OPERATIONS.md').read_text(encoding='utf-8')
