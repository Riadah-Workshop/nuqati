"""Alembic migration framework: checks that need neither Alembic nor a database.

The checks that need PostgreSQL (the baseline builds the same schema as the application's own start-up code, an
existing database is adopted without changes, a database that lacks something is refused, the container starts with
migrations on) run in CI, job "Migrations" in .github/workflows/ci.yml.
"""
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"
VERSIONS = APP / "migrations" / "versions"
BASELINE_SHA256 = "8004be26f60cc77fdbd69a3b074f33c04a725d64d560594ee80b810d86f233c7"

# Since Phase 3.4 the application does not create or change tables by itself: every table, column and index is an
# Alembic revision (python -m app.migrate new "what changes"; docs/DEVELOPMENT.md section 6).
DDL = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\b|\bALTER\s+TABLE\b|\bcreate_all\(", re.I)


def revision_files():
    return sorted(VERSIONS.glob("*.py"))


def read_revision(path):
    text = path.read_text(encoding="utf-8")
    found = {}
    for name in ("revision", "down_revision"):
        match = re.search(rf"^{name}\s*=\s*(None|\"[^\"]*\"|'[^']*')\s*$", text, re.M)
        assert match, f"{path.name} has no plain `{name} = ...` line"
        raw = match.group(1)
        found[name] = None if raw == "None" else raw.strip("\"'")
    return found


def test_application_code_does_not_create_or_change_tables():
    found = []
    for path in sorted(APP.rglob("*.py")):
        relative = path.relative_to(APP).as_posix()
        if relative.startswith("migrations/") or relative == "migrate.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DDL.search(line):
                found.append(f"backend/app/{relative}:{number}: {line.strip()[:90]}")
    assert not found, (
        "Schema statements in application code. New tables, columns and indexes are Alembic revisions: "
        "python -m app.migrate new \"what changes\" (docs/DEVELOPMENT.md section 6).\n" + "\n".join(found))


def test_released_revisions_are_never_edited():
    # An edited baseline would no longer match the databases that were adopted at revision 0001.
    digest = hashlib.sha256((VERSIONS / "0001_baseline.sql").read_bytes()).hexdigest()
    assert digest == BASELINE_SHA256, (
        "0001_baseline.sql changed. Never edit a released revision: add a new one (python -m app.migrate new ...).")


def test_integration_tests_build_their_schema_with_migrations():
    for name in ("test_auth_runtime_postgres.py", "test_security_audit_postgres.py", "test_mfa_postgres.py"):
        text = (ROOT / "backend" / name).read_text(encoding="utf-8")
        assert "migrate.main(['upgrade']) == 0" in text, f"{name} must run the migrations before importing the application"
        assert text.index("migrate.main") < text.index("from app.main import app"), f"{name}: migrate before importing app.main"


def test_revisions_form_one_unbroken_chain_starting_at_the_baseline():
    files = revision_files()
    assert files, "backend/app/migrations/versions has no revision"
    revisions = {}
    for path in files:
        data = read_revision(path)
        assert path.name.startswith(data["revision"] + "_"), f"{path.name} must start with its revision id '{data['revision']}_'"
        assert data["revision"] not in revisions, f"revision {data['revision']} appears twice"
        revisions[data["revision"]] = data["down_revision"]
    assert revisions.get("0001") is None and "0001" in revisions, "0001 must be the baseline (down_revision = None)"
    assert list(revisions).count("0001") == 1
    roots = [r for r, down in revisions.items() if down is None]
    assert roots == ["0001"], f"exactly one revision may have down_revision None, found {roots}"
    parents = [down for down in revisions.values() if down is not None]
    for down in parents:
        assert down in revisions, f"a revision points at {down}, which does not exist"
    assert len(parents) == len(set(parents)), "two revisions share a parent (a fork): merge them into one chain"
    numbers = sorted(int(r) for r in revisions)
    assert numbers == list(range(1, len(numbers) + 1)), f"revision numbers must be 0001, 0002, ... without gaps, found {numbers}"


def test_baseline_sql_is_a_reduced_schema_dump():
    sql = (VERSIONS / "0001_baseline.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE public.companies" in sql, "the baseline must create the companies table"
    assert sql.count("CREATE TABLE public.") >= 40
    for forbidden in ("alembic_version", "set_config", "OWNER TO"):
        assert forbidden not in sql, f"0001_baseline.sql must not contain '{forbidden}'"
    for statement in ("SET", "COPY", "GRANT", "REVOKE", "COMMENT ON", "INSERT INTO", "CREATE SCHEMA", "CREATE EXTENSION"):
        assert not re.search(rf"^\s*{re.escape(statement)}(\s|$)", sql, re.M), f"0001_baseline.sql must not contain a '{statement}' statement"
    assert not re.search(r"^\s*--", sql, re.M), "0001_baseline.sql must not contain comments"
    assert "ANY ((ARRAY[" not in sql, "pg_dump's form of IN (...) on varchar does not round-trip: write the predicate as IN (...) (see uq_handover_open_*)"
    assert not re.search(r"^\s*\\", sql, re.M), "0001_baseline.sql must not contain psql meta-commands (pg_dump 16.x adds \\restrict lines)"
    # migrate.py rebuilds the baseline in a scratch schema by replacing "public." everywhere: nothing may be unqualified.
    names = re.findall(r"^(?:CREATE (?:UNLOGGED )?(?:TABLE|SEQUENCE|VIEW)|ALTER (?:TABLE|SEQUENCE)(?: ONLY)?)\s+(\S+)", sql, re.M)
    assert names, "no CREATE/ALTER statements found"
    assert all(name.startswith("public.") for name in names), f"unqualified object names: {[n for n in names if not n.startswith('public.')][:5]}"


def test_baseline_revision_reads_the_sql_file_and_cannot_be_undone():
    text = (VERSIONS / "0001_baseline.py").read_text(encoding="utf-8")
    assert "0001_baseline.sql" in text
    assert "def downgrade" in text and "raise" in text.split("def downgrade", 1)[1]
    assert (VERSIONS / "0001_baseline.sql").is_file()


def test_migration_environment_is_online_only_and_uses_the_application_engine():
    env = (APP / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "from app.db import engine" in env
    assert "is_offline_mode" in env and "raise" in env.split("is_offline_mode", 1)[1].split("\n", 2)[1]
    assert (APP / "migrations" / "script.py.mako").is_file()
    mako = (APP / "migrations" / "script.py.mako").read_text(encoding="utf-8")
    for marker in ("${up_revision}", "${repr(down_revision)}", "def upgrade", "def downgrade"):
        assert marker in mako


def test_migrations_are_inside_the_docker_build_context():
    # .dockerignore only re-includes backend/app/**: revisions and the SQL file must live there.
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!backend/app/**" in ignore
    assert VERSIONS.relative_to(ROOT).as_posix().startswith("backend/app/")
    assert "COPY backend/app ./app" in (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")


def test_alembic_is_a_runtime_requirement():
    assert re.search(r"^alembic>=1\.\d+,<2\s*$", (ROOT / "backend" / "requirements.in").read_text(encoding="utf-8"), re.M)


def test_container_migrates_by_default_and_stops_on_failure():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    cmd = re.search(r"^CMD\s+(.+)$", dockerfile, re.M).group(1)
    assert "NUQATI_RUN_MIGRATIONS:-1" in cmd, "migrations are on unless NUQATI_RUN_MIGRATIONS=0 (the application no longer creates tables)"
    assert "python -m app.migrate || exit 1" in cmd, "a failed migration must stop the container"
    assert cmd.index("python -m app.migrate") < cmd.index("exec uvicorn"), "migrate before the API starts"
    assert "exec uvicorn app.main:app --host 0.0.0.0 --port 8000" in cmd, "exec keeps uvicorn as PID 1 so it receives the stop signal"
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
    api = compose.split("\n  api:", 1)[1].split("\n  teltonika", 1)[0]
    assert "NUQATI_RUN_MIGRATIONS: ${NUQATI_RUN_MIGRATIONS:-1}" in api
    assert "NUQATI_RUN_MIGRATIONS" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_compare_columns_reports_only_what_the_baseline_needs():
    from app import migrate

    expected = {("a", "id"): ("integer", "NO"), ("a", "name"): ("text", "YES"), ("b", "id"): ("integer", "NO")}
    assert migrate.compare_columns(expected, dict(expected)) == []
    extra = {**expected, ("a", "added_later"): ("text", "YES"), ("c", "id"): ("integer", "NO")}
    assert migrate.compare_columns(expected, extra) == [], "extra tables and columns in the database are fine"
    missing_column = {k: v for k, v in expected.items() if k != ("a", "name")}
    assert migrate.compare_columns(expected, missing_column) == ["column a.name is missing"]
    missing_table = {k: v for k, v in expected.items() if k[0] != "b"}
    assert migrate.compare_columns(expected, missing_table) == ["table b is missing"], "a missing table is one line, not one per column"
    wrong = {**expected, ("a", "name"): ("character varying", "NO")}
    (message,) = migrate.compare_columns(expected, wrong)
    assert "a.name" in message and "character varying NOT NULL" in message and "text NULL" in message


def test_next_revision_number_counts_on_from_the_highest():
    from app import migrate

    assert migrate.next_revision_number([]) == 1
    assert migrate.next_revision_number(["0001"]) == 2
    assert migrate.next_revision_number(["0001", "0007", "0003"]) == 8
    assert migrate.next_revision_number(["0001", "abc123"]) == 2, "hash-style ids are ignored"


@pytest.mark.parametrize("argv", [["bogus"], ["new"], ["new", "  "], ["upgrade", "extra"], ["status", "extra"], ["new", "a", "b"]])
def test_bad_command_lines_exit_2_before_touching_anything(argv, capsys):
    from app import migrate

    assert migrate.main(argv) == 2
    assert "usage" in capsys.readouterr().err


def test_migrate_module_imports_without_alembic_or_a_database():
    # Heavy imports are lazy so that `python -m app.migrate new ...` and these tests work anywhere.
    text = (APP / "migrate.py").read_text(encoding="utf-8")
    top_level = [line for line in text.splitlines() if re.match(r"(import|from)\s", line)]
    assert not any("alembic" in line or "sqlalchemy" in line or "db import" in line for line in top_level)


def test_adoption_refuses_before_stamping_when_the_database_lacks_baseline_objects():
    text = (APP / "migrate.py").read_text(encoding="utf-8")
    run = text.split("def run_upgrade", 1)[1].split("def run_status", 1)[0]
    assert run.index("baseline_differences(engine)") < run.index("command.stamp"), "check first, stamp second"
    assert "return 1" in run.split("command.stamp")[0], "a mismatch must return a failing exit code before the stamp"
    assert "pg_advisory_lock" in run and "pg_advisory_unlock" in run, "only one migration run at a time"
    assert "conn.rollback()" in text.split("def baseline_differences", 1)[1].split("def run_upgrade", 1)[0], "the scratch schema must never persist"


def test_scratch_schema_name_matches_the_literal_sql():
    from app import migrate

    source = (APP / "migrate.py").read_text(encoding="utf-8")
    assert f'text("CREATE SCHEMA {migrate.SCRATCH_SCHEMA}")' in source, "SQL text is not assembled from variables (test_security_guards)"
    assert re.fullmatch(r"[a-z_]+", migrate.SCRATCH_SCHEMA)
    assert migrate.SCRATCH_SCHEMA != "public"


def test_alembic_options_escape_percent_signs():
    # Alembic stores options in a ConfigParser: a bare "%(rev)s" raises InterpolationMissingOptionError (found by CI).
    source = (APP / "migrate.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if "set_main_option" in line and "%" in line:
            value = line.split(",", 1)[1]
            assert "%(" not in value.replace("%%(", ""), f"unescaped % in: {line.strip()}"
    assert '"file_template", "%%(rev)s_%%(slug)s"' in source
