#!/usr/bin/env python3
"""Turns a freshly generated `flutter create --platforms=ios` project into the Nuqati driver or manager iOS project.

The repository keeps only the Dart sources and the Swift recorder (see driver_app/README.md); CI generates the Xcode project. Every
iOS workflow (CI, unsigned builds, TestFlight release) calls this one script, through .github/actions/ios-project, so they cannot drift.

    python3 ops/ios/prepare_ios_project.py --app driver --project-dir driver_app [--bundle-id sa.alriadah.nuqati.driver]

What it does, and why:
  * Info.plist: the app name, the location / camera usage texts Apple shows and reviews, the background modes, the background-task id the
    background-service plugin registers (without it iOS 13+ crashes the app at start), and ITSAppUsesNonExemptEncryption=false (the apps
    use only standard HTTPS, which avoids an export-compliance question on every upload).
  * Bundle identifier of the app and its test target.
  * Podfile: the permission_handler macros. Without them every iOS permission check silently answers "denied".
  * Driver only: AppDelegate.swift = the CoreLocation recorder + the UIScene-style app delegate that installs it, and a privacy manifest
    (PrivacyInfo.xcprivacy) added to the Runner target (required by Apple for the UserDefaults use of the recorder).
It stops with an error if the generated project does not look the way it expects, so a Flutter template change fails the build loudly
instead of producing an app that starts but does not track.
"""
from __future__ import annotations

import argparse
import plistlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# flutter_background_service_ios registers this BGTaskScheduler identifier; it must be listed in Info.plist.
BACKGROUND_TASK_ID = "dev.flutter.background.refresh"

APPS = {
    "driver": {"display_name": "Nuqati Driver", "bundle_id": "sa.alriadah.nuqati.driver"},
    "manager": {"display_name": "Nuqati Manager", "bundle_id": "sa.alriadah.nuqati.manager"},
}

DRIVER_INFO = {
    "NSLocationWhenInUseUsageDescription": "Nuqati uses your location to detect driving trips and calculate safety events.",
    "NSLocationAlwaysAndWhenInUseUsageDescription": (
        "Nuqati records fleet driving trips while the screen is locked or the app is in the background. "
        "Tracking can be paused only with approved Privacy Mode."
    ),
    "NSLocationAlwaysUsageDescription": "Nuqati requires Always location access for automatic fleet trip monitoring.",
    "NSCameraUsageDescription": "Capture vehicle inspection evidence for online handover and return.",
    "NSPhotoLibraryUsageDescription": "Attach vehicle inspection photos during an online handover.",
    "UIBackgroundModes": ["location", "fetch"],
    "BGTaskSchedulerPermittedIdentifiers": [BACKGROUND_TASK_ID],
}

PERMISSION_MACROS = [
    "PERMISSION_LOCATION=1",
    "PERMISSION_LOCATION_ALWAYS=1",
    "PERMISSION_LOCATION_WHENINUSE=1",
    "PERMISSION_NOTIFICATIONS=1",
]

PRIVACY_FILE = "PrivacyInfo.xcprivacy"


class ProjectError(SystemExit):
    def __init__(self, message: str):
        super().__init__(f"prepare_ios_project: {message}")


def patch_info_plist(path: Path, app: str, display_name: str) -> None:
    with path.open("rb") as handle:
        data = plistlib.load(handle)
    if "UIApplicationSceneManifest" not in data:
        raise ProjectError(
            "Info.plist has no UIApplicationSceneManifest: this Flutter is older than 3.41 (UIScene). The app delegate and the iOS "
            "workflows are written for the UIScene template; use a current Flutter stable."
        )
    data["CFBundleDisplayName"] = display_name
    data["ITSAppUsesNonExemptEncryption"] = False
    if app == "driver":
        data.update(DRIVER_INFO)
    with path.open("wb") as handle:
        plistlib.dump(data, handle)


def deployment_target(pbxproj: str) -> str:
    found = set(re.findall(r"IPHONEOS_DEPLOYMENT_TARGET = ([\d.]+);", pbxproj))
    if len(found) != 1:
        raise ProjectError(f"expected one iOS deployment target in the project, found {sorted(found)}")
    return found.pop()


def patch_bundle_id(pbxproj: str, bundle_id: str) -> str:
    def swap(match: re.Match) -> str:
        suffix = ".RunnerTests" if match.group(1).endswith(".RunnerTests") else ""
        return f"PRODUCT_BUNDLE_IDENTIFIER = {bundle_id}{suffix};"

    patched, count = re.subn(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", swap, pbxproj)
    if count < 4:
        raise ProjectError(f"expected the bundle identifier of the app and its tests in the project, replaced only {count}")
    return patched


def patch_podfile(text: str, app: str, target: str) -> str:
    text, count = re.subn(r"^#\s*platform :ios, '[\d.]+'", f"platform :ios, '{target}'", text, count=1, flags=re.M)
    if count == 0 and f"platform :ios, '{target}'" not in text:
        raise ProjectError("Podfile has no 'platform :ios' line to set")
    if app != "driver" or "PERMISSION_LOCATION=1" in text:
        return text
    anchor = "flutter_additional_ios_build_settings(target)"
    if anchor not in text:
        raise ProjectError("Podfile has no post_install block with flutter_additional_ios_build_settings(target)")
    macros = ",\n".join(f"        '{macro}'" for macro in PERMISSION_MACROS)
    block = (
        f"{anchor}\n\n"
        "    # permission_handler only includes the permissions listed here; without them every check answers \"denied\".\n"
        "    target.build_configurations.each do |config|\n"
        "      config.build_settings['GCC_PREPROCESSOR_DEFINITIONS'] ||= [\n"
        "        '$(inherited)',\n"
        f"{macros}\n"
        "      ]\n"
        "    end"
    )
    return text.replace(anchor, block, 1)


def write_app_delegate(ios_dir: Path) -> None:
    target = ios_dir / "Runner" / "AppDelegate.swift"
    generated = target.read_text(encoding="utf-8")
    recorder = (ROOT / "driver_app" / "ios_native_tracking" / "NuqatiIOSNativeTracking.swift").read_text(encoding="utf-8")
    delegate = (ROOT / "driver_app" / "ios_native_tracking" / "AppDelegate.swift").read_text(encoding="utf-8")
    if "final class NuqatiIOSNativeTracking" in generated:
        return  # already prepared
    if "FlutterImplicitEngineDelegate" not in generated:
        raise ProjectError("the generated AppDelegate.swift is not the UIScene template (no FlutterImplicitEngineDelegate)")
    for needle in ("didInitializeImplicitFlutterEngine", "NuqatiIOSNativeTracking.shared.install", "@main"):
        if needle not in delegate:
            raise ProjectError(f"driver_app/ios_native_tracking/AppDelegate.swift lost '{needle}'")
    # One file, so no Xcode project registration is needed (AppDelegate.swift is already in the Runner target).
    target.write_text(recorder.rstrip("\n") + "\n\n" + delegate, encoding="utf-8")


def register_privacy_manifest(ios_dir: Path) -> None:
    runner = ios_dir / "Runner"
    (runner / PRIVACY_FILE).write_text((HERE / "PrivacyInfo.driver.xcprivacy").read_text(encoding="utf-8"), encoding="utf-8")
    project = ios_dir / "Runner.xcodeproj" / "project.pbxproj"
    text = project.read_text(encoding="utf-8")
    if PRIVACY_FILE in text:
        return
    file_ref, build_file = "7A1C0DE0A0B1C2D3E4F50001", "7A1C0DE0A0B1C2D3E4F50002"
    if file_ref in text or build_file in text:
        raise ProjectError("internal ids already used in the project")

    def insert(pattern: str, replacement: str, what: str, flags: int = 0) -> None:
        nonlocal text
        text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
        if count != 1:
            raise ProjectError(f"could not add the privacy manifest to the Xcode project: {what} not found")

    insert(r"(/\* Begin PBXBuildFile section \*/\n)",
           rf"\1\t\t{build_file} /* {PRIVACY_FILE} in Resources */ = {{isa = PBXBuildFile; fileRef = {file_ref} /* {PRIVACY_FILE} */; }};\n",
           "PBXBuildFile section")
    insert(r"(/\* Begin PBXFileReference section \*/\n)",
           rf"\1\t\t{file_ref} /* {PRIVACY_FILE} */ = {{isa = PBXFileReference; lastKnownFileType = text.xml; path = {PRIVACY_FILE}; sourceTree = \"<group>\"; }};\n",
           "PBXFileReference section")
    insert(r"(/\* Runner \*/ = \{\s*isa = PBXGroup;\s*children = \(\n)",
           rf"\1\t\t\t\t{file_ref} /* {PRIVACY_FILE} */,\n", "Runner group")
    # The Resources phase of the Runner target is the one that already holds Assets.xcassets.
    phases = list(re.finditer(r"\t\t[0-9A-F]{24} /\* Resources \*/ = \{\n\t\t\tisa = PBXResourcesBuildPhase;[\s\S]*?\n\t\t\};\n", text))
    runner_phase = [m for m in phases if "Assets.xcassets in Resources" in m.group(0)]
    if len(runner_phase) != 1:
        raise ProjectError("could not add the privacy manifest to the Xcode project: Runner Resources phase not found")
    block = runner_phase[0].group(0)
    new_block = block.replace("files = (\n", f"files = (\n\t\t\t\t{build_file} /* {PRIVACY_FILE} in Resources */,\n", 1)
    text = text.replace(block, new_block, 1)
    project.write_text(text, encoding="utf-8")


def prepare(app: str, project_dir: Path, bundle_id: str | None = None) -> None:
    ios_dir = project_dir / "ios"
    config = APPS[app]
    bundle_id = bundle_id or config["bundle_id"]
    if not re.fullmatch(r"[A-Za-z0-9]+([.-][A-Za-z0-9]+)+", bundle_id):
        raise ProjectError(f"'{bundle_id}' is not a valid bundle identifier")
    for needed in ("Runner/Info.plist", "Runner/AppDelegate.swift", "Runner.xcodeproj/project.pbxproj", "Podfile"):
        if not (ios_dir / needed).is_file():
            raise ProjectError(f"{ios_dir / needed} is missing: run `flutter create --platforms=ios` first")

    patch_info_plist(ios_dir / "Runner" / "Info.plist", app, config["display_name"])
    project = ios_dir / "Runner.xcodeproj" / "project.pbxproj"
    pbxproj = project.read_text(encoding="utf-8")
    target = deployment_target(pbxproj)
    project.write_text(patch_bundle_id(pbxproj, bundle_id), encoding="utf-8")
    podfile = ios_dir / "Podfile"
    podfile.write_text(patch_podfile(podfile.read_text(encoding="utf-8"), app, target), encoding="utf-8")
    if app == "driver":
        write_app_delegate(ios_dir)
        register_privacy_manifest(ios_dir)
    print(f"prepared the {app} iOS project: bundle id {bundle_id}, iOS {target}+")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", choices=sorted(APPS), required=True)
    parser.add_argument("--project-dir", type=Path, required=True, help="the Flutter project (driver_app or manager_app)")
    parser.add_argument("--bundle-id", help="overrides the default bundle identifier")
    args = parser.parse_args(argv)
    prepare(args.app, args.project_dir, args.bundle_id or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
