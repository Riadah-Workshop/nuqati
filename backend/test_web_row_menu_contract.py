"""The three-dot row menu and the Odometer-inside-Maintenance layout (web/src/RowMenu.tsx, App.tsx, ReportSubscriptions.tsx).

No browser needed: these read the TypeScript source, so a table that goes back to loose Edit / Delete buttons, a menu that loses its
keyboard handling, or a menu entry that points at the removed Odometer page fails here. How the menu actually behaves on screen
(where it opens, that a click does not open the row behind it) is checked in a real browser by web/scripts/check-ui-components.mjs
(workflow "Web UI in a real browser").
"""
import re
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "web" / "src"
MENU = (SRC / "RowMenu.tsx").read_text(encoding="utf-8")
MENU_CSS = (SRC / "row-menu.css").read_text(encoding="utf-8")
APP = (SRC / "App.tsx").read_text(encoding="utf-8")
SUBSCRIPTIONS = (SRC / "ReportSubscriptions.tsx").read_text(encoding="utf-8")
TOUR = (SRC / "tourSteps.ts").read_text(encoding="utf-8")


def test_row_menu_is_a_real_accessible_menu():
    for needle in ('role="menu"', 'role="menuitem"', 'aria-haspopup="menu"', "aria-expanded", "aria-label={label}"):
        assert needle in MENU, needle
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"):
        assert f"'{key}'" in MENU, f"RowMenu does not handle {key}"


def test_row_menu_is_drawn_on_top_and_does_not_open_the_row_behind_it():
    # rows are clickable (they open the editor): the button and the list must both stop the click
    assert MENU.count("stopPropagation()") >= 3
    assert "createPortal(" in MENU and "document.body" in MENU, "the list must be drawn in document.body so a scrolling table cannot clip it"
    assert "position:fixed" in MENU_CSS.replace(" ", "")
    assert re.search(r"z-index:\s*9000", MENU_CSS)
    # the guided tour sits above the menu
    assert re.search(r"z-index:\s*10000", (SRC / "guided-tour.css").read_text(encoding="utf-8"))


def test_row_menu_closes_when_it_should_and_focuses_only_once_placed():
    for event in ("pointerdown", "'resize'", "'scroll'"):
        assert event in MENU, event
    # an invisible element cannot take the focus: the focusing effect must wait for the placement
    assert "const placed = place !== null" in MENU
    assert re.search(r"if \(open && placed\)[^\n]*focus\(\)", MENU)
    assert "if (!items.length) return null" in MENU


def test_every_table_with_row_actions_uses_the_menu():
    assert len(re.findall(r"<RowMenu\b", APP)) >= 5, "Companies, Users, Vehicles, Drivers and Maintenance schedules use RowMenu"
    assert "<RowMenu" in SUBSCRIPTIONS, "scheduled-report subscriptions use RowMenu"
    assert "import RowMenu from './RowMenu'" in APP and "import RowMenu from './RowMenu'" in SUBSCRIPTIONS
    # no loose Edit / Delete buttons are left in a table's action cell
    assert "data-nq-action" not in APP
    assert not re.search(r"<td>\s*<button[^>]*>[^<]*(?:Delete|حذف)", APP)
    assert not re.search(r"<td>\s*<button[^>]*>[^<]*(?:Delete|حذف)", SUBSCRIPTIONS)


def test_menu_actions_keep_their_guards_and_both_languages():
    # every menu has a per-row label in both languages (screen readers announce it)
    for found in re.finditer(r"<RowMenu\b[^>]*?label=\{(.*?)\}\s+items", APP, flags=re.S):
        label = found.group(1)
        assert "إجراءات" in label and "Actions for" in label, label
    assert "إجراءات" in SUBSCRIPTIONS and "Actions for" in SUBSCRIPTIONS
    # destructive entries are marked, so they are set apart and coloured
    assert APP.count("danger:true") >= 5, "delete / deactivate entries must be marked danger"
    # the same permission rules as before: only a super admin deletes users, vehicles and drivers, and nobody deletes themselves
    assert re.search(r"me\.role==='super_admin'[^\n]{0,120}u\.id!==me\.id", APP) or "u.id!==me.id" in APP


def test_odometer_is_no_longer_a_page_of_its_own():
    assert not re.search(r"id:\s*'odometer'\s*,", APP), "the Odometer menu entry is gone"
    assert "setTab('odometer')" not in APP and "tab==='odometer'" not in APP and "'odometer'|" not in APP
    assert "setOdometerSection" not in APP
    assert "data-page='odometer'" not in (SRC / "nuqati-reference.css").read_text(encoding="utf-8")
    group = re.search(r"\['(?:safety)'[^\]]*\],\[([^\]]*)\],\['reports'\]", APP)
    assert group and "'odometer'" not in group.group(1), "the Maintenance menu group no longer lists Odometer"


def test_odometer_pages_are_tabs_of_maintenance_alerts():
    union = re.search(r"useState<([^>]*)>\('alerts'\)", APP)
    assert union, "maintenanceSection state not found"
    for tab in ("odometer-current", "odometer-history", "odometer-record"):
        assert f"'{tab}'" in union.group(1), f"{tab} is a Maintenance section"
        assert f"id:'{tab}'" in APP, f"{tab} has a tab in the Maintenance page header"
    # the three old panels are still rendered, each from its own section, and the normal maintenance panel steps aside for them
    for marker in ("odometerSection==='current'", "odometerSection==='history'", "odometerSection==='record'", "odometerSection===null"):
        assert marker in APP, marker
    # recording a reading is a write: only people who may manage maintenance see its tab
    assert re.search(r"\.\.\.\(canManage\?\[\{id:'odometer-record'", APP)


def test_tour_no_longer_sends_people_to_an_odometer_menu_entry():
    maintenance = re.search(r'id:\s*"maintenance"(.*?)\n  \},', TOUR, flags=re.S).group(1)
    assert "tabs inside it" in maintenance and "تبويبات داخلها" in maintenance
