import copy
import json
import logging
import os
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.core.cache import RedisCache
from app.core.config import Settings
from app.services.crawler_adapter import CrawlerAdapter
from scripts.football_all_modules_once_scraper import (
    FAST_REFRESH_FIELDS,
    LEGACY_MATCH_FIELDS,
    SLOW_REFRESH_FIELDS,
)


logger = logging.getLogger(__name__)
INVALID_DETAIL_MARKERS = ("参数错误", "参数错误1", "网络错误，请稍后再试", "undefined")


class RefreshInProgressError(RuntimeError):
    pass


class RefreshService:
    def __init__(self, cache: RedisCache, crawler: CrawlerAdapter, settings: Settings):
        self.cache = cache
        self.crawler = crawler
        self.settings = settings

    def refresh_all(self, mode: str = "full") -> str:
        return self._refresh(scope="all", module_codes=None, mode=mode)

    def refresh_modules(self, module_codes: list[str], mode: str = "full") -> str:
        return self._refresh(scope="module", module_codes=module_codes, mode=mode)

    def get_status(self) -> dict:
        status = self.cache.get_refresh_status()
        if not status:
            return {
                "status": "idle",
                "active_version": self.cache.get_active_version(),
                "last_refresh_mode": "",
                "last_success_refresh_at": "",
                "last_refresh_duration_ms": "",
                "last_fast_success_refresh_at": "",
                "last_fast_refresh_duration_ms": "",
                "last_slow_success_refresh_at": "",
                "last_slow_refresh_duration_ms": "",
                "last_error": "",
                "cache_status": "empty",
            }
        status["active_version"] = self.cache.get_active_version()
        return status

    def _refresh(self, scope: str, module_codes: list[str] | None, mode: str) -> str:
        requested_mode = mode or "full"
        actual_mode = requested_mode
        active_version = self.cache.get_active_version()
        if requested_mode in {"fast", "slow"} and not active_version:
            logger.info("No active cache version found, fallback to full refresh instead of %s", requested_mode)
            actual_mode = "full"

        token = uuid4().hex
        if not self.cache.acquire_refresh_lock(token):
            raise RefreshInProgressError("Refresh task is already running")

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        started_perf = perf_counter()
        previous_status = self.cache.get_refresh_status()
        self.cache.set_refresh_status(
            {
                **previous_status,
                "status": "running",
                "current_scope": scope,
                "current_mode": actual_mode,
                "last_started_at": started_at,
                "last_error": "",
                "cache_status": previous_status.get("cache_status", "fresh") or "fresh",
            }
        )
        try:
            if scope == "all":
                fresh_payload = self.crawler.crawl_all_modules(
                    progress_callback=logger.info,
                    refresh_mode=actual_mode,
                )
            else:
                fresh_payload = self.crawler.crawl_modules(
                    module_codes or [],
                    progress_callback=logger.info,
                    refresh_mode=actual_mode,
                )
            payload = self._merge_payload_for_mode(
                fresh_modules_payload=fresh_payload,
                mode=actual_mode,
            )

            version = self._build_version()
            self.cache.store_version_payload(version, payload)
            self._persist_snapshot(version, payload)
            self.cache.set_active_version(version)
            self.cache.cleanup_old_versions(self.settings.cache_keep_versions)

            completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            duration_ms = int((perf_counter() - started_perf) * 1000)
            self.cache.set_refresh_status(
                self._build_success_status(
                    previous_status=previous_status,
                    version=version,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    mode=actual_mode,
                )
            )
            return version
        except Exception as exc:
            duration_ms = int((perf_counter() - started_perf) * 1000)
            self.cache.set_refresh_status(
                {
                    **previous_status,
                    "status": "idle",
                    "active_version": self.cache.get_active_version(),
                    "last_refresh_mode": actual_mode,
                    "last_started_at": started_at,
                    "last_refresh_duration_ms": str(duration_ms),
                    "last_error": f"{type(exc).__name__}: {exc}",
                    "cache_status": "stale" if self.cache.get_active_version() else "empty",
                }
            )
            raise
        finally:
            self.cache.release_refresh_lock(token)

    def _build_success_status(
        self,
        previous_status: dict,
        version: str,
        started_at: str,
        completed_at: str,
        duration_ms: int,
        mode: str,
    ) -> dict:
        status = {
            **previous_status,
            "status": "idle",
            "active_version": version,
            "last_started_at": started_at,
            "last_success_refresh_at": completed_at,
            "last_refresh_duration_ms": str(duration_ms),
            "last_refresh_mode": mode,
            "last_error": "",
            "cache_status": "fresh",
        }
        if mode in {"full", "fast"}:
            status["last_fast_success_refresh_at"] = completed_at
            status["last_fast_refresh_duration_ms"] = str(duration_ms)
        if mode in {"full", "slow"}:
            status["last_slow_success_refresh_at"] = completed_at
            status["last_slow_refresh_duration_ms"] = str(duration_ms)
        return status

    def _merge_payload_for_mode(self, fresh_modules_payload: dict, mode: str) -> dict:
        active_version = self.cache.get_active_version()
        if mode == "full" and not active_version:
            return fresh_modules_payload

        if not active_version:
            return fresh_modules_payload

        base_payload = self.cache.get_all_payload(active_version)
        merged = copy.deepcopy(base_payload or {})
        merged["captured_at"] = str(
            fresh_modules_payload.get("captured_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        merged["refresh_mode"] = mode
        merged["source_url"] = str(fresh_modules_payload.get("source_url") or merged.get("source_url") or "")
        merged["station_user_id"] = str(
            fresh_modules_payload.get("station_user_id") or merged.get("station_user_id") or ""
        )
        merged["station_uuid"] = str(
            fresh_modules_payload.get("station_uuid") or merged.get("station_uuid") or ""
        )
        merged.setdefault("modules", {})
        for module_code, module_payload in (fresh_modules_payload.get("modules") or {}).items():
            merged["modules"][module_code] = self._merge_module_payload(
                base_module_payload=(base_payload or {}).get("modules", {}).get(module_code) or {},
                fresh_module_payload=module_payload,
                mode=mode,
            )
        return merged

    def _merge_module_payload(self, base_module_payload: dict, fresh_module_payload: dict, mode: str) -> dict:
        merged_module = copy.deepcopy(base_module_payload or {})
        merged_module["module_code"] = str(
            fresh_module_payload.get("module_code") or merged_module.get("module_code") or ""
        )
        merged_module["module_name"] = str(
            fresh_module_payload.get("module_name") or merged_module.get("module_name") or ""
        )

        base_matches = {
            self._match_key(match): copy.deepcopy(match)
            for match in (base_module_payload.get("matches") or [])
            if self._match_key(match)
        }
        merged_matches = []
        for fresh_match in fresh_module_payload.get("matches") or []:
            key = self._match_key(fresh_match)
            base_match = base_matches.get(key)
            merged_matches.append(self._merge_match_payload(base_match, fresh_match, mode))

        merged_module["match_count"] = str(fresh_module_payload.get("match_count") or len(merged_matches))
        merged_module["matches"] = merged_matches
        return merged_module

    def _merge_match_payload(self, base_match: dict | None, fresh_match: dict, mode: str) -> dict:
        if not base_match:
            return copy.deepcopy(fresh_match)

        merged_match = copy.deepcopy(base_match)
        if mode == "fast":
            refresh_fields = FAST_REFRESH_FIELDS
        elif mode == "slow":
            refresh_fields = SLOW_REFRESH_FIELDS
        else:
            refresh_fields = LEGACY_MATCH_FIELDS
        prefer_existing_when_fast = {
            "league_name",
            "home_team",
            "away_team",
            "home_rank_text",
            "away_rank_text",
        }
        for field in refresh_fields:
            if field == "request_log":
                merged_match[field] = self._merge_request_log(
                    base_match.get(field, ""),
                    fresh_match.get(field, ""),
                )
                continue
            fresh_value = fresh_match.get(field, "")
            if mode == "fast" and field in prefer_existing_when_fast and merged_match.get(field):
                continue
            if self._should_keep_existing_value(field, base_match.get(field, ""), fresh_value):
                continue
            merged_match[field] = fresh_value
        return merged_match

    def _merge_request_log(self, base_value: str, fresh_value: str) -> str:
        try:
            base_payload = json.loads(base_value or "{}")
        except Exception:
            base_payload = {}
        try:
            fresh_payload = json.loads(fresh_value or "{}")
        except Exception:
            fresh_payload = {}
        if isinstance(base_payload, dict) and isinstance(fresh_payload, dict):
            merged = dict(base_payload)
            for key, value in fresh_payload.items():
                if value:
                    merged[key] = value
            return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        return fresh_value or base_value or ""

    def _should_keep_existing_value(self, field: str, base_value, fresh_value) -> bool:
        if not self._has_meaningful_existing_value(base_value):
            return False
        if self._has_meaningful_fresh_value(field, fresh_value):
            return False
        return field in LEGACY_MATCH_FIELDS

    def _has_meaningful_existing_value(self, value) -> bool:
        text = str(value or "").strip()
        return text not in {"", "[]", "{}", "null"}

    def _has_meaningful_fresh_value(self, field: str, value) -> bool:
        text = str(value or "").strip()
        if text in {"", "[]", "{}", "null"}:
            return False
        if any(marker in text for marker in INVALID_DETAIL_MARKERS):
            return False
        if field.endswith("_api_raw"):
            return "\"data\":{}" not in text and "\"data\":[]" not in text
        if field.endswith("_dom_text"):
            return len(text) >= 20
        return True

    def _match_key(self, match: dict) -> str:
        return str(
            match.get("match_id2")
            or match.get("match_id")
            or f"{match.get('match_date', '')}:{match.get('match_no', '')}:{match.get('home_team', '')}:{match.get('away_team', '')}"
        )

    def _build_version(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _persist_snapshot(self, version: str, payload: dict) -> None:
        output_dir = self.settings.output_dir
        os.makedirs(output_dir, exist_ok=True)
        versioned_path = output_dir / f"api_snapshot_{version}.json"
        current_path = output_dir / "api_snapshot_current.json"
        self._write_json_atomic(versioned_path, payload)
        self._write_json_atomic(current_path, payload)

    def _write_json_atomic(self, path, payload: dict) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
