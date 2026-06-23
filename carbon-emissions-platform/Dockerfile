# syntax=docker/dockerfile:1
#
# Carbon Emissions Reporting Platform
# -----------------------------------
# A single-stage image that runs the FastAPI backend (which also serves the
# static frontend from /). The SQLite database is created and seeded at
# startup, so the container is fully self-contained -- no external services,
# no manual migration step.

FROM python:3.11-slim

# - Don't write .pyc files, keep stdout/stderr unbuffered so logs stream in
#   real time under `docker compose up`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project (backend, frontend, data workbook).
COPY . .

# FastAPI/uvicorn listens here.
EXPOSE 8000

# The app creates tables and runs the (idempotent) seed on startup, then serves
# the dashboard at / and the JSON API at /api/...
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
