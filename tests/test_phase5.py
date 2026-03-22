import asyncio
from collections.abc import Iterator

import httpx
import pytest
from sqlmodel import SQLModel

from app.core.config import Settings, get_settings
from app.db.session import engine, init_db
from app.services.ingestion import fetch_feed_content
from app.services.scheduler import run_ingestion_scheduler


@pytest.fixture(autouse=True)
def isolate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    get_settings.cache_clear()
    SQLModel.metadata.drop_all(engine)
    init_db()
    yield
    SQLModel.metadata.drop_all(engine)
    init_db()
    get_settings.cache_clear()


def test_settings_validation_rejects_invalid_phase5_inputs() -> None:
    with pytest.raises(ValueError):
        Settings(ingestion_max_retries=0)

    with pytest.raises(ValueError):
        Settings(rss_feed_urls="not-a-url")

    with pytest.raises(ValueError):
        Settings(frontend_api_base_url="api-without-scheme")

    with pytest.raises(ValueError):
        Settings(watchlist_seed_items="Intel|invalid-type|intel")


def test_fetch_feed_content_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    sleep_calls: list[float] = []

    class StubClient:
        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, _: str) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ReadTimeout("timed out")
            request = httpx.Request("GET", "https://feeds.example.com/supply-chain.xml")
            return httpx.Response(200, content=b"<rss/>", request=request)

    monkeypatch.setattr("app.services.ingestion.time.sleep", lambda seconds: sleep_calls.append(seconds))

    result = fetch_feed_content(
        "https://feeds.example.com/supply-chain.xml",
        Settings(ingestion_max_retries=3, ingestion_retry_backoff_seconds=2.0),
        client_factory=StubClient,
    )

    assert result == "<rss/>"
    assert attempts["count"] == 3
    assert sleep_calls == [2.0, 4.0]


def test_scheduler_recovers_from_failed_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"calls": 0}

    def fake_run_ingestion_cycle(_: Settings) -> None:
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("transient scheduler failure")
        raise asyncio.CancelledError

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.services.scheduler.run_ingestion_cycle", fake_run_ingestion_cycle)
    monkeypatch.setattr("app.services.scheduler.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_ingestion_scheduler(
                Settings(
                    ingestion_enabled=True,
                    ingestion_interval_seconds=1,
                    processing_enabled=False,
                    risk_scoring_enabled=False,
                )
            )
        )

    assert state["calls"] == 2
