# Supply Chain Risk Monitor: MVP Implementation Plan


## Phase 0: Foundations and Project Setup (Week 1)
**Goal:** Establish a working development baseline and define MVP boundaries in implementation terms.

**Key Activities**
- Confirm MVP scope and acceptance criteria from the project description.
- Choose initial stack for each layer:
  - Backend/API framework.
  - Data store for articles, entities, scores, and time series.
  - Frontend framework (or Streamlit) for dashboard.
- Define repository structure, coding standards, and environment variable conventions.
- Set up local development environment and CI checks (lint/test placeholders are acceptable initially).
- Add basic observability scaffolding (structured logging and error handling conventions).

**Deliverables**
- Running skeleton application (frontend + backend + database connectivity).
- Environment template (`.env.example`) and setup instructions.
- Initial data model definitions for core entities.

**Exit Criteria**
- Team can run the app locally with one command per service.
- Core project skeleton supports adding ingestion and scoring without refactoring.

## Phase 1: Data Ingestion Pipeline (Week 2)
**Goal:** Ingest and persist raw news data from one reliable source.

**Key Activities**
- Implement connector for one source (NewsAPI, GDELT, or RSS).
- Add scheduler/worker job for periodic fetches.
- Normalize article payloads into a common schema.
- Store raw and normalized records with deduplication (URL/hash strategy).
- Add retry and failure handling for transient API/network errors.

**Deliverables**
- Automated ingestion job running on a schedule.
- Persisted article records in database with source metadata and timestamps.
- Basic ingestion health logs and error metrics.

**Exit Criteria**
- Pipeline ingests fresh items reliably over multiple runs.
- Duplicate content is minimized and ingestion failures are visible in logs.

## Phase 2: Relevance Filtering and Entity Tagging (Week 3)
**Goal:** Transform raw articles into supply-chain-relevant, tagged records.

**Key Activities**
- Implement relevance classifier (rules-first or lightweight model).
- Define relevance confidence threshold and fallback handling.
- Add entity extraction for company, region, and commodity/product category.
- Create monitored-entity mapping logic for watchlist alignment.
- Store filtering outcomes and extracted entities for auditability.

**Deliverables**
- Relevance-filtered article stream.
- Entity-tagged records linked to watchlist targets.
- Evaluation script/report using a small labeled sample.

**Exit Criteria**
- Filter quality is acceptable for MVP (practical precision over recall).
- Most surfaced alerts map to meaningful monitored entities.

## Phase 3: Risk Scoring and Trend Engine (Week 4)
**Goal:** Generate usable risk signals at article and entity levels over time.

**Key Activities**
- Define risk scoring strategy (sentiment + event severity heuristics).
- Compute article-level risk score with stored scoring factors.
- Aggregate to entity-level daily (or hourly) risk time series.
- Implement spike-detection logic for sudden risk increases.
- Expose scoring and trend data through API endpoints.

**Deliverables**
- Article and entity risk score pipeline.
- Trend and spike flags stored for dashboard consumption.
- API endpoints for current risk, history, and flagged events.

**Exit Criteria**
- Risk scores update automatically with new ingestion cycles.
- Spike detection produces understandable, non-random alerts.

## Phase 4: Dashboard MVP and Watchlist UX (Week 5)
**Goal:** Deliver an analyst-usable interface for monitoring and investigation.

**Key Activities**
- Build dashboard pages/components:
  - Risk summary by entity.
  - Trend chart over time.
  - Flagged headline feed.
  - Alert evidence/details panel.
- Implement watchlist management UI (add/edit/remove targets).
- Connect UI to backend endpoints and handle empty/error states.
- Add simple usability pass for readability and navigation flow.

**Deliverables**
- Working dashboard with end-to-end live data.
- Watchlist configuration interface.
- Explainability view showing evidence behind each alert.

**Exit Criteria**
- A user can configure targets, view trends, and inspect alert evidence without developer support.
- Core MVP workflow works in a clean demo run from ingestion to dashboard output.

## Phase 5: Stabilization, Validation, and MVP Release (Week 6)
**Goal:** Improve reliability and prepare for MVP handoff/demo.

**Key Activities**
- Add targeted tests:
  - Ingestion normalization and deduplication.
  - Relevance/entity processing.
  - Risk aggregation and spike detection.
- Run performance checks on expected MVP data volume.
- Harden operational concerns:
  - Graceful error handling and retry policies.
  - Secret management and configuration validation.
- Execute UAT-style walkthroughs with representative scenarios.
- Document known limitations and next-phase recommendations.

**Deliverables**
- MVP release candidate.
- Test summary and defect fixes for critical path issues.
- Deployment/runbook documentation and demo script.

**Exit Criteria**
- No critical defects in end-to-end flow.
- MVP is stable enough for stakeholder demo and early user feedback.

## Cross-Phase Management Practices
- Keep one prioritized backlog for defects and improvements discovered during each phase.
- Use weekly checkpoints to validate scope and prevent phase spillover.
- Track baseline metrics from Phase 2 onward:
  - Relevance precision sample.
  - Number of flagged events per day.
  - End-to-end latency from ingestion to dashboard visibility.
- Defer non-critical polish to post-MVP unless it blocks adoption.
