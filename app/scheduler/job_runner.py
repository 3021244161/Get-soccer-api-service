import asyncio
import logging
from time import monotonic

from app.core.cache import create_cache
from app.core.config import get_settings
from app.services.crawler_adapter import CrawlerAdapter
from app.services.refresh_service import RefreshInProgressError, RefreshService


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def scheduler_loop():
    settings = get_settings()
    cache = create_cache(settings)
    crawler = CrawlerAdapter(headless=settings.playwright_headless)
    refresh_service = RefreshService(cache=cache, crawler=crawler, settings=settings)

    if settings.scheduler_run_on_startup:
        await run_once(refresh_service, mode="full")

    next_fast = monotonic() + settings.fast_refresh_interval_seconds
    next_slow = monotonic() + settings.slow_refresh_interval_seconds
    while True:
        await asyncio.sleep(max(min(next_fast, next_slow) - monotonic(), 1))
        if monotonic() >= next_slow:
            await run_once(refresh_service, mode="slow")
            next_slow = monotonic() + settings.slow_refresh_interval_seconds
        if monotonic() >= next_fast:
            await run_once(refresh_service, mode="fast")
            next_fast = monotonic() + settings.fast_refresh_interval_seconds


async def run_once(refresh_service: RefreshService, mode: str):
    try:
        version = await asyncio.to_thread(refresh_service.refresh_all, mode)
        logger.info("%s refresh finished, active version=%s", mode, version)
    except RefreshInProgressError:
        logger.info("%s refresh skipped because another task is running", mode)
    except Exception as exc:
        logger.exception("%s refresh failed: %s", mode, exc)


def main():
    asyncio.run(scheduler_loop())


if __name__ == "__main__":
    main()
