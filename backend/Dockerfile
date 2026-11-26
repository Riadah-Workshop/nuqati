FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
# requirements.txt is generated from requirements.in with exact versions and checksums; pip refuses anything else.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY backend/app ./app
RUN useradd --create-home --uid 10001 nuqati
USER nuqati
EXPOSE 8000
# Pending database migrations (python -m app.migrate) are applied before the API starts; a failed migration stops the
# container instead of starting the API on a half-changed schema. NUQATI_RUN_MIGRATIONS=0 skips this (the database is then
# managed by hand): since Phase 3.4 the application no longer creates tables itself.
CMD ["sh", "-c", "if [ \"${NUQATI_RUN_MIGRATIONS:-1}\" = 1 ]; then python -m app.migrate || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
