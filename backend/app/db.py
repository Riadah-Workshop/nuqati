import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings
from .db_pool import admission, load_pool_settings

POOL = load_pool_settings()
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    pool_args = {}
else:
    # Fail within 5 seconds when the database does not answer, instead of waiting for the operating
    # system's much longer default. /api/v1/ready then reports 503 quickly and the healthcheck can act.
    connect_args = {"connect_timeout": 5}
    # The same numbers SQLAlchemy used by default (5 + 10), now explicit and adjustable (see db_pool.py).
    pool_args = {"pool_size": POOL.pool_size, "max_overflow": POOL.max_overflow}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True, **pool_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    """Request-scoped session. A request is admitted only when a slot is free (db_pool.py explains why): the wait happens
    in the event loop, with no worker thread and no connection, so requests holding connections can always finish."""
    async with admission(POOL.request_slots):
        db = SessionLocal()
        try:
            yield db
        finally:
            # close() may talk to the database (rollback), so keep it off the event loop; asyncio's own executor is used
            # (not the framework's request threads) so closing never waits for a request thread either. shield: when the
            # client disconnects the framework cancels the request, and the close must still happen.
            await asyncio.shield(asyncio.to_thread(db.close))
