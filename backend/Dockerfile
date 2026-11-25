FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
RUN useradd --create-home --uid 10001 nuqati
USER nuqati
EXPOSE 8000
# NUQATI_RUN_MIGRATIONS=1 applies pending database migrations (python -m app.migrate) before the API starts; a failed
# migration stops the container instead of starting the API on a half-changed schema. Default 0 = unchanged behaviour.
CMD ["sh", "-c", "if [ \"${NUQATI_RUN_MIGRATIONS:-0}\" = 1 ]; then python -m app.migrate || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
