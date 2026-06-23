"""
FastAPI application entry point.

Run from the project root::

    cd "d:/Assignments placement/carbon-emissions-platform"
    python -m uvicorn backend.app.main:app --reload

On startup the database tables are created and the (idempotent) seed runs, so a
fresh checkout is immediately populated with multi-year demo data.  The
``frontend/`` folder is mounted as static at ``/`` *after* the API routes, so
``GET /`` serves the dashboard while ``GET /api/...`` serves JSON.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# --- Defensive: make sure the project root is importable regardless of how the
# process was launched (python -m uvicorn, uvicorn CLI, pytest, etc.). ---------
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # carbon-emissions-platform
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend.app import models, seed  # noqa: E402,F401
from backend.app.database import Base, SessionLocal, engine  # noqa: E402
from backend.app.routers import analytics, masterdata, records  # noqa: E402

FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and seed demo data on startup (idempotent)."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed.seed_all(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Carbon Emissions Reporting Platform",
    description=(
        "GHG Protocol Scope 1 & 2 carbon accounting for a steel manufacturer. "
        "All emissions are stored and reported in kgCO2e."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "carbon-emissions-platform"}


# API routers (all already use the /api prefix internally).
app.include_router(records.router)
app.include_router(masterdata.router)
app.include_router(analytics.router)

# Mount the static frontend LAST so it only handles paths not claimed by the API.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
