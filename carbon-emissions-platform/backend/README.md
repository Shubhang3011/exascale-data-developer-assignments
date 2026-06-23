# Carbon Emissions Reporting Platform — Backend

FastAPI + SQLAlchemy 2.x + SQLite backend implementing **GHG Protocol Scope 1
(direct combustion / process) and Scope 2 (purchased energy)** carbon
accounting for a steel manufacturer (*Central Steel Plant*).

The reference inventory is `data/GHG_Sheet.xlsx`. Scope 3 is intentionally out
of scope per the brief (the workbook's Scope 3 sheet is left unused).

## Run it

```bash
cd "carbon-emissions-platform"
python -m uvicorn backend.app.main:app --reload
```

- Tables are created and the database is **seeded automatically on startup**
  (idempotent — running again does not duplicate data).
- The SQLite file lives at `backend/emissions.db`. It is **gitignored** and
  recreated from the seed on every fresh startup, so the repo ships clean.
- `GET /` serves the static dashboard from `frontend/`.
- `GET /api/...` serves the JSON API. Interactive docs at `/docs`.

## Unit standardisation (important)

The workbook's emission factors are **mock and inflated** (e.g. grid
electricity at `0.8 tCO2/kWh`, which is ~1000× a realistic value). We **preserve
the given numeric values** but standardise all internal storage and computation
to **kgCO2e**:

```
co2e_per_unit (stored)  =  sheet value (tCO2 / unit)  ×  1000   →  kgCO2e / unit
emissions     (stored)  =  quantity  ×  co2e_per_unit           →  kgCO2e
```

So Diesel's sheet factor `1.757 tCO2/KL` is stored as `1757.0 kgCO2e/KL`. Every
emission amount in the database and every analytics figure is in **kgCO2e**.

## Data model (SQLAlchemy 2.x ORM)

| Table | Purpose |
|-------|---------|
| `emission_factors` | **Versioned** factors. Same `(scope, activity, unit)` can have several rows with **non-overlapping `[valid_from, valid_to]`** windows (`valid_to` NULL = open-ended). |
| `emission_records` | A quantified activity. Stores `factor_value_used`, `calculated_emissions_kgco2e` (engine result) and `final_emissions_kgco2e` (= override value if overridden, else calculated). |
| `audit_log` | Immutable trail of overrides: `old_value → new_value`, `reason`, `changed_by`. |
| `business_metrics` | "Tons of Steel Produced", "Number of Employees" — used for intensity. |

## The calculation engine (`calc.py`) — historical accuracy

`resolve_factor(db, scope, activity, activity_date, unit)` returns the factor
whose validity window **contains the activity's own date** (not the newest
factor). With non-overlapping windows there is one match; if several are
candidates the latest `valid_from <= activity_date` wins.

This is the core historical-accuracy requirement: a **2023** activity is costed
with the factor valid in 2023, a **2024** activity with the 2024 factor.

Seeded versioned examples (kgCO2e/unit):

| Activity | v1 (2022-01-01 → 2023-12-31, expired) | v2 (2024-01-01 → open) |
|----------|---------------------------------------|------------------------|
| Diesel | 1862.42 | 1757.00 |
| Natural Gas | 2522.00 | 2425.00 |
| Grid Electricity | 880.00 | 800.00 |
| Open Access Power | 864.00 | 800.00 |
| Captive Solar+Grid | 672.00 | 600.00 |

Because seeded records are routed **through the engine**, 2023 records pick up
the v1 factors and 2024 records the v2 factors automatically, producing a
genuine year-over-year delta and proving the versioning works end to end.

## API

All routes are prefixed `/api`.

### Records (`routers/records.py`)
- `POST /api/records` — create a Scope 1/2 record via the engine.
- `GET  /api/records?year=&scope=&activity=` — list with filters.
- `GET  /api/records/{id}`
- `PATCH /api/records/{id}/override` — body `{override_value, reason, changed_by}`; sets `final`, flags `is_overridden`, writes an audit row.
- `GET  /api/audit-log?record_id=`

### Master data (`routers/masterdata.py`)
- `GET/POST /api/factors` — factors with validity windows + version (filter `scope`, `activity`).
- `GET/POST /api/business-metrics`

### Analytics (`routers/analytics.py`) — Milestone 2
- `GET /api/analytics/yoy?year=` — totals by scope for `year` and `year-1` + `change_pct` (stacked bar).
- `GET /api/analytics/intensity?year=&metric=` — kgCO2e per unit of production + prior-year + per-employee.
- `GET /api/analytics/hotspot?year=` — breakdown by source, `pct_of_total`, sorted desc (donut).
- `GET /api/analytics/monthly-trend?year=` — 12-month scope1/scope2/total (line).
- `GET /api/analytics/summary?year=` — combined KPI payload.

All analytics use `final_emissions_kgco2e`, so **overrides are reflected** in the
reports.

## Seeded data summary

- **19 emission factors** (9 Scope 1 fuels + 5 Scope 2 sources; 5 of them
  double-versioned).
- **420 emission records** — monthly Scope 1 + Scope 2 for **2023, 2024** and a
  partial **2025 (H1)** across plant sections.
- **6 business metrics** — annual steel production and headcount for 2023–2025
  (growing year over year).
