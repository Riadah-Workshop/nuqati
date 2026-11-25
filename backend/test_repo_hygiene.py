"""Repository-layout guards. Pure standard library (plus PyYAML, which uvicorn[standard] installs).

These tests exist because of mistakes this repo has already made once:
  * workflows pointing at folders that were renamed or never existed
  * the Docker build context missing a file the Dockerfile COPYs (Coolify failure, 2026-11-14)
  * patch notes and ZIP drops cluttering the repository root
  * bytecode / keystores / .env files committed by accident
They are cheap and never touch a database.
"""
import ast
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_MARKDOWN_ALLOWED = {"README.md", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md", "LICENSE.md", "CODE_OF_CONDUCT.md"}
FORBIDDEN_TRACKED = re.compile(
    r"(^|/)(__pycache__/|\.env($|\.(?!example$))|[^/]*\.(pyc|pyo|jks|keystore|p12|pem|apk|aab|ipa|sqlite3?|db)$)"
)
PRIVATE_KEY = re.compile("-----BEGIN " + r"(?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY" + "-----")


def _yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise unittest.SkipTest("PyYAML not installed") from exc
    return yaml


def _tracked_files():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise unittest.SkipTest("not a git checkout") from exc
    return [f for f in out.splitlines() if f]


def _load(path):
    return _yaml().safe_load(path.read_text(encoding="utf-8"))


def test_no_bytecode_keystores_env_files_or_databases_are_tracked():
    bad = [f for f in _tracked_files() if FORBIDDEN_TRACKED.search(f)]
    assert not bad, f"Files that must never be committed are tracked: {bad}"


def test_no_private_key_material_is_tracked():
    hits = []
    for f in _tracked_files():
        p = ROOT / f
        if p.is_file() and p.stat().st_size < 1_000_000:
            if PRIVATE_KEY.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(f)
    assert not hits, f"Private key material found in: {hits}"


def test_legacy_app_folders_are_gone_and_new_ones_exist():
    # People used to drop ZIP contents into mobile/ and manager/. Those paths no longer exist.
    for legacy in ("mobile", "manager"):
        assert not (ROOT / legacy).exists(), (
            f"'{legacy}/' reappeared. The apps now live in driver_app/ and manager_app/; "
            "move the files there instead.")
    for app in ("driver_app", "manager_app"):
        assert (ROOT / app / "pubspec.yaml").is_file(), f"{app}/pubspec.yaml is missing"
        assert (ROOT / app / "main.dart").is_file(), f"{app}/main.dart is missing"


def test_repository_root_has_no_patch_notes():
    extra = sorted(p.name for p in ROOT.glob("*.md") if p.name not in ROOT_MARKDOWN_ALLOWED)
    assert not extra, (
        f"Move these into docs/ (or docs/history/ for patch notes): {extra}. "
        f"Only {sorted(ROOT_MARKDOWN_ALLOWED)} may live in the repository root.")


def test_workflow_directories_and_path_filters_exist():
    problems = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        doc = _load(wf)
        triggers = doc.get("on", doc.get(True)) or {}  # PyYAML reads the key `on` as boolean True
        for event in ("push", "pull_request"):
            cfg = triggers.get(event) if isinstance(triggers, dict) else None
            for pattern in (cfg or {}).get("paths", []) or []:
                folder = pattern.split("/**")[0].lstrip("!")
                if "/" in pattern and not (ROOT / folder).exists():
                    problems.append(f"{wf.name}: path filter '{pattern}' -> '{folder}' does not exist")
        default_dir = (doc.get("defaults") or {}).get("run", {}).get("working-directory")
        dirs = {default_dir} if default_dir else set()
        for job in (doc.get("jobs") or {}).values():
            dirs.add(((job.get("defaults") or {}).get("run") or {}).get("working-directory"))
            for step in job.get("steps", []) or []:
                dirs.add(step.get("working-directory"))
        for d in dirs - {None}:
            if "${{" not in d and not (ROOT / d).is_dir():
                problems.append(f"{wf.name}: working-directory '{d}' does not exist")
    assert not problems, "\n".join(problems)


def test_compose_files_point_at_existing_build_inputs():
    problems = []
    for name in ("compose.yml", "docker-compose.yml", "hardware-teltonika.compose.yml"):
        doc = _load(ROOT / name)
        for svc, cfg in (doc.get("services") or {}).items():
            build = cfg.get("build")
            if build:
                context = build if isinstance(build, str) else build.get("context", ".")
                dockerfile = "Dockerfile" if isinstance(build, str) else build.get("dockerfile", "Dockerfile")
                if not (ROOT / context).is_dir():
                    problems.append(f"{name}:{svc}: build context '{context}' missing")
                elif not (ROOT / context / dockerfile).is_file():
                    problems.append(f"{name}:{svc}: Dockerfile '{context}/{dockerfile}' missing")
            command = cfg.get("command")
            if isinstance(command, list) and command[:2] == ["python", "-m"]:
                module = command[2].replace(".", "/") + ".py"
                if not (ROOT / "backend" / module).is_file():
                    problems.append(f"{name}:{svc}: command module '{command[2]}' not found under backend/")
    assert not problems, "\n".join(problems)


def test_dockerignore_keeps_every_file_the_backend_dockerfile_copies():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    sources = re.findall(r"^COPY\s+(?:--\S+\s+)*(\S+)\s+\S+", dockerfile, flags=re.M)
    assert sources, "backend/Dockerfile has no COPY lines?"
    for src in sources:
        assert (ROOT / src).exists(), f"backend/Dockerfile COPYs '{src}' which does not exist"
    ignore = ROOT / ".dockerignore"
    assert ignore.is_file(), ".dockerignore is missing (it was once committed under the name 'download')"
    lines = {l.strip() for l in ignore.read_text(encoding="utf-8").splitlines()}
    for needed in ("!backend/Dockerfile", "!backend/requirements.txt", "!backend/app/", "!backend/app/**"):
        assert needed in lines, f".dockerignore must re-include '{needed}' or the Coolify build breaks"


def test_test_requirements_cover_test_only_imports():
    text = (ROOT / "backend" / "requirements-test.txt").read_text(encoding="utf-8").lower()
    for package in ("pytest", "httpx", "pillow"):
        assert package in text, f"backend/requirements-test.txt must list {package}"


APP = ROOT / "backend" / "app"


def test_main_py_only_assembles_the_api():
    """app/main.py registers modules in order; code, routes and SQL live in api_app.py and features/."""
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        assert not isinstance(node, (ast.FunctionDef, ast.ClassDef)), (
            f"app/main.py defines {node.name}: put code in a module under app/features/")
        assert not isinstance(node, ast.With), (
            "app/main.py runs SQL at import time: put it in the feature module that owns the table")


def test_every_feature_module_with_routes_is_registered_in_main():
    """A route module that main.py never imports silently serves nothing."""
    main = (APP / "main.py").read_text(encoding="utf-8")
    registered = set(re.findall(r"^from \.features import (\w+)", main, flags=re.M))
    for path in sorted((APP / "features").glob("*.py")):
        if path.stem == "__init__":
            continue
        has_routes = re.search(r"^@app\.", path.read_text(encoding="utf-8"), flags=re.M)
        if has_routes:
            assert path.stem in registered, (
                f"app/features/{path.name} defines routes but app/main.py does not import it "
                f"(add 'from .features import {path.stem}' in the right place)")
    for name in registered:
        assert (APP / "features" / f"{name}.py").is_file(), f"main.py imports missing module features/{name}.py"


def test_feature_modules_take_app_from_api_app_not_from_main():
    """main.py imports the features, so a feature importing main would be a circular import."""
    for path in sorted((APP / "features").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from \.\.main import|from \.main import|import app\.main)", text, flags=re.M), (
            f"{path.name} imports main.py; use 'from ..api_app import app' instead")


def test_names_other_modules_import_from_main_are_still_exported_by_main():
    """report_subscriptions does `from .main import ...` at call time; main.py must keep binding those names."""
    tree = ast.parse((APP / "main.py").read_text(encoding="utf-8"))
    bound = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.Assign):
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    wanted = {}
    for path in sorted(APP.glob("*.py")):
        if path.name == "main.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "main":
                for alias in node.names:
                    wanted.setdefault(alias.name, path.name)
    assert wanted, "expected report_subscriptions.py to import from .main; update this test if that was removed"
    for name, user in wanted.items():
        assert name in bound, f"{user} imports '{name}' from .main but main.py no longer exports it"


if __name__ == "__main__":
    unittest.main()
