"""iOS project preparation (ops/ios/prepare_ios_project.py), run against the real files `flutter create --platforms=ios` generated
(ops/ios/fixtures/flutter_template_driver, taken from a CI run with Flutter 3.50.1).

No Xcode needed. What the script produces is compiled and started on an iOS simulator by .github/workflows/ci-ios.yml; these tests
pin the details a simulator cannot see (the text Apple reviews, the exact project edits) and that the script refuses a template it does
not understand.
"""
import importlib.util
import plistlib
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "ops" / "ios" / "fixtures" / "flutter_template_driver"

spec = importlib.util.spec_from_file_location("prepare_ios_project", ROOT / "ops" / "ios" / "prepare_ios_project.py")
prepare_ios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_ios)


@pytest.fixture
def project(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "ios")
    return tmp_path


def _read(project, relative):
    return (project / "ios" / relative).read_text(encoding="utf-8")


def _plist(project):
    with (project / "ios" / "Runner" / "Info.plist").open("rb") as handle:
        return plistlib.load(handle)


def test_fixture_is_the_untouched_flutter_template():
    assert "com.example.nuqatiDriver" in (FIXTURE / "Runner.xcodeproj" / "project.pbxproj").read_text()
    assert "FlutterImplicitEngineDelegate" in (FIXTURE / "Runner" / "AppDelegate.swift").read_text()
    assert "NuqatiIOSNativeTracking" not in (FIXTURE / "Runner" / "AppDelegate.swift").read_text()


def test_driver_info_plist(project):
    prepare_ios.prepare("driver", project)
    info = _plist(project)
    assert info["CFBundleDisplayName"] == "Nuqati Driver"
    assert info["ITSAppUsesNonExemptEncryption"] is False
    assert info["UIBackgroundModes"] == ["location", "fetch"]
    # The background-service plugin registers this identifier; iOS 13+ crashes the app at start if it is not listed.
    assert info["BGTaskSchedulerPermittedIdentifiers"] == ["dev.flutter.background.refresh"]
    for key in ("NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription", "NSLocationAlwaysUsageDescription",
                "NSCameraUsageDescription", "NSPhotoLibraryUsageDescription"):
        assert len(info[key]) > 30, key
    assert "UIApplicationSceneManifest" in info, "the template's scene manifest must survive"


def test_bundle_identifiers(project):
    prepare_ios.prepare("driver", project)
    text = _read(project, "Runner.xcodeproj/project.pbxproj")
    assert "com.example" not in text
    ids = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", text)
    assert ids.count("sa.alriadah.nuqati.driver") == 3 and ids.count("sa.alriadah.nuqati.driver.RunnerTests") == 3, ids
    prepare_ios.prepare("driver", project, "sa.example.fleet.driver")
    assert "sa.alriadah.nuqati.driver" not in _read(project, "Runner.xcodeproj/project.pbxproj")


def test_bad_bundle_identifier_is_refused(project):
    for bad in ("nodots", "has space.x", "a;b.c", "com..example"):
        with pytest.raises(SystemExit):
            prepare_ios.prepare("driver", project, bad)


def test_podfile_enables_the_permissions_the_driver_asks_for(project):
    prepare_ios.prepare("driver", project)
    podfile = _read(project, "Podfile")
    assert re.search(r"^platform :ios, '15\.0'$", podfile, re.M), "the Podfile platform follows the project's deployment target"
    for macro in ("PERMISSION_LOCATION=1", "PERMISSION_LOCATION_ALWAYS=1", "PERMISSION_NOTIFICATIONS=1"):
        assert macro in podfile
    # The block sits inside post_install, after the Flutter line, and keeps the Flutter line.
    post_install = podfile[podfile.index("post_install do |installer|"):]
    assert post_install.index("flutter_additional_ios_build_settings(target)") < post_install.index("PERMISSION_LOCATION=1")


def test_app_delegate_installs_the_recorder_under_uiscene(project):
    prepare_ios.prepare("driver", project)
    swift = _read(project, "Runner/AppDelegate.swift")
    assert swift.count("final class NuqatiIOSNativeTracking") == 1
    assert swift.count("@main") == 1
    assert "FlutterImplicitEngineDelegate" in swift
    install = swift[swift.index("didInitializeImplicitFlutterEngine"):]
    assert install.index("GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)") < install.index("NuqatiIOSNativeTracking.shared.install(messenger:")
    # The old way, which does nothing under UIScene, must not come back.
    assert "window?.rootViewController" not in swift


def test_privacy_manifest_is_added_to_the_runner_target(project):
    prepare_ios.prepare("driver", project)
    manifest = project / "ios" / "Runner" / "PrivacyInfo.xcprivacy"
    with manifest.open("rb") as handle:
        data = plistlib.load(handle)
    assert data["NSPrivacyTracking"] is False
    reasons = {item["NSPrivacyAccessedAPIType"]: item["NSPrivacyAccessedAPITypeReasons"] for item in data["NSPrivacyAccessedAPITypes"]}
    assert reasons == {"NSPrivacyAccessedAPICategoryUserDefaults": ["CA92.1"]}
    collected = {item["NSPrivacyCollectedDataType"] for item in data["NSPrivacyCollectedDataTypes"]}
    assert "NSPrivacyCollectedDataTypePreciseLocation" in collected

    pbx = _read(project, "Runner.xcodeproj/project.pbxproj")
    assert pbx.count("PrivacyInfo.xcprivacy") == 6  # build file line (2), file reference line (2), group child (1), resources entry (1)
    assert re.search(r"/\* Resources \*/ = \{\n\t\t\tisa = PBXResourcesBuildPhase;[^}]*?Assets\.xcassets in Resources[^}]*?PrivacyInfo\.xcprivacy in Resources", pbx) or \
        re.search(r"PrivacyInfo\.xcprivacy in Resources \*/,[\s\S]*?Assets\.xcassets in Resources", pbx)
    # Braces and parentheses still balance (a broken project file would only show up on a Mac).
    assert pbx.count("{") == pbx.count("}") and pbx.count("(") == pbx.count(")")
    # The test target's (empty) Resources phase must not have received it.
    tests_phase = re.search(r"331C807F294A63A400263BE5 /\* Resources \*/ = \{[\s\S]*?\n\t\t\};", pbx).group(0)
    assert "PrivacyInfo" not in tests_phase


def test_running_twice_changes_nothing(project):
    prepare_ios.prepare("driver", project)
    first = {p.relative_to(project): p.read_bytes() for p in (project / "ios").rglob("*") if p.is_file()}
    prepare_ios.prepare("driver", project)
    second = {p.relative_to(project): p.read_bytes() for p in (project / "ios").rglob("*") if p.is_file()}
    assert first == second


def test_manager_gets_name_bundle_id_and_nothing_driver_specific(project):
    prepare_ios.prepare("manager", project)
    info = _plist(project)
    assert info["CFBundleDisplayName"] == "Nuqati Manager"
    assert info["ITSAppUsesNonExemptEncryption"] is False
    assert "UIBackgroundModes" not in info and "NSLocationAlwaysUsageDescription" not in info and "BGTaskSchedulerPermittedIdentifiers" not in info
    assert "sa.alriadah.nuqati.manager" in _read(project, "Runner.xcodeproj/project.pbxproj")
    assert "NuqatiIOSNativeTracking" not in _read(project, "Runner/AppDelegate.swift")
    assert not (project / "ios" / "Runner" / "PrivacyInfo.xcprivacy").exists()
    assert "PERMISSION_" not in _read(project, "Podfile")


def test_old_template_without_uiscene_is_refused(project):
    path = project / "ios" / "Runner" / "Info.plist"
    with path.open("rb") as handle:
        data = plistlib.load(handle)
    del data["UIApplicationSceneManifest"]
    with path.open("wb") as handle:
        plistlib.dump(data, handle)
    with pytest.raises(SystemExit, match="UIScene"):
        prepare_ios.prepare("driver", project)


def test_template_changes_fail_loudly(project):
    delegate = project / "ios" / "Runner" / "AppDelegate.swift"
    delegate.write_text(delegate.read_text().replace("FlutterImplicitEngineDelegate", "FlutterPluginRegistrant"))
    with pytest.raises(SystemExit, match="FlutterImplicitEngineDelegate"):
        prepare_ios.prepare("driver", project)


def test_podfile_without_post_install_anchor_is_refused(project):
    podfile = project / "ios" / "Podfile"
    podfile.write_text(podfile.read_text().replace("flutter_additional_ios_build_settings(target)", "# removed"))
    with pytest.raises(SystemExit, match="post_install"):
        prepare_ios.prepare("driver", project)


def test_project_without_a_runner_resources_phase_is_refused(project):
    pbx = project / "ios" / "Runner.xcodeproj" / "project.pbxproj"
    pbx.write_text(pbx.read_text().replace("Assets.xcassets in Resources", "Something in Resources"))
    with pytest.raises(SystemExit, match="Resources phase"):
        prepare_ios.prepare("driver", project)


def test_missing_project_is_explained(tmp_path):
    with pytest.raises(SystemExit, match="flutter create"):
        prepare_ios.prepare("driver", tmp_path)
