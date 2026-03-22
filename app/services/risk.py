import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, delete, select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import engine
from app.models.article import Article, ArticleEntityLink, Entity
from app.models.risk import ArticleRiskScore, EntityRiskSnapshot

logger = get_logger(__name__)

RISK_SIGNAL_WEIGHTS: dict[str, float] = {
    "strike": 0.18,
    "fire": 0.18,
    "shutdown": 0.18,
    "shortage": 0.16,
    "delay": 0.14,
    "delays": 0.14,
    "disruption": 0.16,
    "bottleneck": 0.14,
    "sanction": 0.18,
    "tariff": 0.14,
    "cyberattack": 0.2,
    "bankruptcy": 0.2,
    "recall": 0.14,
    "congestion": 0.12,
    "reroute": 0.12,
}

SEVERE_EVENT_WEIGHTS: dict[str, float] = {
    "factory fire": 0.22,
    "plant fire": 0.22,
    "port strike": 0.22,
    "canal congestion": 0.18,
    "shipment delays": 0.18,
    "supply chain disruption": 0.2,
}


@dataclass
class RiskScoringStats:
    status: str = "success"
    scored_article_count: int = 0
    entity_snapshot_count: int = 0
    spike_count: int = 0
    last_scored_at: datetime | None = None
    error_count: int = 0
    error_message: str | None = None


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def score_article_risk(article: Article) -> tuple[float, dict[str, object]]:
    text = _normalize(article.normalized_content or article.title)
    title = _normalize(article.title)
    score = round(article.relevance_score * 0.55, 3)
    matched_signals: list[str] = []
    matched_severity: list[str] = []

    for phrase, weight in RISK_SIGNAL_WEIGHTS.items():
        if phrase in text:
            score += weight
            matched_signals.append(phrase)

    for phrase, weight in SEVERE_EVENT_WEIGHTS.items():
        if phrase in text:
            score += weight
            matched_severity.append(phrase)

    title_bonus = (
        0.08 if any(term in title for term in ("warns", "halts", "disrupts", "delays")) else 0.0
    )
    watchlist_bonus = min(article.matched_watchlist_count * 0.05, 0.15)
    score += title_bonus + watchlist_bonus

    factors = {
        "base_relevance": round(article.relevance_score * 0.55, 3),
        "matched_signals": matched_signals,
        "matched_severity_events": matched_severity,
        "title_bonus": round(title_bonus, 3),
        "watchlist_bonus": round(watchlist_bonus, 3),
        "watchlist_match_count": article.matched_watchlist_count,
    }

    return max(0.0, min(round(score, 3), 1.0)), factors


def _refresh_article_scores(session: Session, stats: RiskScoringStats) -> None:
    relevant_articles = session.exec(
        select(Article).where(
            Article.processing_status == "processed",
            Article.is_relevant.is_(True),
        )
    ).all()
    relevant_article_ids = {article.id for article in relevant_articles if article.id is not None}

    stale_scores = session.exec(select(ArticleRiskScore)).all()
    for stale_score in stale_scores:
        if stale_score.article_id not in relevant_article_ids:
            session.delete(stale_score)

    for article in relevant_articles:
        risk_score, factors = score_article_risk(article)
        existing_score = session.exec(
            select(ArticleRiskScore).where(ArticleRiskScore.article_id == article.id)
        ).first()
        if existing_score is None:
            session.add(
                ArticleRiskScore(
                    article_id=article.id,
                    relevance_score=article.relevance_score,
                    risk_score=risk_score,
                    scoring_notes=json.dumps(factors),
                )
            )
        else:
            existing_score.relevance_score = article.relevance_score
            existing_score.risk_score = risk_score
            existing_score.scoring_notes = json.dumps(factors)
        stats.scored_article_count += 1
        stats.last_scored_at = datetime.now(UTC)


def _build_entity_snapshots(
    session: Session,
    settings: Settings,
) -> tuple[int, int]:
    rows = session.exec(
        select(Entity, Article, ArticleRiskScore)
        .join(ArticleEntityLink, ArticleEntityLink.entity_id == Entity.id)
        .join(Article, Article.id == ArticleEntityLink.article_id)
        .join(ArticleRiskScore, ArticleRiskScore.article_id == Article.id)
        .where(Article.is_relevant.is_(True))
    ).all()

    grouped_scores: dict[tuple[int, object], list[float]] = defaultdict(list)
    for entity, article, article_risk in rows:
        grouped_scores[(entity.id, article.published_at.astimezone(UTC).date())].append(
            article_risk.risk_score
        )

    session.exec(delete(EntityRiskSnapshot))

    snapshots_by_entity: dict[int, list[EntityRiskSnapshot]] = defaultdict(list)
    snapshot_count = 0
    spike_count = 0

    for (entity_id, snapshot_date), scores in sorted(
        grouped_scores.items(), key=lambda item: item[0][1]
    ):
        article_volume = len(scores)
        average_score = sum(scores) / article_volume
        volume_multiplier = min(1.0 + (0.05 * max(article_volume - 1, 0)), 1.2)
        aggregated_score = max(0.0, min(round(average_score * volume_multiplier, 3), 1.0))

        snapshot = EntityRiskSnapshot(
            entity_id=entity_id,
            snapshot_date=snapshot_date,
            aggregated_risk_score=aggregated_score,
            article_volume=article_volume,
        )
        snapshots_by_entity[entity_id].append(snapshot)
        snapshot_count += 1

    for entity_snapshots in snapshots_by_entity.values():
        entity_snapshots.sort(key=lambda snapshot: snapshot.snapshot_date)
        for index, snapshot in enumerate(entity_snapshots):
            baseline_window = entity_snapshots[
                max(0, index - settings.risk_spike_baseline_points) : index
            ]
            if baseline_window:
                baseline = sum(
                    item.aggregated_risk_score for item in baseline_window
                ) / len(baseline_window)
                delta_trigger = baseline + settings.risk_spike_delta_threshold
                ratio_trigger = baseline * settings.risk_spike_ratio_threshold
                if (
                    snapshot.aggregated_risk_score >= settings.risk_article_flag_threshold
                    and snapshot.aggregated_risk_score >= max(delta_trigger, ratio_trigger)
                ):
                    snapshot.spike_flag = True
                    spike_count += 1
            session.add(snapshot)

    return snapshot_count, spike_count


def run_risk_scoring_cycle(settings: Settings | None = None) -> RiskScoringStats:
    app_settings = settings or get_settings()
    stats = RiskScoringStats()

    if not app_settings.risk_scoring_enabled:
        return stats

    try:
        with Session(engine) as session:
            _refresh_article_scores(session, stats)
            snapshot_count, spike_count = _build_entity_snapshots(session, app_settings)
            stats.entity_snapshot_count = snapshot_count
            stats.spike_count = spike_count
            session.commit()
    except Exception as exc:
        stats.status = "failed"
        stats.error_count += 1
        stats.error_message = str(exc)
        logger.exception("risk_scoring_cycle_failed")
    else:
        logger.info(
            "risk_scoring_cycle_completed",
            extra={
                "scored_article_count": stats.scored_article_count,
                "entity_snapshot_count": stats.entity_snapshot_count,
                "spike_count": stats.spike_count,
            },
        )

    return stats


def get_risk_overview() -> dict[str, int | str | None]:
    with Session(engine) as session:
        article_score_count = len(session.exec(select(ArticleRiskScore)).all())
        snapshot_count = len(session.exec(select(EntityRiskSnapshot)).all())
        spike_count = len(
            session.exec(
                select(EntityRiskSnapshot).where(EntityRiskSnapshot.spike_flag.is_(True))
            ).all()
        )
        latest_article_score = session.exec(
            select(ArticleRiskScore).order_by(ArticleRiskScore.created_at.desc())
        ).first()

    return {
        "article_risk_scores": article_score_count,
        "entity_risk_snapshots": snapshot_count,
        "spike_snapshots": spike_count,
        "last_scored_at": latest_article_score.created_at if latest_article_score else None,
    }


def get_current_entity_risk(limit: int = 50) -> list[dict[str, object]]:
    with Session(engine) as session:
        entities = session.exec(select(Entity)).all()
        snapshots = session.exec(select(EntityRiskSnapshot)).all()

    latest_by_entity: dict[int, EntityRiskSnapshot] = {}
    for snapshot in snapshots:
        current = latest_by_entity.get(snapshot.entity_id)
        if current is None or snapshot.snapshot_date > current.snapshot_date:
            latest_by_entity[snapshot.entity_id] = snapshot

    payload: list[dict[str, object]] = []
    for entity in entities:
        snapshot = latest_by_entity.get(entity.id)
        if snapshot is None:
            continue
        payload.append(
            {
                "entity_id": entity.id,
                "entity_name": entity.name,
                "entity_type": entity.entity_type,
                "snapshot_date": snapshot.snapshot_date,
                "aggregated_risk_score": snapshot.aggregated_risk_score,
                "article_volume": snapshot.article_volume,
                "spike_flag": snapshot.spike_flag,
            }
        )

    return sorted(
        payload,
        key=lambda item: (item["aggregated_risk_score"], item["article_volume"]),
        reverse=True,
    )[:limit]


def get_entity_risk_history(entity_id: int, limit: int = 30) -> list[dict[str, object]]:
    with Session(engine) as session:
        entity = session.get(Entity, entity_id)
        if entity is None:
            return []
        snapshots = session.exec(
            select(EntityRiskSnapshot)
            .where(EntityRiskSnapshot.entity_id == entity_id)
            .order_by(EntityRiskSnapshot.snapshot_date.desc())
        ).all()

    return [
        {
            "entity_id": entity.id,
            "entity_name": entity.name,
            "entity_type": entity.entity_type,
            "snapshot_date": snapshot.snapshot_date,
            "aggregated_risk_score": snapshot.aggregated_risk_score,
            "article_volume": snapshot.article_volume,
            "spike_flag": snapshot.spike_flag,
        }
        for snapshot in snapshots[:limit]
    ]


def get_flagged_events(
    limit: int = 20,
    threshold: float | None = None,
    settings: Settings | None = None,
) -> list[dict[str, object]]:
    app_settings = settings or get_settings()
    flag_threshold = threshold or app_settings.risk_article_flag_threshold

    with Session(engine) as session:
        rows = session.exec(
            select(Article, ArticleRiskScore)
            .join(ArticleRiskScore, ArticleRiskScore.article_id == Article.id)
            .where(ArticleRiskScore.risk_score >= flag_threshold)
            .order_by(Article.published_at.desc())
        ).all()

        if not rows:
            return []

        article_ids = [article.id for article, _ in rows]
        entity_rows = session.exec(
            select(ArticleEntityLink, Entity)
            .join(Entity, Entity.id == ArticleEntityLink.entity_id)
            .where(ArticleEntityLink.article_id.in_(article_ids))
        ).all()
        snapshot_rows = session.exec(select(EntityRiskSnapshot)).all()

    entities_by_article: dict[int, list[dict[str, object]]] = defaultdict(list)
    for link, entity in entity_rows:
        entities_by_article[link.article_id].append(
            {"entity_id": entity.id, "entity_name": entity.name, "entity_type": entity.entity_type}
        )

    spike_dates = {
        (snapshot.entity_id, snapshot.snapshot_date)
        for snapshot in snapshot_rows
        if snapshot.spike_flag
    }

    payload: list[dict[str, object]] = []
    for article, article_risk in rows[:limit]:
        linked_entities = entities_by_article.get(article.id, [])
        snapshot_date = article.published_at.astimezone(UTC).date()
        spike_entities = [
            entity["entity_name"]
            for entity in linked_entities
            if (entity["entity_id"], snapshot_date) in spike_dates
        ]
        payload.append(
            {
                "article_id": article.id,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at,
                "risk_score": article_risk.risk_score,
                "relevance_score": article_risk.relevance_score,
                "entities": linked_entities,
                "spike_entities": spike_entities,
                "scoring_notes": json.loads(article_risk.scoring_notes or "{}"),
            }
        )

    return payload


def get_flagged_event_detail(article_id: int) -> dict[str, object] | None:
    with Session(engine) as session:
        row = session.exec(
            select(Article, ArticleRiskScore)
            .join(ArticleRiskScore, ArticleRiskScore.article_id == Article.id)
            .where(Article.id == article_id)
        ).first()
        if row is None:
            return None

        article, article_risk = row
        entity_rows = session.exec(
            select(ArticleEntityLink, Entity)
            .join(Entity, Entity.id == ArticleEntityLink.entity_id)
            .where(ArticleEntityLink.article_id == article_id)
        ).all()
        snapshot_date = article.published_at.astimezone(UTC).date()
        snapshot_rows = session.exec(
            select(EntityRiskSnapshot).where(EntityRiskSnapshot.snapshot_date == snapshot_date)
        ).all()

    linked_entities = [
        {
            "entity_id": entity.id,
            "entity_name": entity.name,
            "entity_type": entity.entity_type,
            "relation_type": link.relation_type,
            "confidence": link.confidence,
        }
        for link, entity in entity_rows
    ]
    snapshots_by_entity = {snapshot.entity_id: snapshot for snapshot in snapshot_rows}
    impacted_entities = []
    for entity in linked_entities:
        snapshot = snapshots_by_entity.get(entity["entity_id"])
        impacted_entities.append(
            {
                **entity,
                "snapshot_date": snapshot.snapshot_date if snapshot else snapshot_date,
                "aggregated_risk_score": snapshot.aggregated_risk_score if snapshot else None,
                "article_volume": snapshot.article_volume if snapshot else 0,
                "spike_flag": snapshot.spike_flag if snapshot else False,
            }
        )

    return {
        "article_id": article.id,
        "title": article.title,
        "summary": article.summary,
        "url": article.url,
        "source_name": article.source_name,
        "published_at": article.published_at,
        "risk_score": article_risk.risk_score,
        "relevance_score": article_risk.relevance_score,
        "relevance_reason": json.loads(article.relevance_reason or "[]"),
        "matched_watchlist_count": article.matched_watchlist_count,
        "scoring_notes": json.loads(article_risk.scoring_notes or "{}"),
        "entities": impacted_entities,
    }


def get_dashboard_overview(entity_limit: int = 8, flagged_limit: int = 8) -> dict[str, object]:
    current_entities = get_current_entity_risk(limit=entity_limit)
    flagged_events = get_flagged_events(limit=flagged_limit)
    return {
        "summary": get_risk_overview(),
        "top_entities": current_entities,
        "flagged_events": flagged_events,
        "spike_entity_count": sum(1 for entity in current_entities if entity["spike_flag"]),
    }
