"""Driver app: Google Play in-app updates (driver_app/main.dart, driver_app/pubspec.yaml).

No Flutter needed: these read the Dart source, and run the small decision function (nuqatiUpdateChoice) through a literal translation
to Python so the table of cases below is checked against the real Dart code. What Play itself does cannot be tested here: it only
works on a copy installed from Play (internal testing track or later); see docs/OPERATIONS.md section 12. The Dart is compiled by the
"Driver app analyze" job.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DART = (ROOT / "driver_app" / "main.dart").read_text(encoding="utf-8")
PUBSPEC = (ROOT / "driver_app" / "pubspec.yaml").read_text(encoding="utf-8")


def _block(start_marker, end_marker):
    start = DART.index(start_marker)
    return DART[start: DART.index(end_marker, start)]


CHECK = _block("Future<void> checkForAppUpdate() async {", "// Listens (only once a flexible update has been started)")
RESTART = _block("Future<void> restartForUpdate() async {", "@override void didChangeAppLifecycleState")


def _choice():
    """The Dart nuqatiUpdateChoice, translated line by line (it only uses && || ! ?: and null)."""
    constants = {name: int(value) for name, value in re.findall(r"const int (nuqati\w+)=(\d+);", DART)}
    body = _block("String nuqatiUpdateChoice(", "\n}\n").split("}){", 1)[1]
    lines = [line.strip() for line in body.strip().split("\n") if line.strip()]
    python = ["def choice(available, immediateAllowed, flexibleAllowed, priority, staleDays):"]
    for line in lines:
        line = line.rstrip(";")
        line = line.replace("final ", "").replace("&&", " and ").replace("||", " or ").replace("!=null", " is not None")
        line = re.sub(r"if\(!(\w+)\)", r"if not \1:", line)
        line = re.sub(r"^if\((.*)\)return (.*)$", r"if \1: return \2", line)
        line = re.sub(r"^return (\w+)\?('[a-z]+'):('[a-z]+')$", r"return \2 if \1 else \3", line)
        python.append("    " + line)
    scope = dict(constants)
    exec("\n".join(python), scope)
    return scope["choice"]


def test_decision_table():
    choose = _choice()

    def case(**overrides):
        values = dict(available=True, immediateAllowed=True, flexibleAllowed=True, priority=0, staleDays=0)
        values.update(overrides)
        return choose(**values)

    assert case(available=False) == "none"
    assert case() == "flexible", "an ordinary new build downloads in the background"
    assert case(staleDays=None) == "flexible"
    assert case(priority=3, staleDays=6) == "flexible"
    assert case(priority=4) == "immediate", "an urgent build (priority 4 or 5) is installed with Play's blocking screen"
    assert case(priority=5) == "immediate"
    assert case(staleDays=7) == "immediate", "a build the phone has known about for a week is no longer optional"
    assert case(priority=5, immediateAllowed=False) == "flexible", "if Play says immediate is not possible, fall back"
    assert case(flexibleAllowed=False) == "none"
    assert case(priority=5, immediateAllowed=False, flexibleAllowed=False) == "none"
    assert re.search(r"const Duration nuqatiUpdateCheckEvery=Duration\(hours:6\);", DART)


def test_never_interrupts_a_trip():
    first = CHECK.split("\n")[1]
    assert "tripId!=null" in first and "Platform.isAndroid" in first and "token.isEmpty" in first, first
    # a trip can start while Play is answering: look again before anything is shown
    assert CHECK.index("checkForUpdate()") < CHECK.index("if(!mounted||tripId!=null)return;") < CHECK.index("startFlexibleUpdate()")
    assert CHECK.index("if(!mounted||tripId!=null)return;") < CHECK.index("performImmediateUpdate()")
    assert "tripId!=null)return;" in RESTART.split("\n")[1], "the restart button does nothing during a trip"
    assert "if(updateReady&&tripId==null)panel(" in DART, "the banner is hidden during a trip"


def test_checks_are_throttled_and_never_crash_the_app():
    assert "nuqatiUpdateCheckEvery" in CHECK and "nuqatiUpdateAskAgainAfterDenial" in CHECK
    assert "updateChecking=true;" in CHECK and "updateChecking=false;" in CHECK
    assert re.search(r"\}catch\(e\)\{", CHECK) and "finally{" in CHECK, "a Play error (sideloaded copy, no Play services) is caught"
    # only a short sanitised error code is logged, never the message, and only once per start
    assert "RegExp(r'[^A-Za-z0-9_\\-]')" in CHECK and "updateUnavailableLogged" in CHECK
    assert not re.search(r"(?<![\w.])e\.(toString\(\)|message)|\$e\b|\$\{e\}", CHECK), "the error text itself is never logged"


def test_every_play_call_is_android_only_and_in_the_three_update_functions():
    calls = re.findall(r"InAppUpdate\.(\w+)", DART)
    assert set(calls) <= {"checkForUpdate", "performImmediateUpdate", "startFlexibleUpdate", "completeFlexibleUpdate", "installUpdateListener"}, calls
    assert "Platform.isAndroid" in CHECK
    watch = _block("void watchAppUpdateDownload(){", "// The banner's button.")
    assert "installUpdateListener" in watch and "watchAppUpdateDownload();" in CHECK, "the listener starts only when a flexible update is started"
    for name in ("checkForUpdate", "performImmediateUpdate", "startFlexibleUpdate"):
        assert f"InAppUpdate.{name}()" in CHECK
    assert "InAppUpdate.completeFlexibleUpdate()" in RESTART


def test_started_and_stopped_with_the_screen():
    assert re.search(r"in_app_update: \^\d+\.\d+\.\d+", PUBSPEC)
    assert "import 'package:in_app_update/in_app_update.dart';" in DART
    init = _block("@override void initState(){", "\n")
    assert "updateTimer=Timer.periodic(const Duration(minutes:2)" in init and "checkForAppUpdate" in init
    dispose = _block("@override void dispose(){", "\n")
    assert "updateTimer?.cancel();" in dispose and "updateStatusSub?.cancel();" in dispose
    assert "checkForAppUpdate" in _block("@override void didChangeAppLifecycleState", "@override void dispose(){")


def test_banner_is_in_all_three_languages_and_diagnostics_fit_the_backend():
    for english in ("A new version of Nuqati is ready", "Restart to update"):
        assert re.search(rf"tr\('{english}','[^']*[؀-ۿ][^']*'\)", DART), f"Arabic text for {english!r}"
        assert re.search(rf"'{english}':'[^']*[؀-ۿ][^']*'", DART), f"Urdu text for {english!r}"
    codes = set(re.findall(r"'(APP_UPDATE_[A-Z_]+)", DART))
    assert {"APP_UPDATE_AVAILABLE", "APP_UPDATE_DECLINED", "APP_UPDATE_DOWNLOADED", "APP_UPDATE_RESTARTING",
            "APP_UPDATE_FAILED", "APP_UPDATE_UNAVAILABLE"} <= codes, codes
    diagnostics = (ROOT / "backend" / "app" / "features" / "diagnostics.py").read_text(encoding="utf-8")
    rule = re.search(r"code: str = Field\(min_length=2,max_length=(\d+),pattern=r'([^']+)'\)", diagnostics)
    assert rule and all(len(c) <= int(rule.group(1)) and re.match(rule.group(2), c) for c in codes)
    upload = _block("Future<void> nuqatiUploadDiagnostics() async {", "\n}\n")
    assert "code.startsWith('APP_UPDATE_')" in upload, "the detail (choice, version code, priority) is uploaded"
    assert "code.contains('FAILED')" in upload, "APP_UPDATE_FAILED is an ERROR in App Diagnostics"
