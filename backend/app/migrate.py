"""Database migrations (Alembic) and adoption of the existing database.

    python -m app.migrate               apply pending migrations; adopts an existing database (see below)
    python -m app.migrate status        print the current and the newest revision; exit 1 if they differ
    python -m app.migrate check         compare the database with the baseline schema; exit 1 if it lacks anything
    python -m app.migrate new "text"    create the next revision file in app/migrations/versions/

Until Phase 3.3 the application created and changed its tables by itself while starting (SQL executed at import
time; that code is still there and is a no-op on a database that already has everything). A database that has
Nuqati's tables but no `alembic_version` table is therefore treated as "already at the baseline": it is checked
against the baseline schema and, if it has every table and column the baseline has, *stamped* (the revision number is
recorded, nothing is created or changed). Later revisions are then applied normally. A database that lacks tables
or columns of the baseline is not stamped: start the application once with the current release, which adds them,
and run this again.

Only PostgreSQL is supported. The container runs this before the API when NUQATI_RUN_MIGRATIONS=1 (backend/Dockerfile).
"""

import logging
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001"
BASELINE_SQL = MIGRATIONS_DIR / "versions" / "0001_baseline.sql"
SCRATCH_SCHEMA = "nuqati_baseline_check"  # also written out literally in baseline_differences (no interpolated SQL)
LOCK_KEY = 7_421_337_001  # arbitrary constant: only one migration run at a time

USAGE = 'usage: python -m app.migrate [upgrade | status | check | new "description"]'


def alembic_config():
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("file_template", "%%(rev)s_%%(slug)s")  # %% because Alembic keeps options in a ConfigParser
    return cfg


def baseline_sql() -> str:
    return BASELINE_SQL.read_text(encoding="utf-8")


def compare_columns(expected: dict, actual: dict) -> list[str]:
    """What the baseline expects that the database does not have. Extra tables and columns are fine.

    Both arguments map (table, column) to (data_type, is_nullable)."""
    problems: list[str] = []
    missing_tables = sorted({table for table, _ in expected} - {table for table, _ in actual})
    problems += [f"table {table} is missing" for table in missing_tables]
    for (table, column), (data_type, nullable) in sorted(expected.items()):
        if table in missing_tables:
            continue
        found = actual.get((table, column))
        if found is None:
            problems.append(f"column {table}.{column} is missing")
        elif found != (data_type, nullable):
            problems.append(
                f"column {table}.{column} is {found[0]} {'NULL' if found[1] == 'YES' else 'NOT NULL'}, "
                f"the baseline has {data_type} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
            )
    return problems


def _columns(conn, schema: str) -> dict:
    from sqlalchemy import text

    rows = conn.execute(
        text(
            "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name <> 'alembic_version'"
        ),
        {"schema": schema},
    )
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


def baseline_differences(engine) -> list[str]:
    """Build the baseline in a scratch schema inside a transaction that is always rolled back, then compare."""
    from sqlalchemy import text

    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE SCHEMA nuqati_baseline_check"))  # literal on purpose: see SCRATCH_SCHEMA
            cursor = conn.connection.cursor()
            try:
                cursor.execute(baseline_sql().replace("public.", SCRATCH_SCHEMA + "."))
            finally:
                cursor.close()
            return compare_columns(_columns(conn, SCRATCH_SCHEMA), _columns(conn, "public"))
        finally:
            conn.rollback()  # PostgreSQL DDL is transactional: the scratch schema never persists


def run_upgrade(engine) -> int:
    from alembic import command
    from sqlalchemy import inspect, text

    lock = engine.connect()
    try:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        lock.commit()  # the lock belongs to the session, not to the transaction
        inspector = inspect(engine)
        has_version = inspector.has_table("alembic_version")
        has_application_tables = inspector.has_table("companies")
        if has_application_tables and not has_version:
            problems = baseline_differences(engine)
            if problems:
                print("NOT adopting this database: it does not match the baseline schema.")
                for problem in problems:
                    print(f"  - {problem}")
                print("Start the application once with the current release (it adds missing tables and columns), then run this again.")
                return 1
            command.stamp(alembic_config(), BASELINE_REVISION)
            print(f"Existing database adopted: recorded as revision {BASELINE_REVISION}; nothing was changed.")
        command.upgrade(alembic_config(), "head")
        return 0
    finally:
        try:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            lock.commit()
        finally:
            lock.close()


def run_status(engine) -> int:
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    print(f"current={current or 'none'} head={head}")
    return 0 if current == head else 1


def next_revision_number(existing: list[str]) -> int:
    numbers = [int(name) for name in existing if name.isdigit()]
    return (max(numbers) if numbers else 0) + 1


def new_revision(message: str) -> int:
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config())
    number = next_revision_number([rev.revision for rev in script.walk_revisions()])
    command.revision(alembic_config(), message=message, rev_id=f"{number:04d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)  # one "setup plugin" line per plugin is noise
    action = argv[0] if argv else "upgrade"
    if action == "new":
        if len(argv) != 2 or not argv[1].strip():
            print(USAGE, file=sys.stderr)
            return 2
        return new_revision(argv[1])
    if action not in ("upgrade", "status", "check") or len(argv) > 1:
        print(USAGE, file=sys.stderr)
        return 2

    from .db import engine

    if engine.dialect.name != "postgresql":
        print("Migrations need PostgreSQL (DATABASE_URL points at another database).", file=sys.stderr)
        return 2
    if action == "status":
        return run_status(engine)
    if action == "check":
        problems = baseline_differences(engine)
        for problem in problems:
            print(problem)
        print("The database has everything the baseline has." if not problems else f"{len(problems)} difference(s).")
        return 1 if problems else 0
    return run_upgrade(engine)


if __name__ == "__main__":
    sys.exit(main())
