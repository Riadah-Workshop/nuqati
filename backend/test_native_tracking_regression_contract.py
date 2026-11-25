"""Static/source contract and SQLite migration regression checks for Nuqati native tracking.

Run with: python -m pytest -q backend/test_*.py
These do NOT replace a real Android/Gradle build or an on-device GPS replay.
"""
from pathlib import Path
import sqlite3
try:
    from backend_source import read_backend_source  # the backend code lives in app/features/*.py
except ImportError:  # started as `python -m unittest backend.test_...` from the repository root
    from .backend_source import read_backend_source

ROOT = Path(__file__).resolve().parents[1]
NATIVE = (ROOT/'driver_app/android_native_tracking/NuqatiNativeTrackingService.kt').read_text()
CHANNEL = (ROOT/'driver_app/android_camera_activity/MainActivity.kt').read_text()
DRIVER = (ROOT/'driver_app/main.dart').read_text()
BACKEND = read_backend_source()


def test_sample_interval_is_two_seconds_across_active_and_fallback_paths():
    assert 'const val GPS_SAMPLE_INTERVAL_MS = 2000L' in NATIVE
    assert 'LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, requestedIntervalMs)' in NATIVE
    assert '.setMinUpdateIntervalMillis(GPS_SAMPLE_INTERVAL_MS)' in NATIVE
    assert 'GPS_SAMPLE_INTERVAL_MS, 0f, this, Looper.getMainLooper()' in NATIVE
    assert 'intervalDuration:Duration(seconds:2)' in DRIVER
    assert 'intervalDuration:const Duration(seconds:2)' in DRIVER
    assert 'nativeStatusTimer=Timer.periodic(const Duration(seconds:2)' in DRIVER
    assert 'finally{nativeStatusPolling=false;}' in DRIVER


def test_four_minute_stop_confirmation_preserves_motion_and_gap_safeguards():
    assert 'TRIP_END_DELAY_MS = 240000L' in NATIVE
    assert NATIVE.count('now - stationarySince >= TRIP_END_DELAY_MS') == 2
    assert 'stationaryFixes >= 3' in NATIVE
    assert 'now - lastStationaryFixMs <= 90000L' in NATIVE
    assert 'resetStationaryState()' in NATIVE
    assert 'if(elapsed>=240)unawaited(finishAutomatically())' in DRIVER
    assert "'remaining':(240-elapsed).clamp(0,240)" in DRIVER
    assert '"trip_end_delay_s" to (NuqatiNativeTrackingService.TRIP_END_DELAY_MS/1000L)' in CHANNEL
    assert "final endDelay=(state['trip_end_delay_s'] as num?)?.toInt()??240;" in DRIVER


def test_acceleration_is_measured_and_shared_with_driver_and_gps_queue():
    assert 'private fun validatedAcceleration(fix: Location, prev: Location?): Double?' in NATIVE
    assert 'val accelerationMs2 = validatedAcceleration(location, previousEvent)' in NATIVE
    assert 'db.saveFix(id, location, accelerationMs2)' in NATIVE
    assert 'evaluateSafety(id, location, now, accelerationMs2)' in NATIVE
    assert 'put("acceleration_valid", if (accelerationMs2 != null) 1 else 0)' in NATIVE
    assert '"last_acceleration_valid" to prefs.getBoolean("last_acceleration_valid",false)' in CHANNEL
    assert "accelerationKmhS=id!=null?nativeAcceleration:0.0;" in DRIVER
    assert ')*3.6):0.0' in DRIVER
    assert "fix['acceleration_valid']==1" in DRIVER
    assert "'acceleration_ms2':hasNativeAcceleration" in DRIVER
    assert "'gps_age_seconds':hasNativeGpsAge?" in DRIVER


def test_cornering_still_records_locally_and_notifies_when_enabled():
    assert 'private fun routeCornerAngle(before: Location?, prev: Location, fix: Location)' in NATIVE
    assert 'if (before == null || before.accuracy > 10f' in NATIVE
    assert 'speed >= minimumCorneringKmh' in NATIVE
    assert 'bearingQualified || routeQualified' in NATIVE
    assert 'event(id, "harsh_cornering"' in NATIVE
    assert 'db.saveEvent(id, kind, value, capturedAt, policyVersion)' in NATIVE
    assert NATIVE.index('db.saveEvent(id, kind, value, capturedAt, policyVersion)') < NATIVE.index('notifySafety(kind)', NATIVE.index('private fun event(id: Long'))
    assert "case 'harsh_cornering':co=total;" in DRIVER
    assert "'event_type':event['kind']" in DRIVER


def test_alert_pref_affects_notifications_not_local_persistence():
    assert '"setAlertsEnabled" ->' in CHANNEL
    assert "invokeMethod('setAlertsEnabled',{'enabled':enabled})" in DRIVER
    assert "invokeMethod('setAlertsEnabled',{'enabled':saved!='0'})" in DRIVER
    assert 'prefs.getBoolean("alerts_enabled", true)' in NATIVE
    assert 'Manifest.permission.POST_NOTIFICATIONS' in NATIVE
    assert 'notifications.areNotificationsEnabled()' in NATIVE
    assert 'safety_notification_skipped_permission_or_channel' in NATIVE
    assert 'safety_notification_posted_kind=' in NATIVE


def test_exclusive_severity_and_shared_cooldown():
    assert 'val kind = if (severeNow) "excessive_speeding" else "speeding"' in NATIVE
    assert 'if (!isNewEpisode)' in NATIVE
    assert 'if (now - (lastAlert[group] ?: 0L) < 12000)' in NATIVE
    assert 'enabled("excessive_harsh_braking")' in NATIVE
    assert 'enabled("excessive_harsh_acceleration")' in NATIVE
    assert "DrivingEvent.event_type.in_((base,'excessive_'+base))" in BACKEND


def test_version_five_upgrade_preserves_existing_rows():
    assert 'nuqati_native_tracking.db", null, 5)' in NATIVE
    assert 'if (oldVersion < 5)' in NATIVE
    with sqlite3.connect(':memory:') as db:
        db.executescript('''
            CREATE TABLE trips(id INTEGER PRIMARY KEY,started_ms INTEGER NOT NULL,ended_ms INTEGER,distance_m REAL NOT NULL DEFAULT 0,driver_id INTEGER,company_id INTEGER,vehicle_id INTEGER);
            CREATE TABLE fixes(id INTEGER PRIMARY KEY AUTOINCREMENT,trip_id INTEGER NOT NULL,at_ms INTEGER NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL,accuracy REAL NOT NULL,speed_ms REAL NOT NULL);
            CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,trip_id INTEGER NOT NULL,at_ms INTEGER NOT NULL,kind TEXT NOT NULL,value REAL NOT NULL,policy_version TEXT NOT NULL);
            CREATE TABLE gps_gaps(id INTEGER PRIMARY KEY AUTOINCREMENT,at_ms INTEGER NOT NULL,event TEXT NOT NULL,duration_ms INTEGER NOT NULL,provider TEXT NOT NULL);
            INSERT INTO trips(id,started_ms,driver_id,company_id,vehicle_id) VALUES(11,1000,7,3,5);
            INSERT INTO fixes(id,trip_id,at_ms,lat,lon,accuracy,speed_ms) VALUES(12,11,1100,25.0,50.0,5.0,5.0);
            INSERT INTO events(id,trip_id,at_ms,kind,value,policy_version) VALUES(13,11,1200,'harsh_cornering',3.7,'old-policy');
        ''')
        for sql in (
            'ALTER TABLE fixes ADD COLUMN acceleration_ms2 REAL NOT NULL DEFAULT 0',
            'ALTER TABLE fixes ADD COLUMN acceleration_valid INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE fixes ADD COLUMN gps_age_seconds REAL',
        ):
            assert f'db.execSQL("{sql}")' in NATIVE
            db.execute(sql)
        assert db.execute('SELECT trip_id,acceleration_ms2,acceleration_valid,gps_age_seconds FROM fixes').fetchone() == (11, 0, 0, None)
        assert db.execute('SELECT kind,value FROM events WHERE id=13').fetchone() == ('harsh_cornering', 3.7)
        assert db.execute('SELECT driver_id,company_id,vehicle_id FROM trips WHERE id=11').fetchone() == (7, 3, 5)


def test_no_trip_or_event_deletion_in_native_diagnostics_retention():
    prune = NATIVE.split('fun pruneDiagnostics(olderThanMs: Long)',1)[1].split('fun saveRawFix',1)[0]
    assert 'delete("raw_fixes"' in prune
    assert 'delete("gps_gaps"' in prune
    assert 'DELETE FROM raw_fixes' in prune
    assert 'DELETE FROM gps_gaps' in prune
    assert 'delete("trips"' not in prune
    assert 'delete("fixes"' not in prune
    assert 'delete("events"' not in prune


def test_driver_policy_ack_uses_identical_driver_hash():
    assert 'def driver_mobile_policy_payload(db: Session, driver: Driver):' in BACKEND
    assert 'return driver_mobile_policy_payload(db,own_driver(db,user))' in BACKEND
    assert "expected_version=driver_mobile_policy_payload(db,driver)['policy_version']" in BACKEND
    assert "'status':'received' if ack.get('version')==expected_version else 'pending'" in BACKEND


def test_old_gps_rejections_are_audited_and_do_not_block_future_samples():
    assert "r.body.contains('GPS capture time outside accepted range')" in DRIVER
    assert "await txn.insert('gps_sample_sync_errors'" in DRIVER
    assert "await txn.delete('gps_queue'" in DRIVER
    assert "SYNC_GPS_QUARANTINED status=" in DRIVER
    assert "await txn.insert('safety_event_sync_errors'" not in DRIVER  # safety uses the direct DB insertion path
