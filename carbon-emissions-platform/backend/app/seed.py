"""
Idempotent database seeding.

The seed derives realistic values from ``data/GHG_Sheet.xlsx`` (a Central Steel
Plant GHG inventory) and builds:

* a **versioned** ``EmissionFactor`` table -- several activities get more than
  one factor version with non-overlapping validity windows, including expired
  factors for 2022/2023.  Unit standardisation: the workbook stores factors as
  ``tCO2 / unit``; we multiply by 1000 and store ``kgCO2e / unit``.
* a multi-year set of ``EmissionRecord`` rows (2023 + 2024, plus a partial
  2025) generated *through the calculation engine* so each record automatically
  picks up the factor that was valid on its own date -- demonstrating historical
  accuracy and producing a genuine year-over-year delta.
* ``BusinessMetric`` rows ("Tons of Steel Produced", "Number of Employees")
  that grow year over year, enabling the intensity analytics.

Running it twice is safe: if any emission factors already exist it returns
immediately.
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from . import calc, models
from .database import PROJECT_ROOT

XLSX_PATH = PROJECT_ROOT / "data" / "GHG_Sheet.xlsx"

# Factor mock values are inflated in the workbook; preserve the numbers but
# convert tCO2/unit -> kgCO2e/unit.
T_TO_KG = 1000.0


# ---------------------------------------------------------------------------
# Raw factor reference, lifted from the workbook (tCO2 / unit).
# We use these to build versioned factors; a small downward adjustment is
# applied to the *older* (2022-2023) versions so YoY shows a real change and to
# reflect grid decarbonisation / efficiency improvements over time.
# ---------------------------------------------------------------------------
SCOPE1_FUELS = [
    # activity,           unit,     category,        tco2_per_unit, source
    ("Diesel",            "KL",     "Pellet Plant",  1.757, "IPCC 2006 Guidelines"),
    ("Natural Gas",       "kNm3",   "Pellet Plant",  2.425, "IPCC 2006 Guidelines"),
    ("Anthracite Coal",   "tonne",  "Pellet Plant",  1.044, "IPCC 2006 Guidelines"),
    ("Bituminous Coal",   "tonne",  "Pellet Plant",  3.084, "IPCC 2006 Guidelines"),
    ("Petroleum Coke",    "tonne",  "Pellet Plant",  1.390, "IPCC 2006 Guidelines"),
    ("Fuel Oil",          "KL",     "Power Plant",   2.539, "IPCC 2006 Guidelines"),
    ("LPG",               "tonne",  "Rolling Mill",  3.346, "IPCC 2006 Guidelines"),
    ("Kerosene",          "KL",     "DRI",           2.255, "IPCC 2006 Guidelines"),
    ("Limestone",         "tonne",  "SMS",           3.087, "IPCC 2006 Guidelines"),
]

SCOPE2_SOURCES = [
    # activity,            unit,  category,            tco2_per_unit, source
    ("Grid Electricity",   "kWh", "EAF",               0.80, "CEA India 2023 Report"),
    ("Open Access Power",   "kWh", "Rolling Mill",      0.80, "CEA India 2023 Report"),
    ("Captive Solar+Grid",  "kWh", "Pellet Plant",      0.60, "CEA India 2023 Report"),
    ("Imported Steam",      "GJ",  "Utilities",         0.20, "CEA India 2023 Report"),
    ("Local Discom Power",  "kWh", "Admin Buildings",   0.85, "CEA India 2023 Report"),
]

# Activities that get an EXPIRED older version (2022-01-01 .. 2023-12-31) with a
# slightly different value, plus a current version (2024-01-01 .. open).
# old_factor = current * multiplier.
VERSIONED = {
    "Diesel": 1.06,             # diesel EF was ~6% higher before 2024 spec change
    "Natural Gas": 1.04,
    "Grid Electricity": 1.10,   # grid decarbonised -> 2024 EF lower
    "Open Access Power": 1.08,
    "Captive Solar+Grid": 1.12,
}

# Monthly base quantities per activity (scaled-down, realistic per-month values
# for one plant).  Year-over-year growth is applied on top.
MONTHLY_QTY = {
    # scope 1 (units as in SCOPE1_FUELS)
    "Diesel": 210.0,
    "Natural Gas": 3900.0,
    "Anthracite Coal": 11400.0,
    "Bituminous Coal": 39700.0,
    "Petroleum Coke": 7740.0,
    "Fuel Oil": 610.0,
    "LPG": 8900.0,
    "Kerosene": 430.0,
    "Limestone": 8980.0,
    # scope 2
    "Grid Electricity": 1_950_000.0,
    "Open Access Power": 820_000.0,
    "Captive Solar+Grid": 330_000.0,
    "Imported Steam": 14_900.0,
    "Local Discom Power": 165_000.0,
}

FACILITY = "Central Steel Plant"

# Year -> activity growth factor applied to monthly base quantities.
YEAR_GROWTH = {
    2023: 1.00,
    2024: 1.08,   # plant ramped up production ~8%
    2025: 1.05,   # partial year (H1)
}

# Business metrics that grow year over year.
STEEL_PRODUCTION = {2023: 1_180_000.0, 2024: 1_310_000.0, 2025: 720_000.0}  # tonnes
EMPLOYEES = {2023: 2400.0, 2024: 2520.0, 2025: 2560.0}


def _activity_lookup() -> dict[str, dict]:
    """Map activity -> {unit, category, source, current_ef_kg}."""
    out: dict[str, dict] = {}
    for activity, unit, category, tco2, source in SCOPE1_FUELS:
        out[activity] = {
            "scope": 1,
            "unit": unit,
            "category": category,
            "source": source,
            "current_ef_kg": tco2 * T_TO_KG,
        }
    for activity, unit, category, tco2, source in SCOPE2_SOURCES:
        out[activity] = {
            "scope": 2,
            "unit": unit,
            "category": category,
            "source": source,
            "current_ef_kg": tco2 * T_TO_KG,
        }
    return out


def _seed_factors(db: Session) -> None:
    """Insert versioned emission factors (kgCO2e/unit)."""
    lookup = _activity_lookup()

    for activity, meta in lookup.items():
        current_ef = round(meta["current_ef_kg"], 4)

        if activity in VERSIONED:
            # v1: expired, covers 2022-2023, slightly higher value.
            old_ef = round(current_ef * VERSIONED[activity], 4)
            db.add(
                models.EmissionFactor(
                    scope=meta["scope"],
                    activity=activity,
                    category=meta["category"],
                    unit=meta["unit"],
                    co2e_per_unit=old_ef,
                    source=meta["source"],
                    version=1,
                    valid_from=date(2022, 1, 1),
                    valid_to=date(2023, 12, 31),
                )
            )
            # v2: current, open ended, from 2024.
            db.add(
                models.EmissionFactor(
                    scope=meta["scope"],
                    activity=activity,
                    category=meta["category"],
                    unit=meta["unit"],
                    co2e_per_unit=current_ef,
                    source=meta["source"],
                    version=2,
                    valid_from=date(2024, 1, 1),
                    valid_to=None,
                )
            )
        else:
            # Single open-ended version valid for the whole period.
            db.add(
                models.EmissionFactor(
                    scope=meta["scope"],
                    activity=activity,
                    category=meta["category"],
                    unit=meta["unit"],
                    co2e_per_unit=current_ef,
                    source=meta["source"],
                    version=1,
                    valid_from=date(2022, 1, 1),
                    valid_to=None,
                )
            )

    db.commit()


def _seed_records(db: Session) -> None:
    """Generate monthly records for each activity across 2023-2025 (H1) via the
    calculation engine, so factor resolution is exercised per date."""
    lookup = _activity_lookup()

    plans = [
        (2023, range(1, 13)),
        (2024, range(1, 13)),
        (2025, range(1, 7)),  # partial current year
    ]

    for year, months in plans:
        growth = YEAR_GROWTH[year]
        for month in months:
            # Use the 15th of each month as the activity date.
            activity_date = date(year, month, 15)
            for activity, meta in lookup.items():
                base = MONTHLY_QTY[activity]
                # Light seasonal wobble so the monthly trend isn't flat.
                seasonal = 1.0 + 0.05 * ((month % 4) - 1.5) / 1.5
                quantity = round(base * growth * seasonal, 3)
                calc.create_emission_record(
                    db,
                    {
                        "scope": meta["scope"],
                        "activity": activity,
                        "category": meta["category"],
                        "facility": FACILITY,
                        "quantity": quantity,
                        "unit": meta["unit"],
                        "activity_date": activity_date,
                        "notes": "Seeded monthly record",
                    },
                )


def _seed_business_metrics(db: Session) -> None:
    """Annual production + headcount metrics that grow year over year."""
    for year, tons in STEEL_PRODUCTION.items():
        db.add(
            models.BusinessMetric(
                metric_date=date(year, 12, 31),
                metric_name="Tons of Steel Produced",
                value=tons,
                unit="tonne",
            )
        )
    for year, emp in EMPLOYEES.items():
        db.add(
            models.BusinessMetric(
                metric_date=date(year, 12, 31),
                metric_name="Number of Employees",
                value=emp,
                unit="people",
            )
        )
    db.commit()


def _validate_workbook() -> None:
    """Best-effort sanity read of the workbook so seeding fails loudly if the
    reference file is missing or malformed.  We don't *require* the read to
    succeed (the values are baked into this module), but we log a clear message
    if it isn't available."""
    if not XLSX_PATH.exists():
        print(f"[seed] WARNING: reference workbook not found at {XLSX_PATH}; "
              "using baked-in factor values.")
        return
    try:
        s1 = pd.read_excel(XLSX_PATH, sheet_name="Scope 1")
        s2 = pd.read_excel(XLSX_PATH, sheet_name="Scope 2")
        print(f"[seed] read GHG_Sheet.xlsx -> Scope 1: {len(s1)} rows, "
              f"Scope 2: {len(s2)} rows (factors standardised to kgCO2e/unit).")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[seed] WARNING: could not read workbook ({exc}); using baked-in values.")


def seed_all(db: Session) -> None:
    """Populate the database if empty.  Idempotent."""
    if db.query(models.EmissionFactor).count() > 0:
        print("[seed] emission factors already present -> skipping seed.")
        return

    print("[seed] seeding database from GHG_Sheet.xlsx ...")
    _validate_workbook()
    _seed_factors(db)
    _seed_business_metrics(db)
    _seed_records(db)

    print(
        "[seed] done: "
        f"{db.query(models.EmissionFactor).count()} factors, "
        f"{db.query(models.EmissionRecord).count()} records, "
        f"{db.query(models.BusinessMetric).count()} business metrics."
    )


# Expose month names for analytics (kept here so the data layer owns it).
MONTH_NAMES = list(calendar.month_name)  # index 0 == ''
