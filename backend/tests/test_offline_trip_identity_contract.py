"""Regression guardrails for the offline recording ownership contract.
Run: python -m unittest discover -s backend/tests -p 'test_offline_trip_identity_contract.py'
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

class OfflineIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = (ROOT/'backend/app/main.py').read_text()
        cls.flutter = (ROOT/'mobile/main.dart').read_text()
        cls.native = (ROOT/'mobile/android_native_tracking/NuqatiNativeTrackingService.kt').read_text()

    def test_backend_rejects_other_driver_and_company(self):
        self.assertIn('payload.recorded_driver_id!=d.id', self.backend)
        self.assertIn('payload.recorded_company_id!=d.company_id', self.backend)
        self.assertIn('Recorded trip owner does not match', self.backend)

    def test_backend_rejects_vehicle_mismatch_and_client_id_collision(self):
        self.assertIn('v.id!=payload.recorded_vehicle_id', self.backend)
        self.assertIn('client_trip_id=:c AND driver_id<>:d', self.backend)

    def test_legacy_unowned_trips_not_selected_for_sync(self):
        self.assertIn("where:'driver_id=? AND company_id=? AND vehicle_id IS NOT NULL'", self.flutter)
        self.assertIn('Unowned historical trip quarantined', self.flutter)

    def test_native_trip_ownership_is_durable(self):
        self.assertIn('put("driver_id",driver)', self.native)
        self.assertIn('put("company_id",company)', self.native)
        self.assertIn('put("vehicle_id",vehicle)', self.native)
        self.assertIn('previous_account_trip_quarantined', self.native)

if __name__ == '__main__': unittest.main()
