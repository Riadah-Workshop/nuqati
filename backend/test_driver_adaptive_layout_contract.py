"""Driver app: layouts that follow the phone (driver_app/nuqati_adaptive.dart, driver_app/main.dart).

No Flutter needed: these read the source and the workflows. The layouts themselves are tested by Flutter in CI:
driver_app/test/adaptive_layout_test.dart renders the score ring and the tiles on 7 screen sizes x 6 system font sizes in English, Arabic
and Urdu (job "Driver app analyze" in ci-flutter.yml). What these tests pin is the wiring around it: that main.dart really uses the
adaptive pieces, that no fixed size has come back, and that every workflow that builds the driver app copies every Dart file main.dart
imports (a missing copy only shows up as a compile error after merge).
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "driver_app"
MAIN = (APP / "main.dart").read_text(encoding="utf-8")
ADAPTIVE = (APP / "nuqati_adaptive.dart").read_text(encoding="utf-8")
LAYOUT_TEST = (APP / "test" / "adaptive_layout_test.dart").read_text(encoding="utf-8")
WORKFLOWS = ROOT / ".github" / "workflows"
DRIVER_BUILDS = ["build-android.yml", "build-driver-release.yml", "build-ios.yml", "ci-flutter.yml"]


def _local_imports():
    return sorted(set(re.findall(r"^import '([a-z_]+\.dart)';", MAIN, re.M)))


def test_every_workflow_copies_every_local_library_main_imports():
    imports = _local_imports()
    assert {"nuqati_network.dart", "nuqati_adaptive.dart", "vehicle_handover.dart"} <= set(imports), imports
    for name in DRIVER_BUILDS:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        # Only real copy commands count (a file name in a comment must not satisfy this).
        copies = "\n".join(line for line in text.splitlines() if re.match(r"\s*(cp |for f in )", line))
        for library in imports:
            assert library in copies, f"{name} does not copy driver_app/{library} into lib/"


def test_main_uses_the_adaptive_pieces():
    assert "import 'nuqati_adaptive.dart';" in MAIN
    assert "builder:nuqatiClampTextScale" in MAIN, "the app must clamp the system font scale at the root"
    assert "NuqatiScoreRing(" in MAIN
    assert MAIN.count("NuqatiEqualGrid(") >= 3, "live metrics, completed-trip metrics and event cards share the equal-height grid"
    assert "NuqatiMetricTile(" in MAIN


def test_no_fixed_pixel_sizes_have_come_back():
    forbidden = {
        "SizedBox(width:154,height:154": "score ring with a fixed size",
        "fontSize:59": "score number with a fixed font size",
        "height:124": "event card with a fixed height",
        "SizedBox(width:94,child:compactMetric": "live metric with a fixed width",
        "SizedBox(width:125,child:compactMetric": "completed-trip metric with a fixed width",
    }
    for needle, why in forbidden.items():
        assert needle not in MAIN, f"main.dart: {why}"
    action = re.search(r"Widget action\(.*", MAIN).group(0)
    assert "minHeight:50" in action and "height:50," not in action.replace("minHeight:50", ""), "buttons grow with their text"


def test_app_bar_title_scales_down_instead_of_overflowing():
    assert "title:FittedBox(fit:BoxFit.scaleDown,alignment:AlignmentDirectional.centerStart,child:Column(" in MAIN


def test_ring_text_is_fitted_to_the_circle_and_independent_of_the_system_font():
    ring = ADAPTIVE[ADAPTIVE.index("class NuqatiScoreRing"): ADAPTIVE.index("class NuqatiMetricTile")]
    assert "FittedBox(" in ring and "BoxFit.scaleDown" in ring
    assert ring.count("TextScaler.noScaling") == 2, "number and word follow the ring, not the system font"
    assert "nuqatiRingDiameter(available)" in ring
    # The text box must stay inside the free circle: (w)^2 + (h)^2 < 1 for the fractions of its diameter.
    width, height = (float(x) for x in re.search(r"boxWidth = inner \* ([\d.]+);\s*final boxHeight = inner \* ([\d.]+);", ring).groups())
    assert width ** 2 + height ** 2 < 1.0, (width, height)


def test_tiles_have_no_fixed_height_and_rows_share_a_height():
    tile = ADAPTIVE[ADAPTIVE.index("class NuqatiMetricTile"): ADAPTIVE.index("class NuqatiEqualGrid")]
    assert "minHeight" in tile and not re.search(r"(?<!min)[hH]eight: *\d", tile.replace("SizedBox(height:", "")), "tiles only have a minimum height"
    grid = ADAPTIVE[ADAPTIVE.index("class NuqatiEqualGrid"):]
    assert "IntrinsicHeight(" in grid and "CrossAxisAlignment.stretch" in grid


def test_text_scale_limits():
    assert re.search(r"const double nuqatiMaxTextScale = 1\.35;", ADAPTIVE)
    assert re.search(r"const double nuqatiMinTextScale = 0\.85;", ADAPTIVE)
    assert "media.textScaler.clamp(minScaleFactor: nuqatiMinTextScale, maxScaleFactor: nuqatiMaxTextScale)" in ADAPTIVE


def test_layout_test_covers_small_phones_big_fonts_three_languages_and_has_a_control():
    widths = [int(w) for w in re.findall(r"Size\((\d+), \d+\)", LAYOUT_TEST.split("const fontScales")[0])]
    assert min(widths) <= 280 and max(widths) >= 600, widths
    scales = [float(x) for x in re.search(r"const fontScales = <double>\[([^\]]+)\]", LAYOUT_TEST).group(1).split(",")]
    assert min(scales) <= 0.85 and max(scales) >= 2.0, scales
    for language in ("'en':", "'ar':", "'ur':", "'long':"):
        assert language in LAYOUT_TEST
    assert "the old fixed-height tile overflows at font 2.0" in LAYOUT_TEST, "the control must stay: it proves the checks can fail"
    assert "tiles of one row have different heights" in LAYOUT_TEST
    assert "leaves the free circle" in LAYOUT_TEST


def test_ci_runs_the_layout_test():
    ci = (WORKFLOWS / "ci-flutter.yml").read_text(encoding="utf-8")
    assert "flutter test --no-pub test/adaptive_layout_test.dart" in ci
    assert "lib/nuqati_adaptive.dart test/adaptive_layout_test.dart" in ci
    # Generating the Flutter project creates test/widget_test.dart (it refers to MyApp); it must be removed before the tests run.
    assert ci.index("rm -f test/widget_test.dart") < ci.index("flutter test --no-pub")
