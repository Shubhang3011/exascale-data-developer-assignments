"""Emission record CRUD, overrides and the audit log."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import calc, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["records"])


@router.post("/records", response_model=schemas.EmissionRecordOut, status_code=201)
def create_record(
    payload: schemas.EmissionRecordCreate, db: Session = Depends(get_db)
):
    """Create a Scope 1 or Scope 2 emission record.

    The record is routed through the calculation engine, which resolves the
    historically-correct emission factor for ``activity_date`` and computes the
    emissions in kgCO2e.
    """
    record = calc.create_emission_record(db, payload.model_dump())
    if record.factor_id is None:
        # Not fatal -- the record is stored with zero emissions -- but surface a
        # helpful hint in the notes so the UI can flag it.
        record.notes = (
            (record.notes + " | " if record.notes else "")
            + "No emission factor found for this activity/date."
        )
        db.commit()
        db.refresh(record)
    return record


@router.get("/records", response_model=List[schemas.EmissionRecordOut])
def list_records(
    year: Optional[int] = Query(None, description="Filter by activity year"),
    scope: Optional[int] = Query(None, ge=1, le=2),
    activity: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    stmt = select(models.EmissionRecord)
    if scope is not None:
        stmt = stmt.where(models.EmissionRecord.scope == scope)
    if activity is not None:
        stmt = stmt.where(models.EmissionRecord.activity == activity)
    if year is not None:
        stmt = stmt.where(
            models.EmissionRecord.activity_date >= date(year, 1, 1)
        ).where(models.EmissionRecord.activity_date <= date(year, 12, 31))
    stmt = stmt.order_by(models.EmissionRecord.activity_date.desc()).limit(limit)
    return db.execute(stmt).scalars().all()


@router.get("/records/{record_id}", response_model=schemas.EmissionRecordOut)
def get_record(record_id: int, db: Session = Depends(get_db)):
    record = db.get(models.EmissionRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.patch(
    "/records/{record_id}/override", response_model=schemas.EmissionRecordOut
)
def override_record(
    record_id: int,
    body: schemas.OverrideRequest,
    db: Session = Depends(get_db),
):
    """Apply a manual override to a record's reported emissions.

    Sets ``final_emissions_kgco2e`` to ``override_value``, flags the record as
    overridden and writes an immutable ``AuditLog`` entry.
    """
    record = calc.apply_override(
        db,
        record_id=record_id,
        override_value=body.override_value,
        reason=body.reason,
        changed_by=body.changed_by,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("/audit-log", response_model=List[schemas.AuditLogOut])
def list_audit_log(
    record_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(models.AuditLog)
    if record_id is not None:
        stmt = stmt.where(models.AuditLog.record_id == record_id)
    stmt = stmt.order_by(models.AuditLog.changed_at.desc())
    return db.execute(stmt).scalars().all()
