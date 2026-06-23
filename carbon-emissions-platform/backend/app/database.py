"""
Database configuration for the Carbon Emissions Reporting Platform.

A single SQLite database (``backend/emissions.db``) is used. The file is
gitignored and recreated from the seed script on every startup, so the
repository ships clean.

All monetary/quantity columns that represent emissions are stored in
**kgCO2e** (see README for the unit-standardisation rationale).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# Resolve the database location relative to *this* file so the app runs from
# any working directory.  database.py lives at  backend/app/database.py  so the
# database file sits at  backend/emissions.db  (one level up from ``app``).
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent          # .../backend/app
BACKEND_DIR = APP_DIR.parent                        # .../backend
PROJECT_ROOT = BACKEND_DIR.parent                   # .../carbon-emissions-platform

DB_PATH = BACKEND_DIR / "emissions.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# ``check_same_thread=False`` is required because FastAPI may access the
# session from a different thread than the one that created the connection.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models (SQLAlchemy 2.x style)."""


def get_db():
    """FastAPI dependency that yields a database session and closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
