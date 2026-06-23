"""
The calculation engine.

This is the heart of the platform.  Two requirements drive its design:

1. **Historical accuracy.**  An emission activity must be costed with the
   emission factor that was *valid on the activity's own date*, never the most
   recent factor.  ``resolve_factor`` implements this by selecting the versioned
   ``EmissionFactor`` whose ``[valid_from, valid_to]`` window contains the
   activity date.

2. **Auditable overrides.**  A human may override the engine's computed value;
   the original value, the new value and the reason are recorded immutably in
   ``AuditLog``.

All emissions are expressed in **kgCO2e**.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


def resolve_factor(
    db: Session,
    scope: int,
    activity: str,
    activity_date: date,
    unit: Optional[str] = None,
) -> Optional[models.EmissionFactor]:
    """Return the emission factor valid for ``activity`` on ``activity_date``.

    Matching rules:
      * scope and activity must match exactly;
      * if ``unit`` is supplied it must match too;
      * ``valid_from <= activity_date`` and
        (``valid_to`` is NULL **or** ``activity_date <= valid_to``);
      * if several candidates remain (which should not happen with
        non-overlapping windows, but we are defensive), the one with the latest
        ``valid_from`` wins -- i.e. the most specific window for that date.

    Returns ``None`` when no factor covers the date (the caller then stores a
    zero-emission record so nothing is silently dropped).
    """
    stmt = (
        select(models.EmissionFactor)
        .where(models.EmissionFactor.scope == scope)
        .where(models.EmissionFactor.activity == activity)
        .where(models.EmissionFactor.valid_from <= activity_date)
        .where(
            (models.EmissionFactor.valid_to.is_(None))
            | (models.EmissionFactor.valid_to >= activity_date)
        )
        .order_by(models.EmissionFactor.valid_from.desc())
    )
    if unit is not None:
        stmt = stmt.where(models.EmissionFactor.unit == unit)

    return db.execute(stmt).scalars().first()


def compute_emissions(quantity: float, factor: models.EmissionFactor) -> float:
    """kgCO2e = quantity * (kgCO2e per unit)."""
    return float(quantity) * float(factor.co2e_per_unit)


def create_emission_record(db: Session, payload: dict) -> models.EmissionRecord:
    """Create and persist an :class:`EmissionRecord` via the engine.

    ``payload`` keys: scope, activity, quantity, unit, activity_date and the
    optional category, facility, notes.  The factor is resolved by date so the
    historically-correct value is applied, then ``calculated`` and ``final``
    emissions are stored.
    """
    scope = int(payload["scope"])
    activity = payload["activity"]
    quantity = float(payload["quantity"])
    unit = payload["unit"]
    activity_date = payload["activity_date"]

    factor = resolve_factor(db, scope, activity, activity_date, unit=unit)
    if factor is None:
        # Fall back to a unit-agnostic match (handles records whose unit string
        # differs slightly from the factor's, e.g. "litre" vs "L").
        factor = resolve_factor(db, scope, activity, activity_date, unit=None)

    if factor is not None:
        factor_value = float(factor.co2e_per_unit)
        emissions = compute_emissions(quantity, factor)
        factor_id = factor.id
    else:
        factor_value = None
        emissions = 0.0
        factor_id = None

    record = models.EmissionRecord(
        scope=scope,
        activity=activity,
        category=payload.get("category"),
        facility=payload.get("facility"),
        quantity=quantity,
        unit=unit,
        activity_date=activity_date,
        factor_id=factor_id,
        factor_value_used=factor_value,
        calculated_emissions_kgco2e=emissions,
        final_emissions_kgco2e=emissions,
        is_overridden=False,
        notes=payload.get("notes"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def apply_override(
    db: Session,
    record_id: int,
    override_value: float,
    reason: str,
    changed_by: str,
) -> Optional[models.EmissionRecord]:
    """Override a record's reported emissions and write an audit entry.

    Returns the updated record, or ``None`` if the record does not exist.
    """
    record = db.get(models.EmissionRecord, record_id)
    if record is None:
        return None

    old_final = record.final_emissions_kgco2e

    audit = models.AuditLog(
        record_id=record.id,
        action="OVERRIDE",
        field_changed="final_emissions_kgco2e",
        old_value=f"{old_final}",
        new_value=f"{float(override_value)}",
        reason=reason,
        changed_by=changed_by,
    )
    db.add(audit)

    record.final_emissions_kgco2e = float(override_value)
    record.is_overridden = True

    db.commit()
    db.refresh(record)
    return record
