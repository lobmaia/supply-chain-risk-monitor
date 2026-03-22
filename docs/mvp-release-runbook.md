# MVP Release Runbook

## Scope

Phase 5 stabilizes the MVP for demo and early feedback by tightening runtime validation, adding targeted reliability tests, and documenting the critical-path workflows.

## Pre-Demo Checklist

1. Install dependencies with `pip install -e ".[dev]"`.
2. Copy `.env.example` to `.env` and confirm the configured `RSS_FEED_URLS`.
3. Run `ruff check .`.
4. Run `pytest`.
5. Run `python3 scripts/performance_smoke.py --articles 250`.
6. Start the API with `uvicorn app.main:app --reload`.
7. Start the dashboard with `streamlit run frontend/dashboard.py`.
8. Confirm `GET /health` returns `{"status": "ok"}`.

## Operational Notes

- Configuration now fails fast on invalid URLs, retry settings, thresholds, and seed-watchlist syntax.
- The ingestion scheduler logs and survives transient ingestion failures instead of terminating the background loop.
- The MVP currently relies on RSS feeds, so there are no external API secrets required for the primary ingestion path.

## Demo Script

1. Open the dashboard overview and point out top entities plus flagged events.
2. Trigger `POST /api/v1/ingestion/run` and show the returned counts.
3. Show `GET /api/v1/processing/status` to confirm relevant-article and pending counts.
4. Show `GET /api/v1/risk/entities/current` and one entity history endpoint.
5. Create a watchlist item for a company already present in seeded articles and explain the automatic reprocessing.
6. Open a flagged-event detail view and show the linked entities plus scoring evidence.

## Known Limitations

- Relevance and risk scoring are heuristic and optimized for explainability, not model-grade recall.
- SQLite and the in-process scheduler are appropriate for MVP/demo workloads but not multi-worker production deployment.
- Feed freshness and coverage depend on the configured RSS sources.
- There is no authentication, role separation, or audit trail beyond application logs and persisted ingestion runs.

## Next-Phase Recommendations

- Replace heuristic relevance scoring with a calibrated classifier and labeled evaluation set.
- Move scheduled ingestion to an external worker or queue-backed job runner.
- Add authentication, RBAC, and deployment-specific secret storage.
- Capture longitudinal benchmark data from `scripts/performance_smoke.py` in CI or release checks.
