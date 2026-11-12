"""Static regression checks for native safety counts and driver-scoped trip numbering.
These checks do not replace Android integration or real PostgreSQL transaction tests.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SafetyAndNumberingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = (ROOT/'mobile/android_native_tracking/NuqatiNativeTrackingService.kt').read_text()
        cls.flutter = (ROOT/'mobile/main.dart').read_text()
        cls.backend = (ROOT/'backend/app/main.py').read_text()

    def test_speeding_warning_has_immediate_countable_event(self):
        self.assertIn('val kind = if (severeNow) "excessive_speeding" else "speeding"', self.native)
        self.assertLess(self.native.index('db.saveEvent(id, kind, speed'), self.native.index('notifySafety(kind)'))
        self.assertIn('if (!isNewEpisode)', self.native)
        self.assertIn("kind.endsWith('_session')?0", self.flutter)

    def test_native_counters_do_not_wait_for_upload(self):
        self.assertIn('SELECT kind AS event_type, COUNT(*) AS total FROM events WHERE trip_id=?', self.flutter)
        self.assertIn('if(Platform.isAndroid && id>=nuqatiNativeIdOffset)', self.flutter)
        self.assertIn('minimumCorneringKmh', self.native)
        self.assertIn('val cached = loadPolicy()', self.native)

    def test_event_upload_follows_all_gps_points(self):
        before = self.flutter.index('SYNC_EVENTS_WAIT_FOR_GPS')
        after = self.flutter.index('// All available GPS anchors are committed; now upload local safety events.')
        self.assertLess(before, after)
        self.assertIn('if(outstandingGps>0)', self.flutter)
        self.assertIn(".order_by(func.abs(func.extract('epoch',DriverLocation.recorded_at-captured))", self.backend)

    def test_backend_owns_driver_scoped_number(self):
        self.assertIn('UNIQUE (company_id, driver_id, trip_number)', self.backend)
        self.assertIn('ROW_NUMBER() OVER (PARTITION BY company_id, driver_id ORDER BY id)', self.backend)
        self.assertIn('db.scalar(select(Driver).where(Driver.id==d.id).with_for_update())', self.backend)
        self.assertIn('trip_number=trip_number_for(db,trip)', self.backend)
        self.assertIn("'next_trip_number':int(last_number)+1", self.backend)
        self.assertIn('payload.recorded_driver_id!=d.id', self.backend)
        self.assertIn("'trip_number':allocated", self.flutter)

    def test_official_score_only_completed_but_live_counts_all(self):
        self.assertIn('official_events=[e for e in events if e.trip_id in completed_trip_ids]', self.backend)
        self.assertIn('counts={k:sum(', self.backend)

if __name__ == '__main__':
    unittest.main()
