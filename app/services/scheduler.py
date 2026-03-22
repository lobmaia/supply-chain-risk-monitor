import asyncio
from contextlib import suppress

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.ingestion import run_ingestion_cycle

logger = get_logger(__name__)


async def run_ingestion_scheduler(settings: Settings) -> None:
    if not settings.ingestion_enabled:
        logger.info("ingestion_scheduler_disabled")
        return

    logger.info(
        "ingestion_scheduler_started",
        extra={"interval_seconds": settings.ingestion_interval_seconds},
    )
    while True:
        try:
            await asyncio.to_thread(run_ingestion_cycle, settings)
        except Exception:
            logger.exception("ingestion_scheduler_iteration_failed")
        await asyncio.sleep(settings.ingestion_interval_seconds)


async def stop_background_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
