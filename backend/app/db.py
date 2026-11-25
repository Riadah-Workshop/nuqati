from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Fail within 5 seconds when the database does not answer, instead of waiting for the operating
    # system's much longer default. /api/v1/ready then reports 503 quickly and the healthcheck can act.
    connect_args = {"connect_timeout": 5}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
