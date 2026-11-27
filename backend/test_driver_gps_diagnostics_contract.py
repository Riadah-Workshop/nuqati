"""Driver-app diagnostics for GPS gaps (driver_app/main.dart): the false alarm is gone and the phone's own timeline is uploaded.

No Flutter needed: these read the Dart source. They guard three things that were found in a real diagnostics log:
  * GPS_MONITOR_STALE_FIX repeated every 45 seconds once native tracking was primary (a false alarm of the legacy monitor);
  * the native recorder's timeline (GPS silence, phone suspension, service restarts) stayed on the phone, so a hole in a trip
    could not be explained from the platform;
  * what is uploaded must stay location-free: only numbers, true/false and fixed words may be copied out of the native text.
The Dart code itself is compiled by the "Driver app analyze" job (ci-flutter.yml).
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DART = (ROOT / "driver_app" / "main.dart").read_text(encoding="utf-8")


def _function(name):
    """Source text of a top-level Dart function: from its signature to the next top-level declaration."""
    start = re.search(r"^[A-Za-z<>?\[\], ]+ " + re.escape(name) + r"\(", DART, flags=re.M)
    assert start, name
    end = re.search(r"\n\S", DART[start.end():])
    return DART[start.start(): start.end() + (end.start() if end else len(DART))]


def test_stale_monitor_does_not_cry_wolf_when_native_tracking_is_primary():
    timer = DART[DART.index("Timer.periodic(const Duration(seconds:45)"):]
    timer = timer[: timer.index("Timer.periodic(const Duration(seconds:20)")]
    guard = timer.index("await secure.read(key:'nuqati_native_primary')=='1')return;")
    assert guard < timer.index("nuqatiLog('GPS_MONITOR_STALE_FIX')"), "the native-primary check must come before the stale-fix log"
    assert guard < timer.index("final stale=lastMonitorFixReceivedAt"), "and before the stale calculation"


def test_native_timeline_is_copied_into_the_uploaded_diagnostics():
    upload = _function("nuqatiUploadDiagnostics")
    assert "await nuqatiImportNativeGapEvents();" in upload
    assert upload.index("nuqatiImportNativeGapEvents") < upload.index("readAsLines"), "import first, then read the log tail"
    importer = _function("nuqatiImportNativeGapEvents")
    assert "nuqati_native_tracking.db" in importer and "readOnly:true" in importer
    assert "'gps_gaps'" in importer and "native_import_cursor" in importer
    # lines first, cursor second: a crash in between repeats lines, which the server drops by hash
    assert importer.index("nuqatiLogAt(") < importer.index("target.insert('native_import_cursor'")
    # the log line carries the time the event really happened, not the time of the copy
    assert "isUtc:true" in importer and "row['at_ms']" in importer
    assert "catch(_)" in importer, "best effort: a failure here must never disturb tracking"
    batch = int(re.search(r"const int nuqatiGapImportBatch=(\d+);", DART).group(1))
    assert 0 < batch <= 90, "the upload sends the last 100 lines per minute and the server accepts at most 100 events"
    assert "nuqatiLogAt(DateTime at" in DART


def test_only_numbers_and_fixed_words_leave_the_phone():
    mapper = _function("nuqatiNativeGapLine")
    assert "$event" not in mapper and "event.substring" not in mapper and "event.split" not in mapper, "never copy native text through"
    for forbidden in ("latitude", "longitude", "zone", "geofence", "account", "message", "privacy_blocked", "quarantined"):
        assert forbidden not in mapper, forbidden
    # the noisy heartbeat lines are not uploaded
    assert "watchdog_alive" not in mapper and "fused_callback_received" not in mapper
    upload = _function("nuqatiUploadDiagnostics")
    assert "code.startsWith('GPS_NATIVE_')" in upload and "code.startsWith('TRIP_NATIVE_')" in upload


def test_codes_fit_what_the_backend_accepts():
    mapper = _function("nuqatiNativeGapLine")
    codes = set(re.findall(r"'((?:GPS|TRIP)_NATIVE_[A-Z_]+)'", mapper))
    assert {"GPS_NATIVE_SUSPENDED", "GPS_NATIVE_GAP_STARTED", "GPS_NATIVE_GAP_ENDED", "GPS_NATIVE_SCREEN_ON",
            "GPS_NATIVE_SERVICE_DESTROYED", "TRIP_NATIVE_START_BLOCKED"} <= codes, codes
    diagnostics = (ROOT / "backend" / "app" / "features" / "diagnostics.py").read_text(encoding="utf-8")
    pattern = re.search(r"code: str = Field\(min_length=2,max_length=(\d+),pattern=r'([^']+)'\)", diagnostics)
    assert pattern, "the backend code rule changed: update this test and the Dart codes together"
    for code in codes:
        assert len(code) <= int(pattern.group(1)) and re.match(pattern.group(2), code), code
    # the upload derives the category from the code: GPS_* -> GPS, TRIP_* -> TRIP (both are allowed categories)
    assert "category: Literal['GPS','TRIP'," in diagnostics
    upload = _function("nuqatiUploadDiagnostics")
    for word in ("GAP_STARTED", "SUSPENDED", "DESTROYED"):
        assert f"code.contains('{word}')" in upload, f"{word} must be a WARNING"
