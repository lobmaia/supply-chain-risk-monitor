import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.db.session import engine, init_db
from app.main import app


@pytest.fixture(autouse=True)
def disable_background_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    get_settings.cache_clear()
    SQLModel.metadata.drop_all(engine)
    init_db()
    yield
    SQLModel.metadata.drop_all(engine)
    init_db()
    get_settings.cache_clear()


def test_health_check() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_summary_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/summary")

    assert response.status_code == 200
    assert set(response.json()) == {
        "watchlist_items",
        "articles",
        "relevant_articles",
        "phase2_entity_links",
        "article_risk_scores",
        "entity_risk_snapshots",
        "ingestion_runs",
    }
