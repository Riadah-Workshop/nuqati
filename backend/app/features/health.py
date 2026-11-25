"""Liveness (`/health`) and readiness (`/ready`, checks the database) endpoints."""

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..api_app import app
from ..db import engine

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "nuqati-api", "version": "0.1.0"}

@app.get('/api/v1/ready')
def readiness():
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
    except SQLAlchemyError:
        raise HTTPException(503,'Database unavailable')
    return {'status':'ready'}
