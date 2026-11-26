"""The dashboard's Content-Security-Policy and the map frames must not depend on a third-party script host (finding S5)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def policy() -> dict:
    caddyfile = (WEB / "Caddyfile").read_text(encoding="utf-8")
    line = re.search(r'Content-Security-Policy\s+"([^"]+)"', caddyfile)
    assert line, "web/Caddyfile has no Content-Security-Policy"
    directives = {}
    for part in line.group(1).split(";"):
        words = part.split()
        if words:
            directives[words[0]] = words[1:]
    return directives


def test_no_script_host_is_allowed():
    sources = policy()["script-src"]
    assert sources == ["'self'", "'unsafe-inline'"], sources  # inline: the map frames are srcDoc pages; no CDN


def test_styles_allow_only_the_font_stylesheet_host():
    assert policy()["style-src"] == ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]


def test_requests_from_the_page_may_only_go_to_its_own_origin():
    assert policy()["connect-src"] == ["'self'"]  # every fetch uses the same-origin API base ("" in web/Dockerfile)
    assert 'ENV VITE_API_BASE_URL=""' in (WEB / "Dockerfile").read_text(encoding="utf-8")


def test_nothing_in_the_web_app_loads_from_unpkg():
    for path in [WEB / "index.html", *(WEB / "src").rglob("*")]:
        if path.is_file() and path.suffix in {".ts", ".tsx", ".html", ".css"}:
            assert "unpkg.com" not in path.read_text(encoding="utf-8"), f"{path.relative_to(ROOT)} still references unpkg.com"


def test_both_map_frames_use_the_inline_library_and_ci_renders_them():
    for name in ("FleetPositionMap.tsx", "TripLiveMap.tsx"):
        text = (WEB / "src" / name).read_text(encoding="utf-8")
        assert "${leafletStyleTag}" in text and "${leafletScriptTag}" in text, name
        assert "<script src=" not in text and "<link rel=\"stylesheet\"" not in text, f"{name} loads a resource from outside the frame"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "node scripts/check-map-frames.mjs" in ci
