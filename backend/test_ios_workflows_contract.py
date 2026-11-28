"""iOS build, CI and release plumbing (.github/workflows/{ci,build,release}-ios.yml, .github/actions/ios-project, the smoke tests).

No Mac needed: these read the files. The workflows themselves run on macOS in GitHub Actions; ci-ios.yml starts both apps on an iOS
simulator for every pull request that can affect iOS. release-ios.yml needs the Apple account (docs/IOS.md) and has not run yet.
"""
import re
import struct
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION = ROOT / ".github" / "actions" / "ios-project" / "action.yml"


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def _workflow(name):
    return yaml.safe_load(_text(WORKFLOWS / name))


def test_ios_files_are_valid_yaml_and_the_action_is_composite():
    for name in ("ci-ios.yml", "build-ios.yml", "release-ios.yml"):
        assert "jobs" in _workflow(name), name
    action = yaml.safe_load(_text(ACTION))
    assert action["runs"]["using"] == "composite"
    assert all(step.get("shell") == "bash" for step in action["runs"]["steps"] if "run" in step), "composite steps need an explicit shell"


def test_every_ios_workflow_uses_the_shared_project_preparation():
    for name in ("ci-ios.yml", "build-ios.yml", "release-ios.yml"):
        assert "uses: ./.github/actions/ios-project" in _text(WORKFLOWS / name), name
        # The old per-workflow patching (the AppDelegate that does nothing under UIScene) must not return.
        assert "ios_native_tracking/AppDelegate.swift > ios/Runner/AppDelegate.swift" not in _text(WORKFLOWS / name)
    action = _text(ACTION)
    assert "ops/ios/prepare_ios_project.py" in action
    assert "nuqati_icon_ios.png" in action and "remove_alpha_ios: true" in action


def test_ci_starts_both_apps_on_a_simulator_for_changes_that_can_affect_ios():
    ci = _workflow("ci-ios.yml")
    paths = ci[True]["pull_request"]["paths"]
    for needed in ("driver_app/**", "manager_app/**", "ops/ios/**", ".github/actions/ios-project/**", ".github/workflows/ci-ios.yml"):
        assert needed in paths, needed
    job = ci["jobs"]["ios"]
    assert job["runs-on"].startswith("macos")
    assert sorted(job["strategy"]["matrix"]["app"]) == ["driver", "manager"]
    assert job["strategy"]["fail-fast"] is False
    text = _text(WORKFLOWS / "ci-ios.yml")
    assert "xcrun simctl boot" in text and "xcrun simctl bootstatus" in text
    assert "flutter test integration_test/ios_smoke_test.dart" in text.replace(">", "").replace("\n", " ") or "integration_test/ios_smoke_test.dart" in text


def test_smoke_tests_check_what_a_compile_cannot():
    driver = _text(ROOT / "driver_app" / "integration_test" / "ios_smoke_test.dart")
    for needle in ("nuqati/native_tracking", "isPowerSaveMode", "'status'", "getRecords", "serviceStatus", "FlutterSecureStorage",
                   "Iqama / Saudi ID number", "package:nuqati_driver/main.dart"):
        assert needle in driver, needle
    manager = _text(ROOT / "manager_app" / "integration_test" / "ios_smoke_test.dart")
    for needle in ("FlutterSecureStorage", "Company Admin Sign In", "package:nuqati_manager/main.dart"):
        assert needle in manager, needle
    # The texts the smoke tests wait for must still be on the screens.
    assert "Iqama / Saudi ID number" in _text(ROOT / "driver_app" / "main.dart")
    assert "title('Company Admin Sign In'" in _text(ROOT / "manager_app" / "main.dart")
    # The channel name and methods the Swift recorder serves are the ones the test calls.
    swift = _text(ROOT / "driver_app" / "ios_native_tracking" / "NuqatiIOSNativeTracking.swift")
    for method in ("isPowerSaveMode", "status", "getRecords"):
        assert f'case "{method}"' in swift, method
    assert 'FlutterMethodChannel(name: "nuqati/native_tracking"' in swift


def test_integration_test_package_is_a_dev_dependency_of_both_apps():
    for app in ("driver_app", "manager_app"):
        pubspec = yaml.safe_load(_text(ROOT / app / "pubspec.yaml"))
        assert pubspec["dev_dependencies"]["integration_test"] == {"sdk": "flutter"}, app
        assert "integration_test" not in pubspec["dependencies"]


def test_unsigned_build_offers_both_apps():
    build = _workflow("build-ios.yml")
    inputs = build[True]["workflow_dispatch"]["inputs"]["app"]
    assert inputs["options"] == ["driver", "manager"]
    text = _text(WORKFLOWS / "build-ios.yml")
    assert "--no-codesign" in text and "--simulator" in text
    assert "NOT an installable IPA" in text


def test_release_needs_the_apple_account_and_keeps_nothing_in_the_public_repo():
    text = _text(WORKFLOWS / "release-ios.yml")
    for secret in ("APPLE_TEAM_ID", "APPSTORE_KEY_ID", "APPSTORE_ISSUER_ID", "APPSTORE_API_KEY_P8"):
        assert f"secrets.{secret}" in text, secret
        assert f"Missing GitHub secrets" in text
    # No IPA or archive may leave the runner: the repository is public.
    for forbidden in ("upload-artifact", "gh release", "softprops", "actions/cache"):
        assert forbidden not in text, forbidden
    # The key must never be echoed or traced, and must be deleted at the end even when the build fails.
    assert "set -x" not in text and "xcodebuild -verbose" not in text and "echo \"$API_KEY_P8\"" not in text
    last = yaml.safe_load(text)["jobs"]["testflight"]["steps"][-1]
    assert last["if"] == "always()" and "rm -f" in last["run"] and "AuthKey_" in last["run"]
    # Apple requires a higher build number for every upload: the run number of this workflow.
    assert '--build-number="${{ github.run_number }}"' in text
    # Upload goes straight to App Store Connect with automatic signing through the API key.
    assert "<key>destination</key><string>upload</string>" in text
    assert "<key>method</key><string>app-store-connect</string>" in text
    assert text.count("-allowProvisioningUpdates") == 2 and text.count("-authenticationKeyIssuerID") == 2
    assert "permissions:\n      contents: read" in text


def test_ios_builds_get_the_same_build_settings_as_android():
    for name in ("build-ios.yml", "release-ios.yml"):
        text = _text(WORKFLOWS / name)
        assert "secrets.MAPTILER_API_KEY" in text and "vars.NUQATI_FALLBACK_API" in text, name
        assert "--dart-define=MAPTILER_API_KEY=" in text and "--dart-define=NUQATI_FALLBACK_API=" in text, name
    release = _text(WORKFLOWS / "release-ios.yml")
    assert 'if [ "$APP" = manager ] && [ -z "$MAPTILER_API_KEY" ]' in release, "the manager release must stop early without the map key"
    assert "vars.NUQATI_PRODUCTION_API" in release


def test_ios_icons_are_square_1024_and_opaque():
    for app in ("driver_app", "manager_app"):
        data = (ROOT / app / "assets" / "nuqati_icon_ios.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height, depth, color_type = struct.unpack(">IIBB", data[16:26])
        assert (width, height) == (1024, 1024), app
        assert color_type == 2, f"{app}: colour type {color_type}; Apple rejects icons with an alpha channel (2 = RGB)"
        assert b"tRNS" not in data, app
    assert (ROOT / "driver_app" / "assets" / "nuqati_icon_ios.png").read_bytes() == (ROOT / "manager_app" / "assets" / "nuqati_icon_ios.png").read_bytes()


def test_the_ios_code_paths_that_must_not_run_on_ios_are_guarded():
    main = _text(ROOT / "driver_app" / "main.dart")
    update = main[main.index("Future<void> checkForAppUpdate() async {"):]
    assert update.split("\n", 1)[1].lstrip().startswith("if(!Platform.isAndroid"), "Google Play in-app updates must stay Android-only"
    # Battery-optimisation prompts are Android-only too.
    for match in re.finditer(r"ph\.Permission\.ignoreBatteryOptimizations\.request\(\)", main):
        line_start = main.rfind("\n", 0, match.start()) + 1
        assert "Platform.isAndroid" in main[line_start:match.end()], "battery optimisation request must be Android-only"
