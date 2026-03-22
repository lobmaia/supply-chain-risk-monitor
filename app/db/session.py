from pathlib import Path

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings

settings = get_settings()


def _ensure_sqlite_directory(database_url: str) -> None:
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        return

    db_path = database_url.removeprefix(sqlite_prefix)
    file_path = Path(db_path)
    if file_path.parent != Path("."):
        file_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)
engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    from app.models.article import Article, ArticleEntityLink, Entity
    from app.models.ingestion import IngestionRun
    from app.models.risk import ArticleRiskScore, EntityRiskSnapshot
    from app.models.watchlist import WatchlistItem

    _ = (
        Article,
        ArticleEntityLink,
        Entity,
        IngestionRun,
        ArticleRiskScore,
        EntityRiskSnapshot,
        WatchlistItem,
    )
    SQLModel.metadata.create_all(engine)
    _migrate_article_table_for_phase_2()


def _migrate_article_table_for_phase_2() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return

    article_columns = {
        "processing_status": "TEXT DEFAULT 'pending'",
        "is_relevant": "BOOLEAN DEFAULT 0",
        "relevance_score": "FLOAT DEFAULT 0.0",
        "relevance_reason": "TEXT",
        "matched_watchlist_count": "INTEGER DEFAULT 0",
        "processed_at": "TIMESTAMP",
    }

    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(article)")).all()
        }
        for column_name, column_sql in article_columns.items():
            if column_name in existing_columns:
                continue
            session.exec(text(f"ALTER TABLE article ADD COLUMN {column_name} {column_sql}"))
        session.commit()
