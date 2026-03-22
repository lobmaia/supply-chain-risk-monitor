from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.services.scheduler import run_ingestion_scheduler, stop_background_task


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    logger.info(
        "application_startup",
        extra={"app_env": settings.app_env, "database_url": settings.database_url},
    )
    init_db()
    ingestion_task = asyncio.create_task(run_ingestion_scheduler(settings))
    yield
    await stop_background_task(ingestion_task)
    logger.info("application_shutdown")


app = FastAPI(
    title="Supply Chain Risk Monitor API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)
