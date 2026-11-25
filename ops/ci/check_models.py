"""Every table and column that the ORM models describe must exist in the migrated database.

Run by CI job "Migrations" inside the API image against a database built only by `python -m app.migrate`
(PYTHONPATH=/app). A model change without a matching Alembic revision fails here. Differences in nullability are
printed as information only.
"""
import sys

from sqlalchemy import inspect

import app.main  # noqa: F401  (importing the application registers every model, also those in feature modules)
from app.db import Base, engine

inspector = inspect(engine)
problems, notes = [], []
tables = Base.metadata.sorted_tables
for table in tables:
    if not inspector.has_table(table.name):
        problems.append(f"table {table.name}: described by a model, missing in the database")
        continue
    columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    for column in table.columns:
        found = columns.get(column.name)
        if found is None:
            problems.append(f"column {table.name}.{column.name}: described by a model, missing in the database")
        elif not column.primary_key and bool(found["nullable"]) != bool(column.nullable):
            notes.append(f"{table.name}.{column.name}: model nullable={bool(column.nullable)}, database nullable={bool(found['nullable'])}")

for note in notes:
    print("note:", note)
for problem in problems:
    print("PROBLEM:", problem)
print(f"{len(tables)} model tables checked, {len(problems)} problem(s), {len(notes)} nullability note(s)")
sys.exit(1 if problems else 0)
