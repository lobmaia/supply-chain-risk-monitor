import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, delete, desc, select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import engine
from app.models.article import Article, ArticleEntityLink, Entity
from app.models.watchlist import WatchlistItem
from app.services.risk import run_risk_scoring_cycle

logger = get_logger(__name__)

POSITIVE_SIGNALS: dict[str, float] = {
    "supply chain": 0.2,
    "shipment": 0.15,
    "shipments": 0.15,
    "logistics": 0.15,
    "factory": 0.18,
    "plant": 0.12,
    "port": 0.2,
    "tariff": 0.18,
    "sanction": 0.18,
    "strike": 0.22,
    "disruption": 0.22,
    "shortage": 0.2,
    "delay": 0.16,
    "delays": 0.16,
    "bottleneck": 0.18,
    "customs": 0.12,
    "freight": 0.16,
    "semiconductor": 0.14,
    "chip": 0.14,
    "copper": 0.14,
    "steel": 0.12,
    "oil": 0.12,
}

NEGATIVE_SIGNALS: dict[str, float] = {
    "earnings": 0.18,
    "sports": 0.22,
    "entertainment": 0.18,
    "celebrity": 0.22,
    "fashion": 0.12,
    "recipe": 0.18,
}

REGION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Panama Canal": ("panama canal",),
    "Red Sea": ("red sea",),
    "Taiwan": ("taiwan",),
    "China": ("china",),
    "United States": ("united states", "u.s.", "us "),
    "Mexico": ("mexico",),
    "Europe": ("europe", "european union", "eu "),
}

COMMODITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Semiconductors": ("semiconductor", "semiconductors", "chip", "chips"),
    "Copper": ("copper",),
    "Steel": ("steel",),
    "Oil": ("oil", "crude"),
    "Automotive": ("automotive", "vehicle", "vehicles", "auto parts"),
}


@dataclass
class ProcessingStats:
    status: str = "success"
    processed_count: int = 0
    relevant_count: int = 0
    not_relevant_count: int = 0
    entity_link_count: int = 0
    watchlist_match_count: int = 0
    error_count: int = 0
    last_processed_at: datetime | None = None
    error_message: str | None = None


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def parse_watchlist_seed_items(settings: Settings | None = None) -> list[WatchlistItem]:
    app_settings = settings or get_settings()
    items: list[WatchlistItem] = []
    for raw_item in app_settings.watchlist_seed_items.split(","):
        item = raw_item.strip()
        if not item:
            continue
        display_name, entity_type, *rest = [part.strip() for part in item.split("|")]
        query_hint = rest[0] if rest else None
        items.append(
            WatchlistItem(
                display_name=display_name,
                entity_type=entity_type,
                query_hint=query_hint or None,
                is_active=True,
            )
        )
    return items


def ensure_watchlist_seed_data(session: Session, settings: Settings | None = None) -> None:
    if session.exec(select(WatchlistItem)).first() is not None:
        return
    if session.exec(select(Article)).first() is not None:
        return

    for item in parse_watchlist_seed_items(settings):
        session.add(item)
    session.commit()


def score_article_relevance(article: Article, threshold: float) -> tuple[float, list[str]]:
    text = _normalize(article.normalized_content or article.title)
    score = 0.0
    reasons: list[str] = []

    for phrase, weight in POSITIVE_SIGNALS.items():
        if phrase in text:
            score += weight
            reasons.append(f"matched:{phrase}")

    for phrase, weight in NEGATIVE_SIGNALS.items():
        if phrase in text:
            score -= weight
            reasons.append(f"downranked:{phrase}")

    if article.summary and "disrupt" in _normalize(article.summary):
        score += 0.1
        reasons.append("summary:disruption")

    if "supply chain" in text and any(keyword in text for keyword in ("risk", "delay", "strike", "shortage")):
        score += 0.1
        reasons.append("compound:supply_chain_risk")

    bounded_score = max(0.0, min(round(score, 3), 1.0))
    if bounded_score >= threshold and not reasons:
        reasons.append("threshold_met")
    return bounded_score, reasons


def _match_watchlist_items(session: Session, article_text: str) -> list[WatchlistItem]:
    matched_items: list[WatchlistItem] = []
    active_items = session.exec(select(WatchlistItem).where(WatchlistItem.is_active.is_(True))).all()
    for item in active_items:
        candidates = [item.display_name, item.query_hint]
        if any(candidate and _normalize(candidate) in article_text for candidate in candidates):
            matched_items.append(item)
    return matched_items


def _ensure_entity(session: Session, name: str, entity_type: str, external_ref: str | None = None) -> Entity:
    existing = session.exec(
        select(Entity).where(Entity.name == name, Entity.entity_type == entity_type)
    ).first()
    if existing is not None:
        if external_ref and existing.external_ref != external_ref:
            existing.external_ref = external_ref
        return existing

    entity = Entity(name=name, entity_type=entity_type, external_ref=external_ref)
    session.add(entity)
    session.flush()
    return entity


def _link_entity(
    session: Session,
    article_id: int,
    entity_name: str,
    entity_type: str,
    relation_type: str,
    confidence: float,
    external_ref: str | None = None,
) -> None:
    entity = _ensure_entity(session, name=entity_name, entity_type=entity_type, external_ref=external_ref)
    session.add(
        ArticleEntityLink(
            article_id=article_id,
            entity_id=entity.id,
            relation_type=relation_type,
            confidence=confidence,
        )
    )


def extract_and_link_entities(
    session: Session,
    article: Article,
    score: float,
) -> tuple[int, int]:
    text = _normalize(article.normalized_content or article.title)
    link_count = 0
    watchlist_match_count = 0
    seen_links: set[tuple[str, str, str]] = set()

    matched_items = _match_watchlist_items(session, text)
    for item in matched_items:
        link_key = (item.display_name, item.entity_type, "watchlist_match")
        if link_key in seen_links:
            continue
        _link_entity(
            session,
            article_id=article.id,
            entity_name=item.display_name,
            entity_type=item.entity_type,
            relation_type="watchlist_match",
            confidence=max(score, 0.5),
            external_ref=item.query_hint,
        )
        seen_links.add(link_key)
        link_count += 1
        watchlist_match_count += 1

    for region_name, keywords in REGION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            link_key = (region_name, "region", "regional_exposure")
            if link_key in seen_links:
                continue
            _link_entity(
                session,
                article_id=article.id,
                entity_name=region_name,
                entity_type="region",
                relation_type="regional_exposure",
                confidence=max(score, 0.35),
            )
            seen_links.add(link_key)
            link_count += 1

    for commodity_name, keywords in COMMODITY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            link_key = (commodity_name, "commodity", "commodity_exposure")
            if link_key in seen_links:
                continue
            _link_entity(
                session,
                article_id=article.id,
                entity_name=commodity_name,
                entity_type="commodity",
                relation_type="commodity_exposure",
                confidence=max(score, 0.35),
            )
            seen_links.add(link_key)
            link_count += 1

    return link_count, watchlist_match_count


def process_article(session: Session, article: Article, threshold: float) -> tuple[int, int]:
    score, reasons = score_article_relevance(article, threshold=threshold)
    is_relevant = score >= threshold

    session.exec(delete(ArticleEntityLink).where(ArticleEntityLink.article_id == article.id))

    link_count = 0
    watchlist_match_count = 0
    if is_relevant:
        link_count, watchlist_match_count = extract_and_link_entities(session, article, score)

    article.relevance_score = score
    article.is_relevant = is_relevant
    article.processing_status = "processed"
    article.relevance_reason = json.dumps(reasons)
    article.matched_watchlist_count = watchlist_match_count
    article.processed_at = datetime.now(UTC)
    article.updated_at = datetime.now(UTC)
    session.add(article)

    return link_count, watchlist_match_count


def run_processing_cycle(settings: Settings | None = None) -> ProcessingStats:
    app_settings = settings or get_settings()
    stats = ProcessingStats()

    try:
        with Session(engine) as session:
            ensure_watchlist_seed_data(session, app_settings)
            articles = session.exec(
                select(Article).where(Article.processing_status != "processed").order_by(desc(Article.published_at))
            ).all()

            for article in articles:
                link_count, watchlist_match_count = process_article(
                    session,
                    article,
                    threshold=app_settings.relevance_threshold,
                )
                stats.processed_count += 1
                stats.entity_link_count += link_count
                stats.watchlist_match_count += watchlist_match_count
                if article.is_relevant:
                    stats.relevant_count += 1
                else:
                    stats.not_relevant_count += 1
                stats.last_processed_at = article.processed_at

            session.commit()
    except Exception as exc:
        stats.status = "failed"
        stats.error_count += 1
        stats.error_message = str(exc)
        logger.exception("processing_cycle_failed")
    else:
        if app_settings.risk_scoring_enabled:
            risk_stats = run_risk_scoring_cycle(app_settings)
            if risk_stats.status != "success":
                stats.status = "failed"
                stats.error_count += risk_stats.error_count
                stats.error_message = risk_stats.error_message

        logger.info(
            "processing_cycle_completed",
            extra={
                "processed_count": stats.processed_count,
                "relevant_count": stats.relevant_count,
                "not_relevant_count": stats.not_relevant_count,
                "entity_link_count": stats.entity_link_count,
                "watchlist_match_count": stats.watchlist_match_count,
            },
        )

    return stats


def get_processing_overview() -> dict[str, int | str | None]:
    with Session(engine) as session:
        total_articles = len(session.exec(select(Article)).all())
        processed_articles = len(
            session.exec(select(Article).where(Article.processing_status == "processed")).all()
        )
        relevant_articles = len(session.exec(select(Article).where(Article.is_relevant.is_(True))).all())
        total_entities = len(session.exec(select(Entity)).all())
        total_links = len(session.exec(select(ArticleEntityLink)).all())
        latest_processed = session.exec(
            select(Article).where(Article.processed_at.is_not(None)).order_by(desc(Article.processed_at))
        ).first()

    return {
        "total_articles": total_articles,
        "processed_articles": processed_articles,
        "pending_articles": max(total_articles - processed_articles, 0),
        "relevant_articles": relevant_articles,
        "tracked_entities": total_entities,
        "entity_links": total_links,
        "last_processed_at": latest_processed.processed_at if latest_processed else None,
    }
