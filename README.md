# Supply Chain Risk Monitor

The MVP now includes:

- `FastAPI` backend for service endpoints.
- `Streamlit` frontend for a lightweight dashboard shell.
- `SQLite` via `SQLModel` for local persistence.
- Environment-driven configuration, structured logging, and CI checks.
- RSS-based news ingestion with scheduled background polling, retry handling, and deduplication.
- Rules-first relevance scoring with persisted audit fields on articles.
- Entity extraction for watchlist companies, regions, and commodity exposure.
- Risk scoring, trend snapshots, and flagged-event APIs for dashboard consumption.
- Analyst-facing Streamlit dashboard with entity summaries, trend charts, alert evidence, and watchlist management.
- Phase 5 stabilization work: fail-fast config validation, scheduler hardening, targeted reliability tests, and release/runbook documentation.

## Repository Layout

```text
app/
  api/        # FastAPI routes
  core/       # config and logging
  db/         # engine and session helpers
  models/     # initial MVP data models
frontend/     # Streamlit app
tests/        # backend smoke tests
```

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Copy the environment template:

```bash
cp .env.example .env
```

## Run Locally

Backend:

```bash
uvicorn app.main:app --reload
```

Frontend:

```bash
streamlit run frontend/dashboard.py
```

The backend initializes the database automatically on startup, starts the ingestion scheduler, and exposes:

- `GET /health`
- `GET /api/v1/summary`
- `GET /api/v1/ingestion/status`
- `POST /api/v1/ingestion/run`
- `GET /api/v1/processing/status`
- `POST /api/v1/processing/run`
- `GET /api/v1/risk/status`
- `GET /api/v1/risk/entities/current`
- `GET /api/v1/risk/entities/{entity_id}/history`
- `GET /api/v1/risk/events/flagged`
- `GET /api/v1/risk/events/{article_id}`
- `GET /api/v1/dashboard/overview`
- `GET|POST|PUT|DELETE /api/v1/watchlist`

The ingestion worker polls the comma-separated `RSS_FEED_URLS` list on `INGESTION_INTERVAL_SECONDS`.
Articles are persisted with raw payloads, normalized text, source metadata, and URL/content-hash
deduplication. Each ingestion run is logged in the database with counts for fetched, inserted,
updated, duplicate, and failed items.
After ingestion, pending articles are relevance-scored, tagged to extracted entities, and linked to
watchlist targets using a rules-first classifier.

## Quality Checks

Lint:

```bash
ruff check .
```

Tests:

```bash
pytest
```

Performance smoke check:

```bash
python3 scripts/performance_smoke.py --articles 250
```

Runbook and demo notes:

```text
docs/mvp-release-runbook.md
```

## MVP Scope Decisions

- Ingestion source: RSS feeds to avoid API key friction during MVP development
- Scheduler model: in-process background worker started with the FastAPI app
- Deduplication strategy: unique URL plus content-hash detection for syndicated duplicates
- Persistence: article raw payloads and ingestion run metrics stored in `SQLite`
- Observability baseline: JSON structured logs plus persisted ingestion run status/error counts
- Relevance strategy: explainable keyword-based scoring optimized for precision over recall
- Entity tagging: watchlist-aware company matching plus curated region/commodity dictionaries
- Dashboard delivery: Streamlit to keep the MVP operationally simple while still supporting analyst workflows
- Watchlist refresh strategy: watchlist CRUD triggers article reprocessing so entity links and risk views stay aligned
- Release readiness: invalid config now fails fast at startup, and scheduler loop failures are logged without killing the process
