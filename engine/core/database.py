"""
Market Bias Platform — Database Layer
SQLAlchemy 2.0 synchronous engine with SQLite default.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import settings

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    echo=False,
)

# Enable WAL mode for SQLite for better concurrent read performance
if "sqlite" in settings.database_url:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# ── Base ──────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy session and handles commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    from core import models  # noqa: F401 — import to register ORM models
    Base.metadata.create_all(bind=engine)
    # ``create_all`` can run from Streamlit before an operator invokes the
    # explicit migration script. Install the SQLite storage guards here too so
    # immutable audit tables never exist in an unprotected state. The helper is
    # idempotent; the migration remains the verification/reporting entry point.
    if engine.dialect.name == "sqlite":
        from core.research_store import install_append_only_guards
        install_append_only_guards(engine)
    from core.pit_data import sync_series_catalog
    with SessionLocal.begin() as session:
        sync_series_catalog(session)
    logger.info("Database initialised at: %s", settings.database_url)
