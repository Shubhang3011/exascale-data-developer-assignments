"""Pydantic v2 request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Emission records
# ---------------------------------------------------------------------------
class EmissionRecordCreate(BaseModel):
    scope: int = Field(..., ge=1, le=2, description="GHG Protocol scope (1 or 2)")
    activity: str = Field(..., examples=["Diesel", "Grid Electricity", "Imported Steam"])
    category: Optional[str] = Field(None, description="Section / process, e.g. 'EAF'")
    facility: Optional[str] = Field(None, description="Plant / location")
    quantity: float = Field(..., gt=0)
    unit: str = Field(..., examples=["litre", "kWh", "GJ", "tonne", "KL", "kNm3"])
    activity_date: date
    notes: Optional[str] = None


class EmissionRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: int
    activity: str
    category: Optional[str]
    facility: Optional[str]
    quantity: float
    unit: str
    activity_date: date
    factor_id: Optional[int]
    factor_value_used: Optional[float]
    calculated_emissions_kgco2e: float
    final_emissions_kgco2e: float
    is_overridden: bool
    notes: Optional[str]
    created_at: datetime


class OverrideRequest(BaseModel):
    override_value: float = Field(..., description="New final emissions in kgCO2e")
    reason: str = Field(..., min_length=1)
    changed_by: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Emission factors (master data)
# ---------------------------------------------------------------------------
class EmissionFactorCreate(BaseModel):
    scope: int = Field(..., ge=1, le=2)
    activity: str
    category: Optional[str] = None
    unit: str
    co2e_per_unit: float = Field(..., description="kgCO2e per unit of activity")
    source: str
    version: int = 1
    valid_from: date
    valid_to: Optional[date] = None


class EmissionFactorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: int
    activity: str
    category: Optional[str]
    unit: str
    co2e_per_unit: float
    source: str
    version: int
    valid_from: date
    valid_to: Optional[date]
    created_at: datetime


# ---------------------------------------------------------------------------
# Business metrics
# ---------------------------------------------------------------------------
class BusinessMetricCreate(BaseModel):
    metric_date: date
    metric_name: str = Field(..., examples=["Tons of Steel Produced", "Number of Employees"])
    value: float
    unit: Optional[str] = None


class BusinessMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metric_date: date
    metric_name: str
    value: float
    unit: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_id: int
    action: str
    field_changed: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    reason: Optional[str]
    changed_by: Optional[str]
    changed_at: datetime


# ---------------------------------------------------------------------------
# Analytics response models
# ---------------------------------------------------------------------------
class ScopeBreakdown(BaseModel):
    scope1: float
    scope2: float
    total: float


class YoYResponse(BaseModel):
    year: int
    prev_year: int
    current: ScopeBreakdown
    previous: ScopeBreakdown
    change_pct: Optional[float]


class IntensityResponse(BaseModel):
    year: int
    metric: str
    total_kgco2e: float
    production_value: Optional[float]
    production_unit: Optional[str]
    intensity_kgco2e_per_unit: Optional[float]
    prev_year_intensity: Optional[float]
    change_pct: Optional[float]
    employees: Optional[float]
    intensity_kgco2e_per_employee: Optional[float]


class HotspotItem(BaseModel):
    source: str
    scope: int
    kgco2e: float
    pct_of_total: float


class MonthlyTrendItem(BaseModel):
    month: int
    month_name: str
    scope1: float
    scope2: float
    total: float


class SummaryResponse(BaseModel):
    year: int
    total_kgco2e: float
    scope1_kgco2e: float
    scope2_kgco2e: float
    top_hotspot: Optional[HotspotItem]
    intensity_kgco2e_per_unit: Optional[float]
    intensity_metric: Optional[str]
    record_count: int
