import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from generation.api.routes import router
from generation.application.watchdog import run_watchdog
from generation.application.workflow import Workflow
from generation.config import settings
from generation.infrastructure.db.session import SessionFactory
from generation.infrastructure.providers import ProviderClient

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    workflow = Workflow(
        session_factory=SessionFactory,
        settings=settings,
        provider_client=ProviderClient(
            timeout_seconds=settings.provider_dispatch_timeout_seconds
        ),
    )
    app.state.workflow = workflow
    task = asyncio.create_task(run_watchdog(workflow, settings), name="watchdog")
    logger.info("generation service started")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Generation service", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
