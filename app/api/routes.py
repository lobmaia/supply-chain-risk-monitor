from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.logging import get_logger
from app.db.session import engine
from app.models.article import Article, ArticleEntityLink
from app.models.ingestion import IngestionRun
from app.models.risk import ArticleRiskScore, EntityRiskSnapshot
from app.models.watchlist import WatchlistItem
from app.services.ingestion import get_ingestion_overview, run_ingestion_cycle
from app.services.processing import get_processing_overview, run_processing_cycle
from app.services.risk import (
    get_dashboard_overview,
    get_current_entity_risk,
    get_entity_risk_history,
    get_flagged_event_detail,
    get_flagged_events,
    get_risk_overview,
    run_risk_scoring_cycle,
)
from app.services.watchlist import (
    create_watchlist_item,
    delete_watchlist_item,
    list_watchlist_items,
    update_watchlist_item,
)

api_router = APIRouter()
logger = get_logger(__name__)


class WatchlistItemPayload(BaseModel):
    display_name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    query_hint: str | None = None
    is_active: bool = True


@api_router.get("/health")
def health_check() -> dict[str, str]:
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive handling
        logger.exception("database_health_check_failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    return {"status": "ok", "database": "connected"}


@api_router.get("/api/v1/summary")
def get_summary() -> dict[str, int]:
    with Session(engine) as session:
        watchlist_count = len(session.exec(select(WatchlistItem)).all())
        article_count = len(session.exec(select(Article)).all())
        relevant_article_count = len(session.exec(select(Article).where(Article.is_relevant.is_(True))).all())
        entity_link_count = len(session.exec(select(ArticleEntityLink)).all())
        article_score_count = len(session.exec(select(ArticleRiskScore)).all())
        entity_snapshot_count = len(session.exec(select(EntityRiskSnapshot)).all())
        ingestion_run_count = len(session.exec(select(IngestionRun)).all())

    return {
        "watchlist_items": watchlist_count,
        "articles": article_count,
        "relevant_articles": relevant_article_count,
        "phase2_entity_links": entity_link_count,
        "article_risk_scores": article_score_count,
        "entity_risk_snapshots": entity_snapshot_count,
        "ingestion_runs": ingestion_run_count,
    }


@api_router.get("/api/v1/ingestion/status")
def get_ingestion_status() -> dict[str, int | str | object | None]:
    return get_ingestion_overview()


@api_router.post("/api/v1/ingestion/run")
def trigger_ingestion() -> dict[str, int | str | object | None]:
    run = run_ingestion_cycle()
    return {
        "run_id": run.id,
        "status": run.status,
        "fetched_count": run.fetched_count,
        "inserted_count": run.inserted_count,
        "updated_count": run.updated_count,
        "duplicate_count": run.duplicate_count,
        "error_count": run.error_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "last_successful_published_at": run.last_successful_published_at,
        "error_message": run.error_message,
    }


@api_router.get("/api/v1/processing/status")
def get_processing_status() -> dict[str, int | str | object | None]:
    return get_processing_overview()


@api_router.post("/api/v1/processing/run")
def trigger_processing() -> dict[str, int | str | object | None]:
    stats = run_processing_cycle()
    return {
        "status": stats.status,
        "processed_count": stats.processed_count,
        "relevant_count": stats.relevant_count,
        "not_relevant_count": stats.not_relevant_count,
        "entity_link_count": stats.entity_link_count,
        "watchlist_match_count": stats.watchlist_match_count,
        "error_count": stats.error_count,
        "last_processed_at": stats.last_processed_at,
        "error_message": stats.error_message,
    }


@api_router.get("/api/v1/risk/status")
def get_risk_status() -> dict[str, int | str | object | None]:
    return get_risk_overview()


@api_router.post("/api/v1/risk/run")
def trigger_risk_scoring() -> dict[str, int | str | object | None]:
    stats = run_risk_scoring_cycle()
    return {
        "status": stats.status,
        "scored_article_count": stats.scored_article_count,
        "entity_snapshot_count": stats.entity_snapshot_count,
        "spike_count": stats.spike_count,
        "error_count": stats.error_count,
        "last_scored_at": stats.last_scored_at,
        "error_message": stats.error_message,
    }


@api_router.get("/api/v1/risk/entities/current")
def get_current_risk_entities(limit: int = 50) -> list[dict[str, object]]:
    return get_current_entity_risk(limit=limit)


@api_router.get("/api/v1/risk/entities/{entity_id}/history")
def get_risk_entity_history(entity_id: int, limit: int = 30) -> list[dict[str, object]]:
    history = get_entity_risk_history(entity_id=entity_id, limit=limit)
    if not history:
        raise HTTPException(status_code=404, detail="Entity risk history not found")
    return history


@api_router.get("/api/v1/risk/events/flagged")
def get_risk_flagged_events(limit: int = 20) -> list[dict[str, object]]:
    return get_flagged_events(limit=limit)


@api_router.get("/api/v1/risk/events/{article_id}")
def get_risk_event_detail(article_id: int) -> dict[str, object]:
    detail = get_flagged_event_detail(article_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Flagged event not found")
    return detail


@api_router.get("/api/v1/dashboard/overview")
def get_dashboard_snapshot(entity_limit: int = 8, flagged_limit: int = 8) -> dict[str, object]:
    return get_dashboard_overview(entity_limit=entity_limit, flagged_limit=flagged_limit)


@api_router.get("/api/v1/watchlist")
def get_watchlist() -> list[dict[str, object]]:
    return [
        {
            "id": item.id,
            "display_name": item.display_name,
            "entity_type": item.entity_type,
            "query_hint": item.query_hint,
            "is_active": item.is_active,
            "created_at": item.created_at,
        }
        for item in list_watchlist_items()
    ]


@api_router.post("/api/v1/watchlist")
def create_watchlist(payload: WatchlistItemPayload) -> dict[str, object]:
    result = create_watchlist_item(**payload.model_dump())
    item = result.item
    return {
        "id": item.id,
        "display_name": item.display_name,
        "entity_type": item.entity_type,
        "query_hint": item.query_hint,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "reprocessing_triggered": result.reprocessing_triggered,
    }


@api_router.put("/api/v1/watchlist/{item_id}")
def update_watchlist(item_id: int, payload: WatchlistItemPayload) -> dict[str, object]:
    result = update_watchlist_item(item_id=item_id, **payload.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    item = result.item
    return {
        "id": item.id,
        "display_name": item.display_name,
        "entity_type": item.entity_type,
        "query_hint": item.query_hint,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "reprocessing_triggered": result.reprocessing_triggered,
    }


@api_router.delete("/api/v1/watchlist/{item_id}")
def delete_watchlist(item_id: int) -> dict[str, object]:
    result = delete_watchlist_item(item_id=item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return {
        "id": result.item.id,
        "display_name": result.item.display_name,
        "reprocessing_triggered": result.reprocessing_triggered,
    }
