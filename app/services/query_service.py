import copy

from scripts.football_all_modules_once_scraper import MODULES

from app.core.cache import RedisCache
from app.core.config import Settings
from app.core.models import strip_match_debug_fields


class QueryService:
    def __init__(self, cache: RedisCache, settings: Settings):
        self.cache = cache
        self.settings = settings

    def _latest_context(self) -> tuple[str, dict]:
        version = self.cache.get_active_version()
        status = self.cache.get_refresh_status()
        return version, status

    def _generated_at(self, payload: dict, status: dict) -> str:
        return str(
            (payload or {}).get("captured_at")
            or status.get("last_success_refresh_at")
            or ""
        )

    def _cache_status(self, status: dict) -> str:
        if not status:
            return "empty"
        return str(status.get("cache_status") or "fresh")

    def _meta_common(self, version: str, payload: dict, status: dict) -> dict:
        return {
            "version": version,
            "generated_at": self._generated_at(payload, status),
            "cache_status": self._cache_status(status),
            "refresh_interval_seconds": str(self.settings.refresh_interval_seconds),
            "fast_refresh_interval_seconds": str(self.settings.fast_refresh_interval_seconds),
            "slow_refresh_interval_seconds": str(self.settings.slow_refresh_interval_seconds),
            "last_refresh_mode": str(status.get("last_refresh_mode", "")),
            "last_fast_success_refresh_at": str(status.get("last_fast_success_refresh_at", "")),
            "last_slow_success_refresh_at": str(status.get("last_slow_success_refresh_at", "")),
        }

    def get_meta(self) -> dict:
        version, status = self._latest_context()
        payload = self.cache.get_all_payload(version) if version else {}
        return {
            **self._meta_common(version, payload, status),
            "source_url": str((payload or {}).get("source_url", "")),
            "last_success_refresh_at": str(status.get("last_success_refresh_at", "")),
            "modules": [
                {"module_code": cfg["module_code"], "module_name": cfg["module_name"]}
                for cfg in MODULES.values()
            ],
        }

    def get_all(self, modules=None, include_matches=True, page=1, page_size=50, debug=False) -> dict:
        version, status = self._latest_context()
        payload = self.cache.get_all_payload(version) if version else {}
        modules_payload = copy.deepcopy((payload or {}).get("modules") or {})
        selected_modules = set(modules or modules_payload.keys())

        result_modules = {}
        for module_code, module_data in modules_payload.items():
            if module_code not in selected_modules:
                continue
            result_modules[module_code] = self._shape_module_payload(
                module_data,
                include_matches=include_matches,
                page=page,
                page_size=page_size,
                debug=debug,
            )

        return {
            "meta": self._meta_common(version, payload, status),
            "data": {
                "source_url": str((payload or {}).get("source_url", "")),
                "captured_at": str((payload or {}).get("captured_at", "")),
                "station_user_id": str((payload or {}).get("station_user_id", "")),
                "station_uuid": str((payload or {}).get("station_uuid", "")),
                "modules": result_modules,
            },
        }

    def get_module(self, module_code: str, include_matches=True, debug=False) -> dict:
        version, status = self._latest_context()
        module_data = self.cache.get_module_payload(version, module_code) if version else {}
        payload = self.cache.get_all_payload(version) if version else {}
        return {
            "meta": {
                **self._meta_common(version, payload, status),
                "module_code": module_code,
            },
            "data": self._shape_module_payload(
                module_data,
                include_matches=include_matches,
                page=1,
                page_size=max(len(module_data.get("matches", [])), 1),
                debug=debug,
            ),
        }

    def list_module_matches(
        self,
        module_code: str,
        match_no="",
        league_name="",
        home_team="",
        away_team="",
        page=1,
        page_size=50,
        debug=False,
    ) -> dict:
        version, status = self._latest_context()
        module_data = self.cache.get_module_payload(version, module_code) if version else {}
        payload = self.cache.get_all_payload(version) if version else {}
        matches = list(module_data.get("matches", []))
        filters = {
            "match_no": match_no,
            "league_name": league_name,
            "home_team": home_team,
            "away_team": away_team,
        }
        matches = [match for match in matches if self._match_filters(match, filters)]
        total = len(matches)
        matches = self._paginate(matches, page, page_size)
        matches = [strip_match_debug_fields(match, include_debug=debug) for match in matches]
        return {
            "meta": {
                **self._meta_common(version, payload, status),
                "module_code": module_code,
            },
            "data": {
                "module_code": module_code,
                "module_name": module_data.get("module_name", ""),
                "match_count": str(total),
                "page": str(page),
                "page_size": str(page_size),
                "matches": matches,
            },
        }

    def get_match(self, module_code: str, match_id2: str, debug=True) -> dict:
        version, status = self._latest_context()
        match = self.cache.get_match_payload(version, module_code, match_id2) if version else {}
        payload = self.cache.get_all_payload(version) if version else {}
        return {
            "meta": {
                **self._meta_common(version, payload, status),
                "module_code": module_code,
            },
            "match": strip_match_debug_fields(match, include_debug=debug),
        }

    def _shape_module_payload(self, module_data: dict, include_matches: bool, page: int, page_size: int, debug: bool) -> dict:
        cloned = copy.deepcopy(module_data or {})
        matches = cloned.get("matches", [])
        if include_matches:
            matches = self._paginate(matches, page, page_size)
            matches = [strip_match_debug_fields(match, include_debug=debug) for match in matches]
        else:
            matches = []
        cloned["matches"] = matches
        return cloned

    def _paginate(self, items: list, page: int, page_size: int) -> list:
        safe_page = max(int(page or 1), 1)
        safe_page_size = max(min(int(page_size or 50), 500), 1)
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        return items[start:end]

    def _match_filters(self, match: dict, filters: dict) -> bool:
        for field, expected in filters.items():
            if not expected:
                continue
            value = str(match.get(field, "") or "")
            if expected not in value:
                return False
        return True
