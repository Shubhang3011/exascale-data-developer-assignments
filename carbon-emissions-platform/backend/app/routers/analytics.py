"""
Analytics endpoints -- the high-value reporting layer (Milestone 2).

All figures are computed from ``EmissionRecord.final_emissions_kgco2e`` (i.e.
overrides are respected) and are expressed in kgCO2e.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["analytics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _scope_totals(db: Session, year: int) -> tuple[float, float]:
    """Return (scope1_kgco2e, scope2_kgco2e) for a calendar year."""
    rows = (
        db.execute(
            select(
                models.EmissionRecord.scope,
                func.coalesce(
                    func.sum(models.EmissionRecord.final_emissions_kgco2e), 0.0
                ),
            )
            .where(
                extract("year", models.EmissionRecord.activity_date) == year
            )
            .group_by(models.EmissionRecord.scope)
        )
        .all()
    )
    by_scope = {int(scope): float(total) for scope, total in rows}
    return by_scope.get(1, 0.0), by_scope.get(2, 0.0)


def _metric_value(db: Session, year: int, metric_name: str) -> Optional[float]:
    """Sum a business metric for a year (annual rows sum to the annual value)."""
    total = db.execute(
        select(func.sum(models.BusinessMetric.value))
        .where(models.BusinessMetric.metric_name == metric_name)
        .where(extract("year", models.BusinessMetric.metric_date) == year)
    ).scalar()
    return float(total) if total is not None else None


def _metric_unit(db: Session, metric_name: str) -> Optional[str]:
    unit = db.execute(
        select(models.BusinessMetric.unit)
        .where(models.BusinessMetric.metric_name == metric_name)
        .limit(1)
    ).scalar()
    return unit


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous in (None, 0) or previous == 0.0:
        return None
    return round((current - previous) / previous * 100.0, 2)


# ---------------------------------------------------------------------------
# /analytics/yoy
# ---------------------------------------------------------------------------
@router.get("/analytics/yoy", response_model=schemas.YoYResponse)
def yoy(year: int = Query(..., description="Reporting year"), db: Session = Depends(get_db)):
    """Year-over-year totals by scope (drives the stacked bar chart)."""
    prev_year = year - 1

    s1_cur, s2_cur = _scope_totals(db, year)
    s1_prev, s2_prev = _scope_totals(db, prev_year)

    cur_total = s1_cur + s2_cur
    prev_total = s1_prev + s2_prev

    return schemas.YoYResponse(
        year=year,
        prev_year=prev_year,
        current=schemas.ScopeBreakdown(
            scope1=round(s1_cur, 3), scope2=round(s2_cur, 3), total=round(cur_total, 3)
        ),
        previous=schemas.ScopeBreakdown(
            scope1=round(s1_prev, 3),
            scope2=round(s2_prev, 3),
            total=round(prev_total, 3),
        ),
        change_pct=_pct_change(cur_total, prev_total),
    )


# ---------------------------------------------------------------------------
# /analytics/intensity
# ---------------------------------------------------------------------------
@router.get("/analytics/intensity", response_model=schemas.IntensityResponse)
def intensity(
    year: int = Query(...),
    metric: str = Query("Tons of Steel Produced"),
    db: Session = Depends(get_db),
):
    """Emission intensity = total kgCO2e / unit of production for the year,
    with prior-year comparison and (if available) per-employee intensity."""
    s1, s2 = _scope_totals(db, year)
    total = s1 + s2

    prod = _metric_value(db, year, metric)
    prod_unit = _metric_unit(db, metric)
    intensity_val = round(total / prod, 4) if prod else None

    # Previous-year intensity for the same metric.
    s1p, s2p = _scope_totals(db, year - 1)
    total_prev = s1p + s2p
    prod_prev = _metric_value(db, year - 1, metric)
    prev_intensity = (
        round(total_prev / prod_prev, 4) if (prod_prev and total_prev) else None
    )

    change_pct = (
        _pct_change(intensity_val, prev_intensity)
        if (intensity_val is not None and prev_intensity is not None)
        else None
    )

    employees = _metric_value(db, year, "Number of Employees")
    per_emp = round(total / employees, 4) if employees else None

    return schemas.IntensityResponse(
        year=year,
        metric=metric,
        total_kgco2e=round(total, 3),
        production_value=prod,
        production_unit=prod_unit,
        intensity_kgco2e_per_unit=intensity_val,
        prev_year_intensity=prev_intensity,
        change_pct=change_pct,
        employees=employees,
        intensity_kgco2e_per_employee=per_emp,
    )


# ---------------------------------------------------------------------------
# /analytics/hotspot
# ---------------------------------------------------------------------------
@router.get("/analytics/hotspot", response_model=list[schemas.HotspotItem])
def hotspot(year: int = Query(...), db: Session = Depends(get_db)):
    """Emissions broken down by activity/source, sorted desc (donut chart)."""
    rows = db.execute(
        select(
            models.EmissionRecord.activity,
            models.EmissionRecord.scope,
            func.coalesce(
                func.sum(models.EmissionRecord.final_emissions_kgco2e), 0.0
            ),
        )
        .where(extract("year", models.EmissionRecord.activity_date) == year)
        .group_by(models.EmissionRecord.activity, models.EmissionRecord.scope)
        .order_by(
            func.sum(models.EmissionRecord.final_emissions_kgco2e).desc()
        )
    ).all()

    grand_total = sum(float(r[2]) for r in rows)
    items: list[schemas.HotspotItem] = []
    for activity, scope, kg in rows:
        kg = float(kg)
        pct = round(kg / grand_total * 100.0, 2) if grand_total else 0.0
        items.append(
            schemas.HotspotItem(
                source=activity, scope=int(scope), kgco2e=round(kg, 3), pct_of_total=pct
            )
        )
    return items


# ---------------------------------------------------------------------------
# /analytics/monthly-trend
# ---------------------------------------------------------------------------
@router.get("/analytics/monthly-trend", response_model=list[schemas.MonthlyTrendItem])
def monthly_trend(year: int = Query(...), db: Session = Depends(get_db)):
    """Per-month scope1 / scope2 / total for the line chart (months with no
    data are returned as zeros so the chart has a full 12-point axis)."""
    rows = db.execute(
        select(
            extract("month", models.EmissionRecord.activity_date),
            models.EmissionRecord.scope,
            func.coalesce(
                func.sum(models.EmissionRecord.final_emissions_kgco2e), 0.0
            ),
        )
        .where(extract("year", models.EmissionRecord.activity_date) == year)
        .group_by(
            extract("month", models.EmissionRecord.activity_date),
            models.EmissionRecord.scope,
        )
    ).all()

    buckets: dict[int, dict[str, float]] = {
        m: {"scope1": 0.0, "scope2": 0.0} for m in range(1, 13)
    }
    for month, scope, kg in rows:
        m = int(month)
        key = "scope1" if int(scope) == 1 else "scope2"
        buckets[m][key] += float(kg)

    result: list[schemas.MonthlyTrendItem] = []
    for m in range(1, 13):
        s1 = round(buckets[m]["scope1"], 3)
        s2 = round(buckets[m]["scope2"], 3)
        result.append(
            schemas.MonthlyTrendItem(
                month=m,
                month_name=calendar.month_abbr[m],
                scope1=s1,
                scope2=s2,
                total=round(s1 + s2, 3),
            )
        )
    return result


# ---------------------------------------------------------------------------
# /analytics/summary
# ---------------------------------------------------------------------------
@router.get("/analytics/summary", response_model=schemas.SummaryResponse)
def summary(
    year: int = Query(...),
    metric: str = Query("Tons of Steel Produced"),
    db: Session = Depends(get_db),
):
    """Combined KPI-card payload: totals, top hotspot and intensity."""
    s1, s2 = _scope_totals(db, year)
    total = s1 + s2

    hotspots = hotspot(year=year, db=db)
    top = hotspots[0] if hotspots else None

    prod = _metric_value(db, year, metric)
    intensity_val = round(total / prod, 4) if prod else None

    record_count = db.execute(
        select(func.count(models.EmissionRecord.id)).where(
            extract("year", models.EmissionRecord.activity_date) == year
        )
    ).scalar() or 0

    return schemas.SummaryResponse(
        year=year,
        total_kgco2e=round(total, 3),
        scope1_kgco2e=round(s1, 3),
        scope2_kgco2e=round(s2, 3),
        top_hotspot=top,
        intensity_kgco2e_per_unit=intensity_val,
        intensity_metric=metric if intensity_val is not None else None,
        record_count=int(record_count),
    )
