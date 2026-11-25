"""Alembic environment. Online mode only, using the application's own engine (DATABASE_URL).

Run it through `python -m app.migrate` (see docs/DEVELOPMENT.md section 6), not by calling `alembic` directly:
that command also adopts an existing database safely.
"""
from alembic import context

from app.db import engine

if context.is_offline_mode():
    raise RuntimeError("Offline (SQL-only) mode is not supported: run migrations against the database with `python -m app.migrate`.")

# A caller (tests, tools) may pass an open connection through config.attributes["connection"].
connectable = context.config.attributes.get("connection") or engine


def run_migrations_online() -> None:
    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    # PostgreSQL can roll back DDL, so a failing revision leaves the database as it was.
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
