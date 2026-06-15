from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from scripts.football_all_modules_once_scraper import MODULES

from app.core.auth import require_api_key
from app.core.models import build_meta, success_response
from app.services.refresh_service import RefreshInProgressError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_api_key)])


class RefreshRequest(BaseModel):
    scope: str = "all"
    module_code: str = ""
    mode: str = "full"


def _run_refresh(refresh_service, scope: str, module_code: str, mode: str) -> None:
    if scope == "module":
        refresh_service.refresh_modules([module_code], mode=mode)
    else:
        refresh_service.refresh_all(mode=mode)


@router.post("/refresh")
def trigger_refresh(request: Request, body: RefreshRequest, background_tasks: BackgroundTasks):
    refresh_service = request.app.state.refresh_service
    refresh_status = refresh_service.get_status()
    if refresh_status.get("status") == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Refresh task is already running",
        )
    if body.scope not in {"all", "module"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scope")
    if body.mode not in {"full", "fast", "slow"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid mode")
    if body.scope == "module":
        if not body.module_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="module_code is required when scope=module",
            )
        if body.module_code not in MODULES:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    background_tasks.add_task(_run_refresh, refresh_service, body.scope, body.module_code, body.mode)

    meta = build_meta(request_id=request.state.request_id)
    data = {
        "accepted": "true",
        "scope": body.scope,
        "module_code": body.module_code,
        "mode": body.mode,
        "status": "running",
    }
    return success_response(meta=meta, data=data)


@router.get("/refresh/status")
def get_refresh_status(request: Request):
    refresh_service = request.app.state.refresh_service
    status_payload = refresh_service.get_status()
    meta = build_meta(
        version=status_payload.get("active_version", ""),
        request_id=request.state.request_id,
    )
    data = {
        "status": str(status_payload.get("status", "")),
        "active_version": str(status_payload.get("active_version", "")),
        "last_refresh_mode": str(status_payload.get("last_refresh_mode", "")),
        "last_success_refresh_at": str(status_payload.get("last_success_refresh_at", "")),
        "last_refresh_duration_ms": str(status_payload.get("last_refresh_duration_ms", "")),
        "last_fast_success_refresh_at": str(status_payload.get("last_fast_success_refresh_at", "")),
        "last_fast_refresh_duration_ms": str(status_payload.get("last_fast_refresh_duration_ms", "")),
        "last_slow_success_refresh_at": str(status_payload.get("last_slow_success_refresh_at", "")),
        "last_slow_refresh_duration_ms": str(status_payload.get("last_slow_refresh_duration_ms", "")),
        "last_error": str(status_payload.get("last_error", "")),
        "cache_status": str(status_payload.get("cache_status", "")),
    }
    return success_response(meta=meta, data=data)
