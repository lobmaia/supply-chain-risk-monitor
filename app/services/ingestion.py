import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from sqlmodel import Session, desc, or_, select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import engine
from app.models.article import Article
from app.models.ingestion import IngestionRun
from app.services.processing import run_processing_cycle

logger = get_logger(__name__)


@dataclass
class NormalizedArticle:
    source_name: str
    source_feed_url: str
    source_article_id: str | None
    title: str
    url: str
    published_at: datetime
    author: str | None
    summary: str | None
    raw_content: str | None
    raw_payload: str
    normalized_content: str | None
    content_hash: str


@dataclass
class IngestionStats:
    source_type: str = "rss"
    source_name: str = "rss"
    status: str = "success"
    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    last_successful_published_at: datetime | None = None
    error_message: str | None = None


def get_feed_urls(settings: Settings | None = None) -> list[str]:
    app_settings = settings or get_settings()
    return [url.strip() for url in app_settings.rss_feed_urls.split(",") if url.strip()]


def normalize_text(value: str | None) -> str | None:
    if not value:
        return None

    normalized = " ".join(value.split())
    return normalized or None


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(UTC)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_content_hash(title: str, url: str, published_at: datetime) -> str:
    hash_input = f"{title.strip().lower()}|{url.strip().lower()}|{published_at.isoformat()}"
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def normalize_rss_item(item: ElementTree.Element, feed_url: str, default_source_name: str) -> NormalizedArticle:
    title = normalize_text(item.findtext("title")) or "Untitled Article"
    url = normalize_text(item.findtext("link"))
    if not url:
        raise ValueError("RSS item missing link")

    source_name = (
        normalize_text(item.findtext("source"))
        or normalize_text(item.findtext("{http://purl.org/rss/1.0/modules/content/}source"))
        or default_source_name
    )
    description = normalize_text(item.findtext("description"))
    raw_content = (
        normalize_text(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"))
        or description
    )
    author = normalize_text(item.findtext("author")) or normalize_text(
        item.findtext("{http://purl.org/dc/elements/1.1/}creator")
    )
    published_at = parse_datetime(item.findtext("pubDate"))
    source_article_id = normalize_text(item.findtext("guid")) or url

    raw_payload = {
        "title": item.findtext("title"),
        "link": item.findtext("link"),
        "guid": item.findtext("guid"),
        "pubDate": item.findtext("pubDate"),
        "author": item.findtext("author"),
        "description": item.findtext("description"),
        "content:encoded": item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"),
    }

    normalized_content = normalize_text(" ".join(part for part in [title, description, raw_content] if part))
    content_hash = build_content_hash(title=title, url=url, published_at=published_at)

    return NormalizedArticle(
        source_name=source_name,
        source_feed_url=feed_url,
        source_article_id=source_article_id,
        title=title,
        url=url,
        published_at=published_at,
        author=author,
        summary=description,
        raw_content=raw_content,
        raw_payload=json.dumps(raw_payload, default=str),
        normalized_content=normalized_content,
        content_hash=content_hash,
    )


def parse_rss_feed(xml_content: str, feed_url: str) -> list[NormalizedArticle]:
    root = ElementTree.fromstring(xml_content)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS feed missing channel")

    default_source_name = normalize_text(channel.findtext("title")) or urlparse(feed_url).netloc
    articles: list[NormalizedArticle] = []
    for item in channel.findall("item"):
        articles.append(normalize_rss_item(item, feed_url=feed_url, default_source_name=default_source_name))
    return articles


def fetch_feed_content(
    feed_url: str,
    settings: Settings,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> str:
    attempts = settings.ingestion_max_retries
    last_error: Exception | None = None
    factory = client_factory or (
        lambda: httpx.Client(
            timeout=settings.ingestion_request_timeout_seconds,
            headers={"User-Agent": "supply-chain-risk-monitor/0.1"},
            follow_redirects=True,
        )
    )

    for attempt in range(1, attempts + 1):
        try:
            with factory() as client:
                response = client.get(feed_url)
                response.raise_for_status()
                return response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            logger.warning(
                "ingestion_fetch_retry",
                extra={"feed_url": feed_url, "attempt": attempt, "max_attempts": attempts},
            )
            if attempt < attempts:
                time.sleep(settings.ingestion_retry_backoff_seconds * attempt)

    assert last_error is not None
    raise last_error


def upsert_article(session: Session, article: NormalizedArticle, stats: IngestionStats) -> None:
    existing = session.exec(
        select(Article).where(or_(Article.url == article.url, Article.content_hash == article.content_hash))
    ).first()

    if existing is None:
        session.add(
            Article(
                source_name=article.source_name,
                source_feed_url=article.source_feed_url,
                source_article_id=article.source_article_id,
                title=article.title,
                url=article.url,
                published_at=article.published_at,
                author=article.author,
                summary=article.summary,
                raw_content=article.raw_content,
                raw_payload=article.raw_payload,
                normalized_content=article.normalized_content,
                content_hash=article.content_hash,
            )
        )
        stats.inserted_count += 1
        return

    existing.updated_at = datetime.now(UTC)
    if existing.url == article.url:
        existing.source_name = article.source_name
        existing.source_feed_url = article.source_feed_url
        existing.source_article_id = article.source_article_id
        existing.title = article.title
        existing.published_at = article.published_at
        existing.author = article.author
        existing.summary = article.summary
        existing.raw_content = article.raw_content
        existing.raw_payload = article.raw_payload
        existing.normalized_content = article.normalized_content
        existing.content_hash = article.content_hash
        stats.updated_count += 1
        return

    stats.duplicate_count += 1


def persist_ingestion_run(stats: IngestionStats, started_at: datetime) -> IngestionRun:
    with Session(engine) as session:
        ingestion_run = IngestionRun(
            source_type=stats.source_type,
            source_name=stats.source_name,
            status=stats.status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            fetched_count=stats.fetched_count,
            inserted_count=stats.inserted_count,
            updated_count=stats.updated_count,
            duplicate_count=stats.duplicate_count,
            error_count=stats.error_count,
            last_successful_published_at=stats.last_successful_published_at,
            error_message=stats.error_message,
        )
        session.add(ingestion_run)
        session.commit()
        session.refresh(ingestion_run)
        return ingestion_run


def run_ingestion_cycle(
    settings: Settings | None = None,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> IngestionRun:
    app_settings = settings or get_settings()
    stats = IngestionStats(source_name="configured_rss_feeds")
    started_at = datetime.now(UTC)
    feed_urls = get_feed_urls(app_settings)

    try:
        with Session(engine) as session:
            for feed_url in feed_urls:
                try:
                    xml_content = fetch_feed_content(feed_url, app_settings, client_factory=client_factory)
                    normalized_articles = parse_rss_feed(xml_content, feed_url)
                except Exception as exc:
                    stats.error_count += 1
                    stats.error_message = str(exc)
                    logger.exception("ingestion_feed_failed", extra={"feed_url": feed_url})
                    continue

                stats.fetched_count += len(normalized_articles)
                for article in normalized_articles:
                    upsert_article(session, article, stats)
                    if (
                        stats.last_successful_published_at is None
                        or article.published_at > stats.last_successful_published_at
                    ):
                        stats.last_successful_published_at = article.published_at

            session.commit()
    except Exception as exc:
        stats.status = "failed"
        stats.error_count += 1
        stats.error_message = str(exc)
        logger.exception("ingestion_cycle_failed", extra={"source_type": stats.source_type})
    else:
        if stats.error_count > 0:
            stats.status = "completed_with_errors"

        if app_settings.processing_enabled:
            processing_stats = run_processing_cycle(app_settings)
            if processing_stats.status != "success":
                stats.status = "completed_with_errors"
                stats.error_count += processing_stats.error_count
                stats.error_message = processing_stats.error_message

        logger.info(
            "ingestion_cycle_completed",
            extra={
                "source_type": stats.source_type,
                "fetched_count": stats.fetched_count,
                "inserted_count": stats.inserted_count,
                "updated_count": stats.updated_count,
                "duplicate_count": stats.duplicate_count,
                "error_count": stats.error_count,
                "status": stats.status,
            },
        )

    return persist_ingestion_run(stats, started_at=started_at)


def get_ingestion_overview() -> dict[str, int | str | None]:
    with Session(engine) as session:
        latest_run = session.exec(select(IngestionRun).order_by(desc(IngestionRun.started_at))).first()
        total_runs = len(session.exec(select(IngestionRun)).all())
        total_articles = len(session.exec(select(Article)).all())
        failed_runs = len(session.exec(select(IngestionRun).where(IngestionRun.status == "failed")).all())

    return {
        "total_runs": total_runs,
        "failed_runs": failed_runs,
        "total_articles": total_articles,
        "last_run_status": latest_run.status if latest_run else None,
        "last_run_started_at": latest_run.started_at if latest_run else None,
        "last_run_completed_at": latest_run.completed_at if latest_run else None,
        "last_successful_published_at": (
            latest_run.last_successful_published_at if latest_run else None
        ),
    }
