"""
SQLAlchemy ORM models for the Carbon Emissions Reporting Platform.

GHG Protocol Scope 1 (direct combustion / process) and Scope 2 (purchased
energy) are modelled.  **Every emission amount is stored in kgCO2e** and every
emission factor is stored as ``co2e_per_unit`` = kgCO2e per activity unit.

Design highlights
-----------------
* ``EmissionFactor`` is *versioned*: the same (scope, activity, unit) may have
  several rows with non-overlapping ``[valid_from, valid_to]`` windows. This is
  what makes the calculation engine historically accurate -- a 2023 activity is
  costed with the factor that was valid in 2023, not today's factor.
* ``EmissionRecord`` keeps both ``calculated_emissions_kgco2e`` (the engine's
  result) and ``final_emissions_kgco2e`` (the value actually reported -- equal
  to the calculated value unless a human override is applied).
* Every override is captured immutably in ``AuditLog``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class EmissionFactor(Base):
    """A versioned emission factor (kgCO2e per unit of activity)."""

    __tablename__ = "emission_factors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    activity: Mapped[str] = mapped_column(String, nullable=False)  # "Diesel", "Grid Electricity", ...
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # section / process
    unit: Mapped[str] = mapped_column(String, nullable=False)  # "litre", "kWh", "GJ", "tonne", ...
    co2e_per_unit: Mapped[float] = mapped_column(Float, nullable=False)  # kgCO2e per unit
    source: Mapped[str] = mapped_column(String, nullable=False)  # "IPCC 2006 Guidelines", ...
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)  # NULL = open ended
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    records: Mapped[list["EmissionRecord"]] = relationship(
        back_populates="factor", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return (
            f"<EmissionFactor scope={self.scope} activity={self.activity!r} "
            f"v{self.version} {self.valid_from}->{self.valid_to or 'open'} "
            f"{self.co2e_per_unit} kgCO2e/{self.unit}>"
        )


class EmissionRecord(Base):
    """A single quantified emission activity, costed through the engine."""

    __tablename__ = "emission_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[int] = mapped_column(Integer, nullable=False)
    activity: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)  # section / process
    facility: Mapped[str | None] = mapped_column(String, nullable=True)  # plant / location
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)

    factor_id: Mapped[int | None] = mapped_column(
        ForeignKey("emission_factors.id"), nullable=True
    )
    factor_value_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    calculated_emissions_kgco2e: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    final_emissions_kgco2e: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    is_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    factor: Mapped["EmissionFactor | None"] = relationship(back_populates="records")
    audit_entries: Mapped[list["AuditLog"]] = relationship(
        back_populates="record", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EmissionRecord id={self.id} scope={self.scope} "
            f"activity={self.activity!r} {self.activity_date} "
            f"final={self.final_emissions_kgco2e} kgCO2e>"
        )


class AuditLog(Base):
    """Immutable audit trail for overrides and other tracked changes."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("emission_records.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)  # "OVERRIDE", ...
    field_changed: Mapped[str | None] = mapped_column(String, nullable=True)
    old_value: Mapped[str | None] = mapped_column(String, nullable=True)
    new_value: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    record: Mapped["EmissionRecord"] = relationship(back_populates="audit_entries")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLog record_id={self.record_id} action={self.action!r} "
            f"{self.old_value}->{self.new_value}>"
        )


class BusinessMetric(Base):
    """Business activity data used to compute emission intensity (e.g. per ton
    of steel, per employee)."""

    __tablename__ = "business_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BusinessMetric {self.metric_name!r} {self.metric_date} "
            f"{self.value} {self.unit or ''}>"
        )
