from dataclasses import dataclass

from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.db.session import engine
from app.models.article import Article
from app.models.watchlist import WatchlistItem
from app.services.processing import run_processing_cycle


@dataclass
class WatchlistMutationResult:
    item: WatchlistItem
    reprocessing_triggered: bool


def list_watchlist_items() -> list[WatchlistItem]:
    with Session(engine) as session:
        return session.exec(select(WatchlistItem).order_by(WatchlistItem.display_name)).all()


def _normalize_watchlist_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _queue_articles_for_reprocessing(session: Session) -> None:
    articles = session.exec(select(Article)).all()
    for article in articles:
        article.processing_status = "pending"
        session.add(article)


def create_watchlist_item(
    display_name: str,
    entity_type: str,
    query_hint: str | None = None,
    is_active: bool = True,
    settings: Settings | None = None,
) -> WatchlistMutationResult:
    app_settings = settings or get_settings()
    with Session(engine) as session:
        item = WatchlistItem(
            display_name=display_name.strip(),
            entity_type=entity_type.strip(),
            query_hint=_normalize_watchlist_value(query_hint),
            is_active=is_active,
        )
        session.add(item)
        _queue_articles_for_reprocessing(session)
        session.commit()
        session.refresh(item)

    run_processing_cycle(app_settings)
    return WatchlistMutationResult(item=item, reprocessing_triggered=True)


def update_watchlist_item(
    item_id: int,
    display_name: str,
    entity_type: str,
    query_hint: str | None = None,
    is_active: bool = True,
    settings: Settings | None = None,
) -> WatchlistMutationResult | None:
    app_settings = settings or get_settings()
    with Session(engine) as session:
        item = session.get(WatchlistItem, item_id)
        if item is None:
            return None
        item.display_name = display_name.strip()
        item.entity_type = entity_type.strip()
        item.query_hint = _normalize_watchlist_value(query_hint)
        item.is_active = is_active
        _queue_articles_for_reprocessing(session)
        session.add(item)
        session.commit()
        session.refresh(item)

    run_processing_cycle(app_settings)
    return WatchlistMutationResult(item=item, reprocessing_triggered=True)


def delete_watchlist_item(item_id: int, settings: Settings | None = None) -> WatchlistMutationResult | None:
    app_settings = settings or get_settings()
    with Session(engine) as session:
        item = session.get(WatchlistItem, item_id)
        if item is None:
            return None
        session.delete(item)
        _queue_articles_for_reprocessing(session)
        session.commit()

    run_processing_cycle(app_settings)
    return WatchlistMutationResult(item=item, reprocessing_triggered=True)
