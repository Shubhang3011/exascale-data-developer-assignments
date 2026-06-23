# Exascale Deeptech & AI — Data Developer Intern Assignments

This repository contains both end-to-end prototypes built for the **Data Developer Intern**
two-week sprint. Each assignment lives in its own self-contained folder with its own
backend, frontend, Dockerfile and detailed README.

| # | Assignment | Folder | Live entry point |
|---|------------|--------|------------------|
| 1 | Intelligent Power Demand Forecasting | [`power-demand-forecasting/`](power-demand-forecasting/) | FastAPI + Chart.js dashboard on `:8000` |
| 2 | Carbon Emissions Reporting Platform | [`carbon-emissions-platform/`](carbon-emissions-platform/) | FastAPI + Chart.js ESG dashboard on `:8000` |

---

## 1. Power Demand Forecasting — [details »](power-demand-forecasting/README.md)

Predicts electricity demand for every **10-minute block of the day (144 blocks / 24 h)** for
Apex Power & Utilities in **Dhanbad, Jharkhand**.

- **Data cleaning** handles the dataset's real defects: two *interleaved* date formats
  (`DD-MM-YYYY` and `M/D/YYYY`) parsed by separator, gap reindexing to a complete 10-min grid,
  and rolling-median + MAD outlier removal.
- **Feature engineering**: calendar + cyclical (sin/cos) features, weather, and **self-sourced
  localized Jharkhand holidays** (Sarhul, Karma, Tusu, Chhath, Vishwakarma Puja, Jharkhand
  Foundation Day, Labour Day, …).
- **Model**: per-feeder **LightGBM**, time-based validation → **TOTAL MAPE ≈ 4.4 %, R² ≈ 0.95**
  (trained artifact committed at `models/demand_model.pkl`).
- **Backend** (FastAPI): `/api/forecast`, `/api/weather` (live **Open-Meteo** + climatology
  fallback), `/api/holidays`, `/api/dashboard`.
- **Frontend**: interactive Chart.js dashboard (demand + feeders, weather panel, holiday markers).
- Plus an executed **EDA + modeling Jupyter notebook**, Dockerfile and comprehensive README.

## 2. Carbon Emissions Reporting Platform — [details »](carbon-emissions-platform/README.md)

A GHG-Protocol **Scope 1 & 2** carbon accounting platform with an analytics-first design.

- **Schema**: versioned `EmissionFactors` (`valid_from`/`valid_to`), `EmissionRecords`,
  `AuditLog`, `BusinessMetrics`.
- **Historical accuracy**: the calculation engine costs each activity with the factor that was
  valid *on its own date* (e.g. the same Diesel activity yields different emissions in 2023 vs 2024).
- **Analytics APIs**: Year-over-Year by scope, Emission Intensity (per ton of product **and** per
  employee), Emission Hotspot (by source), monthly trend, and a summary endpoint.
- **Core APIs**: create Scope 1/2 records and apply manual **overrides with a full audit trail**.
- **Frontend**: ESG dashboard with a stacked-bar (YoY), donut (hotspot), KPI cards (intensity) and
  a line chart (monthly trend), plus data-entry forms.
- Stack: FastAPI + SQLAlchemy + SQLite (seeded from the provided GHG workbook on startup),
  Dockerfile and a README with architecture & ER diagrams.

---

## Running the projects

Each project is independent. Pick a folder and follow its README. Quick start:

```bash
# Assignment 1 — Power Demand Forecasting
cd power-demand-forecasting
pip install -r requirements.txt
python -m uvicorn backend.main:app --port 8000      # open http://localhost:8000

# Assignment 2 — Carbon Emissions Platform
cd carbon-emissions-platform
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --port 8000  # open http://localhost:8000
```

Or with Docker (each folder ships a `Dockerfile` + `docker-compose.yml`):

```bash
cd <project-folder>
docker compose up --build      # open http://localhost:8000
```

> Run the two projects on **different ports** (or one at a time) if you want them up
> simultaneously, since both default to `:8000`.

## Repository structure

```
.
├── power-demand-forecasting/     # Assignment 1
│   ├── src/                      # data cleaning, features, weather, holidays, train, predict
│   ├── backend/                  # FastAPI app
│   ├── frontend/                 # Chart.js dashboard
│   ├── notebooks/                # executed EDA + modeling notebook
│   ├── models/                   # trained .pkl artifact + metadata
│   ├── data/                     # load CSV + self-sourced holiday calendar
│   ├── Dockerfile / docker-compose.yml / requirements.txt / README.md
│
└── carbon-emissions-platform/    # Assignment 2
    ├── backend/app/              # FastAPI + SQLAlchemy (models, calc engine, seed, routers)
    ├── frontend/                 # ESG Chart.js dashboard
    ├── data/                     # GHG workbook used to seed master data
    ├── Dockerfile / docker-compose.yml / requirements.txt / README.md
```
