from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from scripts.football_all_modules_once_scraper import MODULES

from app.core.auth import require_api_key
from app.core.models import build_meta, success_response

router = APIRouter(prefix="/api/v1", tags=["modules"], dependencies=[Depends(require_api_key)])


def _ensure_module(module_code: str) -> None:
    if module_code not in MODULES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")


@router.get("/matches")
def get_all_matches(
    request: Request,
    modules: str = Query(default=""),
    include_matches: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    debug: bool = Query(default=False),
):
    query_service = request.app.state.query_service
    selected_modules = [item.strip() for item in modules.split(",") if item.strip()] or None
    if selected_modules:
        invalid_modules = [item for item in selected_modules if item not in MODULES]
        if invalid_modules:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Module not found: {','.join(invalid_modules)}",
            )
    payload = query_service.get_all(
        modules=selected_modules,
        include_matches=include_matches,
        page=page,
        page_size=page_size,
        debug=debug,
    )
    meta = build_meta(request_id=request.state.request_id, **payload["meta"])
    return success_response(meta=meta, data=payload["data"])


@router.get("/modules/{module_code}")
def get_module(
    request: Request,
    module_code: str,
    include_matches: bool = Query(default=True),
    debug: bool = Query(default=False),
):
    _ensure_module(module_code)
    query_service = request.app.state.query_service
    payload = query_service.get_module(
        module_code=module_code,
        include_matches=include_matches,
        debug=debug,
    )
    if not payload["data"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    meta = build_meta(request_id=request.state.request_id, **payload["meta"])
    return success_response(meta=meta, data=payload["data"])


@router.get("/modules/{module_code}/matches")
def list_module_matches(
    request: Request,
    module_code: str,
    match_no: str = Query(default=""),
    league_name: str = Query(default=""),
    home_team: str = Query(default=""),
    away_team: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    debug: bool = Query(default=False),
):
    _ensure_module(module_code)
    query_service = request.app.state.query_service
    payload = query_service.list_module_matches(
        module_code=module_code,
        match_no=match_no,
        league_name=league_name,
        home_team=home_team,
        away_team=away_team,
        page=page,
        page_size=page_size,
        debug=debug,
    )
    meta = build_meta(request_id=request.state.request_id, **payload["meta"])
    return success_response(meta=meta, data=payload["data"])


@router.get("/modules/{module_code}/matches/{match_id2}")
def get_match(
    request: Request,
    module_code: str,
    match_id2: str,
    debug: bool = Query(default=True),
):
    _ensure_module(module_code)
    query_service = request.app.state.query_service
    payload = query_service.get_match(module_code=module_code, match_id2=match_id2, debug=debug)
    if not payload["match"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    meta = build_meta(request_id=request.state.request_id, **payload["meta"])
    return success_response(meta=meta, match=payload["match"])
