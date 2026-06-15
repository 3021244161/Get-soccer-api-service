import copy
from typing import Any
from uuid import uuid4


DEBUG_FIELDS = [
    "history_dom_text",
    "strength_detail_dom_text",
    "lineup_dom_text",
    "europe_dom_text",
    "asia_dom_text",
    "history_api_raw",
    "base_api_raw",
    "lineup_api_raw",
    "europe_list_api_raw",
    "europe_stats_api_raw",
    "asia_list_api_raw",
    "asia_stats_api_raw",
    "request_log",
]


def build_request_id() -> str:
    return f"req_{uuid4().hex}"


def build_meta(
    version: str = "",
    generated_at: str = "",
    cache_status: str = "unknown",
    refresh_interval_seconds: int | str = "",
    request_id: str = "",
    **extra: Any,
) -> dict[str, str]:
    meta = {
        "version": str(version or ""),
        "generated_at": str(generated_at or ""),
        "cache_status": str(cache_status or ""),
        "refresh_interval_seconds": str(refresh_interval_seconds or ""),
        "request_id": str(request_id or build_request_id()),
    }
    for key, value in extra.items():
        meta[key] = "" if value is None else str(value)
    return meta


def success_response(meta: dict[str, Any], data: Any = None, match: Any = None) -> dict[str, Any]:
    payload = {"meta": meta}
    if match is not None:
        payload["match"] = match
    else:
        payload["data"] = data
    return payload


def strip_match_debug_fields(match: dict[str, Any], include_debug: bool) -> dict[str, Any]:
    cloned = copy.deepcopy(match)
    if include_debug:
        return cloned
    for field in DEBUG_FIELDS:
        if field in cloned:
            cloned[field] = ""
    return cloned
