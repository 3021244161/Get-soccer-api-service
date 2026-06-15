from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request):
    cache = request.app.state.cache
    refresh_service = request.app.state.refresh_service
    redis_status = "ok"
    status = {}
    try:
        cache.ping()
        status = refresh_service.get_status()
    except Exception:
        redis_status = "error"
        status = {
            "active_version": "",
            "last_success_refresh_at": "",
            "last_refresh_duration_ms": "",
        }
    service_status = "ok" if redis_status == "ok" else "degraded"
    return {
        "service_status": service_status,
        "redis_status": redis_status,
        "active_version": str(status.get("active_version", "")),
        "last_success_refresh_at": str(status.get("last_success_refresh_at", "")),
        "last_refresh_duration_ms": str(status.get("last_refresh_duration_ms", "")),
        "degraded": "true" if service_status != "ok" else "false",
    }
