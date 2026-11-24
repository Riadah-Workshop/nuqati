"""DB-free deployment contracts for Driver VPN failover and last-seen queues."""
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

ROOT=Path(__file__).resolve().parent.parent


def _heartbeat_model():
    source=ast.parse((ROOT/'backend/app/main.py').read_text())
    cls=next(node for node in source.body if isinstance(node,ast.ClassDef) and node.name=='TrackingHeartbeatIn')
    scope={'BaseModel':BaseModel,'Field':Field,'Literal':Literal,'datetime':datetime}
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<heartbeat contract>','exec'),scope)
    return scope['TrackingHeartbeatIn']


def test_phone_queue_counts_optional_for_old_driver_apps():
    cls=_heartbeat_model()
    values={'screen_state':'unknown','trip_active':False,'captured_at':datetime.now(timezone.utc)}
    old=cls(**values)
    assert old.queued_gps_points is None and old.queued_trips is None
    new=cls(**values,queued_gps_points=100,queued_safety_events=4,queued_trips=2)
    assert (new.queued_gps_points,new.queued_safety_events,new.queued_trips)==(100,4,2)
    with pytest.raises(ValidationError):cls(**values,queued_gps_points=-1)
    with pytest.raises(ValidationError):cls(**values,queued_trips=10000001)


def test_last_reported_queue_stored_server_side_without_location():
    text=(ROOT/'backend/app/main.py').read_text()
    for col in ('queued_gps_points','queued_safety_events','queued_trips'):
        assert f"ADD COLUMN IF NOT EXISTS {{_queue_column}}" in text
        assert f'{col}=EXCLUDED.{col}' in text
        assert col in text[text.index("@app.get('/api/v1/tracking-heartbeats')"):text.index("# Driver alert preferences:")]
    ui=(ROOT/'web/src/App.tsx').read_text()
    assert 'Last reported before communication stopped' in ui
    assert 'Last seen by server' in ui


def test_backup_is_optional_and_never_auto_bypasses_vpn():
    lib=(ROOT/'mobile/nuqati_network.dart').read_text()
    assert "String.fromEnvironment('NUQATI_FALLBACK_API')" in lib
    assert "backup.host.endsWith('.al-riadah.sa')" in lib
    assert 'bindProcessToNetwork' not in lib
    assert '_canRetryPost(uri)' in lib
    assert 'return execute(uri)' in lib  # unsafe POSTs remain primary-only
    workflow=(ROOT/'.github/workflows/build-driver-release.yml').read_text()
    assert '--dart-define=NUQATI_FALLBACK_API="$NUQATI_FALLBACK_API"' in workflow
    assert 'flutter analyze' in workflow


def test_backoff_jitter_never_exceeds_five_minutes():
    source=(ROOT/'mobile/main.dart').read_text()
    assert 'math.min(300,15*(1<<math.min(syncFailureCount-1,5))+math.Random().nextInt(8))' in source
    for count in range(1,9):
        for jitter in range(8):
            assert min(300, 15*(1 << min(count-1,5))+jitter) <= 300
