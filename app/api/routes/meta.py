from fastapi import APIRouter, Depends, Request

from app.core.auth import require_api_key
from app.core.models import build_meta, success_response

router = APIRouter(prefix="/api/v1", tags=["meta"], dependencies=[Depends(require_api_key)])


@router.get("/meta")
def get_meta(request: Request):
    query_service = request.app.state.query_service
    meta_payload = query_service.get_meta()
    meta = build_meta(
        version=meta_payload.get("version", ""),
        generated_at=meta_payload.get("generated_at", ""),
        cache_status=meta_payload.get("cache_status", ""),
        refresh_interval_seconds=meta_payload.get("refresh_interval_seconds", ""),
        request_id=request.state.request_id,
    )
    data = {
        "modules": meta_payload.get("modules", []),
        "source_url": meta_payload.get("source_url", ""),
        "last_success_refresh_at": meta_payload.get("last_success_refresh_at", ""),
    }
    return success_response(meta=meta, data=data)
