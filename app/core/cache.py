import json
import time

import redis

from app.core.config import Settings


class RedisCache:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def _dump(self, value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _load(self, raw_value, default=None):
        if raw_value is None:
            return default
        try:
            return json.loads(raw_value)
        except Exception:
            return default

    def acquire_refresh_lock(self, token: str) -> bool:
        return bool(
            self.client.set(
                self.settings.refresh_lock_key,
                token,
                nx=True,
                ex=self.settings.refresh_lock_ttl_seconds,
            )
        )

    def release_refresh_lock(self, token: str) -> None:
        current = self.client.get(self.settings.refresh_lock_key)
        if current == token:
            self.client.delete(self.settings.refresh_lock_key)

    def get_active_version(self) -> str:
        return self.client.get(self.settings.active_version_key) or ""

    def set_active_version(self, version: str) -> None:
        self.client.set(self.settings.active_version_key, version)

    def get_refresh_status(self) -> dict:
        return self._load(self.client.get(self.settings.refresh_latest_key), default={}) or {}

    def set_refresh_status(self, payload: dict) -> None:
        self.client.set(self.settings.refresh_latest_key, self._dump(payload))

    def _version_versions_set_key(self) -> str:
        return f"{self.settings.redis_key_prefix}:versions"

    def _all_key(self, version: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:all"

    def _module_key(self, version: str, module_code: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:module:{module_code}"

    def _match_key(self, version: str, module_code: str, match_id2: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:match:{module_code}:{match_id2}"

    def _module_index_key(self, version: str, module_code: str) -> str:
        return f"{self.settings.redis_key_prefix}:index:{version}:module:{module_code}"

    def store_version_payload(self, version: str, payload: dict) -> None:
        pipe = self.client.pipeline()
        pipe.set(self._all_key(version), self._dump(payload))
        pipe.zadd(self._version_versions_set_key(), {version: time.time()})

        for module_code, module_data in (payload.get("modules") or {}).items():
            pipe.set(self._module_key(version, module_code), self._dump(module_data))
            index_payload = []
            for match in module_data.get("matches", []):
                match_id2 = str(match.get("match_id2", "") or "")
                if match_id2:
                    pipe.set(self._match_key(version, module_code, match_id2), self._dump(match))
                index_payload.append(
                    {
                        "match_id2": match_id2,
                        "match_no": str(match.get("match_no", "") or ""),
                        "league_name": str(match.get("league_name", "") or ""),
                        "home_team": str(match.get("home_team", "") or ""),
                        "away_team": str(match.get("away_team", "") or ""),
                    }
                )
            pipe.set(self._module_index_key(version, module_code), self._dump(index_payload))
        pipe.execute()

    def cleanup_old_versions(self, keep_versions: int) -> None:
        versions = self.client.zrevrange(self._version_versions_set_key(), 0, -1)
        for version in versions[keep_versions:]:
            keys = self.client.keys(f"{self.settings.redis_key_prefix}:data:{version}:*")
            keys.extend(self.client.keys(f"{self.settings.redis_key_prefix}:index:{version}:*"))
            if keys:
                self.client.delete(*keys)
            self.client.zrem(self._version_versions_set_key(), version)

    def get_all_payload(self, version: str) -> dict:
        return self._load(self.client.get(self._all_key(version)), default={}) or {}

    def get_module_payload(self, version: str, module_code: str) -> dict:
        return self._load(self.client.get(self._module_key(version, module_code)), default={}) or {}

    def get_match_payload(self, version: str, module_code: str, match_id2: str) -> dict:
        return self._load(
            self.client.get(self._match_key(version, module_code, match_id2)),
            default={},
        ) or {}

    def get_module_index(self, version: str, module_code: str) -> list[dict]:
        return self._load(
            self.client.get(self._module_index_key(version, module_code)),
            default=[],
        ) or []


class MemoryCache:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = {}
        self.versions = []
        self.lock_token = ""
        self.lock_expire_at = 0.0

    def ping(self) -> bool:
        return True

    def acquire_refresh_lock(self, token: str) -> bool:
        now = time.time()
        if self.lock_token and now < self.lock_expire_at:
            return False
        self.lock_token = token
        self.lock_expire_at = now + self.settings.refresh_lock_ttl_seconds
        return True

    def release_refresh_lock(self, token: str) -> None:
        if self.lock_token == token:
            self.lock_token = ""
            self.lock_expire_at = 0.0

    def get_active_version(self) -> str:
        return self.store.get(self.settings.active_version_key, "")

    def set_active_version(self, version: str) -> None:
        self.store[self.settings.active_version_key] = version

    def get_refresh_status(self) -> dict:
        return self.store.get(self.settings.refresh_latest_key, {}) or {}

    def set_refresh_status(self, payload: dict) -> None:
        self.store[self.settings.refresh_latest_key] = payload

    def _all_key(self, version: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:all"

    def _module_key(self, version: str, module_code: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:module:{module_code}"

    def _match_key(self, version: str, module_code: str, match_id2: str) -> str:
        return f"{self.settings.redis_key_prefix}:data:{version}:match:{module_code}:{match_id2}"

    def _module_index_key(self, version: str, module_code: str) -> str:
        return f"{self.settings.redis_key_prefix}:index:{version}:module:{module_code}"

    def store_version_payload(self, version: str, payload: dict) -> None:
        self.store[self._all_key(version)] = payload
        if version in self.versions:
            self.versions.remove(version)
        self.versions.insert(0, version)
        for module_code, module_data in (payload.get("modules") or {}).items():
            self.store[self._module_key(version, module_code)] = module_data
            index_payload = []
            for match in module_data.get("matches", []):
                match_id2 = str(match.get("match_id2", "") or "")
                if match_id2:
                    self.store[self._match_key(version, module_code, match_id2)] = match
                index_payload.append(
                    {
                        "match_id2": match_id2,
                        "match_no": str(match.get("match_no", "") or ""),
                        "league_name": str(match.get("league_name", "") or ""),
                        "home_team": str(match.get("home_team", "") or ""),
                        "away_team": str(match.get("away_team", "") or ""),
                    }
                )
            self.store[self._module_index_key(version, module_code)] = index_payload

    def cleanup_old_versions(self, keep_versions: int) -> None:
        old_versions = self.versions[keep_versions:]
        for version in old_versions:
            keys = [key for key in list(self.store.keys()) if f":{version}:" in key]
            for key in keys:
                self.store.pop(key, None)
        self.versions = self.versions[:keep_versions]

    def get_all_payload(self, version: str) -> dict:
        return self.store.get(self._all_key(version), {}) or {}

    def get_module_payload(self, version: str, module_code: str) -> dict:
        return self.store.get(self._module_key(version, module_code), {}) or {}

    def get_match_payload(self, version: str, module_code: str, match_id2: str) -> dict:
        return self.store.get(self._match_key(version, module_code, match_id2), {}) or {}

    def get_module_index(self, version: str, module_code: str) -> list[dict]:
        return self.store.get(self._module_index_key(version, module_code), []) or []


def create_cache(settings: Settings):
    if settings.cache_backend == "memory":
        return MemoryCache(settings)
    return RedisCache(settings)
