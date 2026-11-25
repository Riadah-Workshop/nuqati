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


def _top_level_names(tree):
    """Names bound at module level (also inside top-level if/try), and whether the module is too dynamic to check."""
    names, dynamic = set(), False
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    dynamic = True
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                for child in getattr(node, field, []) or []:
                    stack.extend(child.body if isinstance(child, ast.ExceptHandler) else [child])
    return names, dynamic


def test_every_relative_import_resolves_even_inside_functions():
    """A relative import inside a function runs only when called, so moving a file can break it silently.

    Example: `from .db import SessionLocal` in app/features/x.py means app.features.db, not app.db.
    """
    problems = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.level >= 1):
                continue
            base = path.parent
            for _ in range(node.level - 1):
                base = base.parent
            where = f"{path.relative_to(ROOT)}:{node.lineno}"
            if node.module is None:  # from . import name
                for alias in node.names:
                    if not ((base / f"{alias.name}.py").is_file() or (base / alias.name / "__init__.py").is_file()):
                        problems.append(f"{where} imports '{alias.name}' from {base.relative_to(ROOT)}, which has no such module")
                continue
            target = base.joinpath(*node.module.split("."))
            if target.with_suffix(".py").is_file():
                module_file = target.with_suffix(".py")
            elif (target / "__init__.py").is_file():
                module_file = target / "__init__.py"
            else:
                problems.append(f"{where} imports '{'.' * node.level}{node.module}' but {target.relative_to(ROOT)}.py does not exist")
                continue
            names, dynamic = _top_level_names(ast.parse(module_file.read_text(encoding="utf-8")))
            if dynamic:
                continue
            for alias in node.names:
                submodule = target / f"{alias.name}.py"
                if alias.name not in names and not submodule.is_file():
                    problems.append(f"{where} imports '{alias.name}' which {module_file.relative_to(ROOT)} does not define")
    assert not problems, "Broken relative imports:\n" + "\n".join(problems)


def test_modules_started_by_docker_and_compose_exist():
    """api / teltonika / report_scheduler start `app.<module>`; a missing file makes that container crash-loop."""
    started = {"app.main"}
    for name in ("compose.yml", "docker-compose.yml", "hardware-teltonika.compose.yml", "backend/Dockerfile"):
        path = ROOT / name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for groups in re.findall(r"\"-m\",\s*\"(app\.[\w.]+)\"|-m\s+(app\.[\w.]+)|uvicorn\W+(app\.[\w.]+):", text):
                started |= {module for module in groups if module}
    assert (APP / "__init__.py").is_file(), "backend/app/__init__.py is missing"
    for module in sorted(started):
        relative = Path(*module.split(".")[1:])
        assert (APP / relative).with_suffix(".py").is_file() or (APP / relative / "__init__.py").is_file(), (
            f"{module} is started by Docker/compose but backend/app/{relative}.py is missing")


def test_no_stray_python_modules_in_backend_root():
    """Only tests and test helpers live in backend/; application code belongs in backend/app/."""
    for path in sorted((ROOT / "backend").glob("*.py")):
        assert path.name.startswith("test_") or path.name in {"backend_source.py", "conftest.py"}, (
            f"backend/{path.name} is in the wrong folder: application code goes in backend/app/ (delete this copy)")


if __name__ == "__main__":
    unittest.main()
