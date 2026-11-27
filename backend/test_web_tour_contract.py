"""The first-login tour (web/src/tourSteps.ts, GuidedTour.tsx, App.tsx) holds together.

No browser needed: the step list is plain data, so a missing translation, a step that points at an element that no longer
exists, or a role that is not a real role fails here instead of showing a broken tour to a new user.
"""
import re
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "web" / "src"
STEPS = (SRC / "tourSteps.ts").read_text(encoding="utf-8")
APP = (SRC / "App.tsx").read_text(encoding="utf-8")
# read from the source, so this test needs neither a database driver nor the web framework
ROLES = set(re.findall(r"\"([a-z_]+)\"", re.search(r"ROLES = \{(.*?)\}", (Path(__file__).resolve().parent / "app" / "auth.py").read_text(encoding="utf-8")).group(1)))
ARABIC = re.compile(r"[؀-ۿ]")

# One entry per `{ id: "...", ... },` block of TOUR_STEPS.
BLOCKS = re.findall(r"\{\s*id:\s*\"([a-z-]+)\"(.*?)\n  \},", STEPS, flags=re.S)


def _field(block, name, language):
    found = re.search(name + r":\s*\{\s*en:\s*\"(.*?)\",\s*ar:\s*\"(.*?)\",?\s*\}", block, flags=re.S)
    assert found, f"missing {name} in one step"
    return found.group(1 if language == "en" else 2)


def test_the_step_list_is_parsed_and_has_the_expected_shape():
    ids = [step_id for step_id, _ in BLOCKS]
    assert len(ids) >= 8, ids
    assert len(ids) == len(set(ids)), "step ids must be unique"
    assert ids[0] == "welcome"


def test_every_step_has_a_title_and_text_in_both_languages():
    for step_id, block in BLOCKS:
        for name in ("title", "body"):
            english, arabic = _field(block, name, "en"), _field(block, name, "ar")
            assert english.strip() and not ARABIC.search(english), (step_id, name, "English text is empty or contains Arabic")
            assert ARABIC.search(arabic), (step_id, name, "Arabic text is missing")
            assert "undefined" not in english + arabic


def test_every_target_is_an_element_of_the_page():
    targets = set(re.findall(r"target:\s*\"([a-z-]+)\"", STEPS))
    assert targets, "no targets found"
    groups = set(re.findall(r"'(nav-[a-z]+)'", APP))
    plain = set(re.findall(r"data-tour=\"([a-z-]+)\"", APP))
    missing = sorted(t for t in targets if t not in groups | plain)
    assert not missing, f"tour targets that no element carries: {missing}"


def test_menu_group_targets_follow_the_menu_order():
    # the six groups of the side menu; the tour finds them by position, so the list and the menu must stay in step
    assert re.search(r"TOUR_NAV_GROUPS=\['nav-home','nav-fleet','nav-safety','nav-maintenance','nav-reports','nav-admin'\] as const", APP)
    menu = re.search(r"\(\[\['overview'\],\['companies'.*?\] as const\)\.map\(\(ids,index\)", APP, flags=re.S)
    assert menu and menu.group(0).count("],[") + 1 == 6, "the side menu no longer has six groups"


def test_roles_named_by_steps_are_real_roles():
    used = set(re.findall(r"\"((?:super_admin|company_admin|fleet_manager|workshop_staff|representative|driver))\"", STEPS))
    named = set(re.findall(r"roles:\s*\[([^\]]*)\]", STEPS))
    assert used <= ROLES
    # an alias such as ADMINS must itself be made only of real roles
    for alias in re.findall(r"const ([A-Z_]+) = \[([^\]]*)\]", STEPS):
        assert set(re.findall(r"\"([a-z_]+)\"", alias[1])) <= ROLES, alias
    assert named, "no step is limited to a role: the tour would be identical for everyone"


def test_the_tour_is_remembered_per_user_and_can_be_replayed():
    assert "tourSeen(me.id)" in APP and "markTourSeen(me.id)" in APP
    assert "data-tour=\"tour-replay\"" in APP and "setTourOpen(true)" in APP
    assert "<GuidedTour" in APP
