from fastapi import Request

from app.core.config import Settings
from app.core.cache import RedisCache
from app.services.query_service import QueryService
from app.services.refresh_service import RefreshService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> RedisCache:
    return request.app.state.cache


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


def get_refresh_service(request: Request) -> RefreshService:
    return request.app.state.refresh_service
