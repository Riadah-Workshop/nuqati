"""Contracts for Flutter/native ownership and artifact inclusion."""
from pathlib import Path
try:
    from backend_source import read_backend_source  # the backend code lives in app/features/*.py
except ImportError:  # started as `python -m unittest backend.test_...` from the repository root
    from .backend_source import read_backend_source
ROOT=Path(__file__).resolve().parents[1]

def test_android_builds_copy_handover_dart():
    for f in ['build-android.yml','build-driver-release.yml']:
        text=(ROOT/'.github/workflows'/f).read_text()
        assert 'cp main.dart lib/main.dart' in text
        assert 'cp vehicle_handover.dart lib/vehicle_handover.dart' in text
        assert 'test -s vehicle_handover.dart' in text

def test_online_return_clears_native_recording_owner():
    src=(ROOT/'driver_app/main.dart').read_text()
    native=(ROOT/'driver_app/android_camera_activity/MainActivity.kt').read_text()
    assert "if(v==null){" in src
    assert "invokeMethod('clearRecordingOwner')" in src
    assert "'vehicle_id':v??0" not in src
    assert '"clearRecordingOwner"' in native

def test_driver_can_be_registered_without_preassigning_vehicle():
    backend=read_backend_source()
    web=(ROOT/'web/src/App.tsx').read_text()
    assert 'vehicle_id: int | None = None' in backend
    assert 'vehicle_id:driverVehicle?Number(driverVehicle):null' in web
