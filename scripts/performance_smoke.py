from __future__ import annotations

import argparse
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, delete

from app.db.session import engine, init_db
from app.models.article import Article, ArticleEntityLink, Entity
from app.models.ingestion import IngestionRun
from app.models.risk import ArticleRiskScore, EntityRiskSnapshot
from app.models.watchlist import WatchlistItem
from app.services.processing import run_processing_cycle
from app.services.risk import run_risk_scoring_cycle


@dataclass
class PhaseTiming:
    name: str
    seconds: float


def _make_article(index: int, published_at: datetime) -> Article:
    company = "Intel" if index % 2 == 0 else "TSMC"
    region = "Panama Canal" if index % 3 == 0 else "Taiwan"
    commodity = "semiconductors" if index % 4 else "copper"
    title = f"{company} warns {region} disruption is delaying {commodity} shipments"
    body = (
        f"{company} warns that {region} congestion is creating a supply chain disruption. "
        f"The resulting shipment delays are increasing risk for {commodity} capacity planning."
    )
    return Article(
        source_name="Performance Feed",
        source_feed_url="https://feeds.example.com/performance",
        source_article_id=f"perf-{index}",
        title=title,
        url=f"https://example.com/performance/{index}",
        published_at=published_at,
        summary="Synthetic performance scenario for MVP validation.",
        normalized_content=body,
        content_hash=f"perf-hash-{index}",
    )


def seed_dataset(article_count: int) -> None:
    init_db()
    with Session(engine) as session:
        session.exec(delete(ArticleRiskScore))
        session.exec(delete(EntityRiskSnapshot))
        session.exec(delete(ArticleEntityLink))
        session.exec(delete(Entity))
        session.exec(delete(WatchlistItem))
        session.exec(delete(IngestionRun))
        session.exec(delete(Article))

        session.add_all(
            [
                WatchlistItem(display_name="Intel", entity_type="company", query_hint="intel corporation"),
                WatchlistItem(display_name="TSMC", entity_type="company", query_hint="taiwan semiconductor"),
                WatchlistItem(display_name="Panama Canal", entity_type="region", query_hint="panama canal"),
                WatchlistItem(display_name="Semiconductors", entity_type="commodity", query_hint="chips"),
            ]
        )

        start = datetime.now(UTC) - timedelta(days=max(article_count // 50, 1))
        for index in range(article_count):
            session.add(_make_article(index, start + timedelta(minutes=index * 5)))
        session.commit()


def timed_run(article_count: int) -> tuple[list[PhaseTiming], dict[str, object]]:
    seed_dataset(article_count)

    timings: list[PhaseTiming] = []

    processing_started = time.perf_counter()
    processing_stats = run_processing_cycle()
    timings.append(
        PhaseTiming(name="processing", seconds=round(time.perf_counter() - processing_started, 3))
    )

    risk_started = time.perf_counter()
    risk_stats = run_risk_scoring_cycle()
    timings.append(PhaseTiming(name="risk", seconds=round(time.perf_counter() - risk_started, 3)))

    summary = {
        "article_count": article_count,
        "processing_stats": asdict(processing_stats),
        "risk_stats": asdict(risk_stats),
    }
    return timings, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 performance smoke check")
    parser.add_argument("--articles", type=int, default=250, help="Synthetic article volume to seed")
    args = parser.parse_args()

    timings, summary = timed_run(article_count=args.articles)

    print("Performance smoke summary")
    for timing in timings:
        print(f"- {timing.name}: {timing.seconds:.3f}s")
    print(summary)


if __name__ == "__main__":
    main()
