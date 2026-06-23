"""Master data: emission factors (versioned) and business metrics."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["masterdata"])


@router.get("/factors", response_model=List[schemas.EmissionFactorOut])
def list_factors(
    scope: Optional[int] = Query(None, ge=1, le=2),
    activity: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List emission factors with their validity windows and versions.

    Ordered by activity then ``valid_from`` so the versioning timeline reads
    naturally (oldest expired version first, current/open-ended last).
    """
    stmt = select(models.EmissionFactor)
    if scope is not None:
        stmt = stmt.where(models.EmissionFactor.scope == scope)
    if activity is not None:
        stmt = stmt.where(models.EmissionFactor.activity == activity)
    stmt = stmt.order_by(
        models.EmissionFactor.activity,
        models.EmissionFactor.valid_from,
    )
    return db.execute(stmt).scalars().all()


@router.post("/factors", response_model=schemas.EmissionFactorOut, status_code=201)
def create_factor(
    payload: schemas.EmissionFactorCreate, db: Session = Depends(get_db)
):
    factor = models.EmissionFactor(**payload.model_dump())
    db.add(factor)
    db.commit()
    db.refresh(factor)
    return factor


@router.get("/business-metrics", response_model=List[schemas.BusinessMetricOut])
def list_business_metrics(
    metric_name: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    from datetime import date

    stmt = select(models.BusinessMetric)
    if metric_name is not None:
        stmt = stmt.where(models.BusinessMetric.metric_name == metric_name)
    if year is not None:
        stmt = stmt.where(
            models.BusinessMetric.metric_date >= date(year, 1, 1)
        ).where(models.BusinessMetric.metric_date <= date(year, 12, 31))
    stmt = stmt.order_by(models.BusinessMetric.metric_date)
    return db.execute(stmt).scalars().all()


@router.post(
    "/business-metrics", response_model=schemas.BusinessMetricOut, status_code=201
)
def create_business_metric(
    payload: schemas.BusinessMetricCreate, db: Session = Depends(get_db)
):
    metric = models.BusinessMetric(**payload.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric
