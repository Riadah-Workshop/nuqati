"""Baseline: the schema the application created by itself up to Phase 3.2.

`0001_baseline.sql` next to this file is a schema-only dump (pg_dump -s) of a database created by the application's
own start-up code, reduced to CREATE and ALTER statements (no comments, SET lines, owners or privileges). CI proves
that applying it gives the same schema as the start-up code (.github/workflows/ci.yml, job "Migrations").

An existing database is not built with this revision: `python -m app.migrate` checks that it already has every table
and column of the baseline and then only records the revision (stamp).
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    sql = Path(__file__).with_name("0001_baseline.sql").read_text(encoding="utf-8")
    # The raw DBAPI cursor sends the script as it is: no parameter parsing, so '%' and ':' in it are harmless.
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def downgrade():
    raise RuntimeError("The baseline cannot be undone (it would delete every table). Restore from a backup instead.")
