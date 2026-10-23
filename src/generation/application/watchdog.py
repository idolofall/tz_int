import asyncio
import logging

from generation.application.workflow import Workflow
from generation.config import Settings

logger = logging.getLogger(__name__)


async def run_watchdog(workflow: Workflow, settings: Settings) -> None:
    """Each uvicorn worker runs this loop. SKIP LOCKED keeps the work unique."""
    while True:
        try:
            handled = await workflow.watchdog_tick()
            if handled:
                logger.info("watchdog finalized %s expired attempt(s)", handled)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("watchdog tick failed")
        await asyncio.sleep(settings.watchdog_interval_seconds)
