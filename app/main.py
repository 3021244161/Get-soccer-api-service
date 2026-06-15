import asyncio
import contextlib
import logging
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api.routes.admin import router as admin_router
from app.api.routes.health import router as health_router
from app.api.routes.meta import router as meta_router
from app.api.routes.modules import router as modules_router
from app.core.cache import create_cache
from app.core.config import get_settings
from app.core.models import build_request_id
from app.services.crawler_adapter import CrawlerAdapter
from app.services.query_service import QueryService
from app.services.refresh_service import RefreshInProgressError, RefreshService


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    cache = create_cache(settings)
    crawler = CrawlerAdapter(headless=settings.playwright_headless)
    refresh_service = RefreshService(cache=cache, crawler=crawler, settings=settings)
    query_service = QueryService(cache=cache, settings=settings)

    app.state.settings = settings
    app.state.cache = cache
    app.state.refresh_service = refresh_service
    app.state.query_service = query_service
    app.state.scheduler_task = None

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = build_request_id()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(Exception)
    async def handle_generic_error(request: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "meta": {"request_id": getattr(request.state, "request_id", "")},
                "error": {"code": "INTERNAL_ERROR", "message": str(exc)},
            },
        )

    @app.exception_handler(RedisError)
    async def handle_redis_error(request: Request, exc: RedisError):
        logger.warning("Redis unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "meta": {"request_id": getattr(request.state, "request_id", "")},
                "error": {"code": "REDIS_UNAVAILABLE", "message": str(exc)},
            },
        )

    @app.on_event("startup")
    async def startup_event():
        if settings.run_scheduler_in_api:
            app.state.scheduler_task = asyncio.create_task(periodic_refresh_loop(app))

    @app.on_event("shutdown")
    async def shutdown_event():
        task = app.state.scheduler_task
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app.include_router(health_router)
    app.include_router(meta_router)
    app.include_router(modules_router)
    app.include_router(admin_router)
    return app


async def periodic_refresh_loop(app: FastAPI):
    settings = app.state.settings
    refresh_service = app.state.refresh_service
    if settings.scheduler_run_on_startup:
        await _run_refresh_once(refresh_service, mode="full")
    next_fast = monotonic() + settings.fast_refresh_interval_seconds
    next_slow = monotonic() + settings.slow_refresh_interval_seconds
    while True:
        await asyncio.sleep(max(min(next_fast, next_slow) - monotonic(), 1))
        if monotonic() >= next_slow:
            await _run_refresh_once(refresh_service, mode="slow")
            next_slow = monotonic() + settings.slow_refresh_interval_seconds
        if monotonic() >= next_fast:
            await _run_refresh_once(refresh_service, mode="fast")
            next_fast = monotonic() + settings.fast_refresh_interval_seconds


async def _run_refresh_once(refresh_service: RefreshService, mode: str):
    try:
        await asyncio.to_thread(refresh_service.refresh_all, mode)
    except RefreshInProgressError:
        logger.info("Refresh already running, skip %s cycle", mode)
    except Exception as exc:
        logger.exception("Scheduled %s refresh failed: %s", mode, exc)


app = create_app()
