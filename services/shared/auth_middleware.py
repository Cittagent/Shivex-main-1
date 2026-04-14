"""
FactoryOPS shared authentication middleware.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from fastapi import HTTPException, Request as FARequest
from jose import JWTError, jwt
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .feature_entitlements import build_feature_entitlement_state
from .request_context import current_http_path
from .tenant_context import TenantContext, normalize_tenant_id, resolve_request_tenant_id

logger = logging.getLogger(__name__)


def _load_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY environment variable is required")
    return secret


_JWT_SECRET = _load_jwt_secret()
_JWT_ALG = os.environ.get("JWT_ALGORITHM", "HS256")
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_AUTH_ENGINE = None
_AUTH_SESSION_FACTORY = None
_REDIS_CLIENT = None

_OPEN_PATHS = frozenset(
    {
        "/health",
    "/ready",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/api/v1/data/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    }
)


def _build_internal_context(request: Request) -> TenantContext:
    service_name = request.headers.get("X-Internal-Service")
    if not service_name:
        raise JWTError("Missing internal service identity")

    tenant_id = resolve_request_tenant_id(
        request,
        allow_superadmin_query_fallback=False,
        allow_query_fallback=False,
    )
    return TenantContext(
        tenant_id=tenant_id,
        user_id=service_name,
        role="internal_service",
        plant_ids=[],
        is_super_admin=False,
    )


def _get_auth_session_factory():
    global _AUTH_ENGINE, _AUTH_SESSION_FACTORY

    if _AUTH_SESSION_FACTORY is not None:
        return _AUTH_SESSION_FACTORY

    if not _DATABASE_URL:
        return None

    _AUTH_ENGINE = create_async_engine(
        _DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    _AUTH_SESSION_FACTORY = async_sessionmaker(_AUTH_ENGINE, expire_on_commit=False)
    return _AUTH_SESSION_FACTORY


def _get_redis_client():
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL environment variable is required")

    _REDIS_CLIENT = Redis.from_url(redis_url, decode_responses=True)
    return _REDIS_CLIENT


def _assert_token_not_revoked(payload: dict[str, Any]) -> None:
    jti = payload.get("jti")
    if not jti:
        raise JWTError("Token missing jti")
    client = _get_redis_client()
    if client.get(f"token:revoked:{jti}") is not None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "TOKEN_REVOKED",
                "message": "Token has been revoked.",
            },
        )


async def _assert_token_is_current(payload: dict[str, Any]) -> None:
    user_id = payload.get("sub")
    token_version = payload.get("permissions_version")
    if not user_id or token_version is None:
        raise JWTError("Invalid token payload")

    session_factory = _get_auth_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL not configured")

    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    u.permissions_version,
                    u.is_active AS user_is_active,
                    u.tenant_id,
                    o.is_active AS tenant_is_active,
                    COALESCE(o.entitlements_version, 0) AS tenant_entitlements_version
                FROM users AS u
                LEFT JOIN organizations AS o ON o.id = u.tenant_id
                WHERE u.id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().one_or_none()

    if row is None:
        raise JWTError("Unknown user")

    if not row["user_is_active"]:
        raise JWTError("Inactive user")

    if int(row["permissions_version"]) != int(token_version):
        raise JWTError("Stale token")

    if row["tenant_id"] is not None and not row["tenant_is_active"]:
        raise JWTError("Inactive tenant")

    tenant_entitlements_version = payload.get("tenant_entitlements_version")
    if row["tenant_id"] is not None and tenant_entitlements_version is None:
        raise JWTError("Missing tenant entitlements version")

    if row["tenant_id"] is not None and tenant_entitlements_version is not None:
        if int(row["tenant_entitlements_version"]) != int(tenant_entitlements_version):
            raise JWTError("Stale tenant entitlements")


def _json_error(status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    content = {"code": code, "message": message}
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content)


def _build_tenant_context(request: Request, payload: dict[str, Any]) -> TenantContext:
    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        raise JWTError("Token missing required claims")

    plant_ids = payload.get("plant_ids") or []
    if not isinstance(plant_ids, list):
        raise JWTError("Invalid plant_ids claim")

    is_super_admin = role == "super_admin"
    tenant_id_claim = normalize_tenant_id(payload.get("tenant_id"))

    if is_super_admin and tenant_id_claim is None:
        tenant_id = resolve_request_tenant_id(request)
    else:
        if tenant_id_claim is None:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "MISSING_TENANT_ID",
                    "message": "Authenticated user is missing a tenant scope.",
                },
        )
        tenant_id = tenant_id_claim

    feature_state = getattr(request.state, "tenant_feature_entitlements", None)

    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        plant_ids=[str(plant_id) for plant_id in plant_ids],
        is_super_admin=is_super_admin,
        entitlements=feature_state,
    )


def _attach_auth_state(request: Request, ctx: TenantContext, payload: dict[str, Any]) -> None:
    request.state.tenant_context = ctx
    request.state.tenant_id = ctx.tenant_id
    request.state.user_id = ctx.user_id
    request.state.role = ctx.role
    request.state.plant_ids = ctx.plant_ids
    request.state.is_authenticated = True
    request.state.email = payload.get("email")
    request.state.full_name = payload.get("full_name")
    request.state.feature_entitlements = ctx.entitlements


async def _load_tenant_feature_state(request: Request, tenant_id: str | None, role: str) -> None:
    if tenant_id is None:
        request.state.tenant_feature_entitlements = None
        return

    session_factory = _get_auth_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL not configured")

    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    o.is_active AS tenant_is_active,
                    o.premium_feature_grants_json AS premium_feature_grants_json,
                    o.role_feature_matrix_json AS role_feature_matrix_json,
                    COALESCE(o.entitlements_version, 0) AS entitlements_version
                FROM organizations AS o
                WHERE o.id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_NOT_FOUND",
                "message": "Tenant not found",
            },
        )

    if not row["tenant_is_active"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_SUSPENDED",
                "message": "Tenant is suspended",
            },
        )

    feature_role = "org_admin" if role == "super_admin" else role
    request.state.tenant_feature_entitlements = build_feature_entitlement_state(
        role=feature_role,
        premium_feature_grants=row["premium_feature_grants_json"] or [],
        role_feature_matrix=row["role_feature_matrix_json"] or {},
        entitlements_version=int(row["entitlements_version"] or 0),
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)

        path_token = current_http_path.set(request.url.path)
        try:
            try:
                auth_header = request.headers.get("Authorization", "")
                internal_service = request.headers.get("X-Internal-Service")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
                    if payload.get("type") != "access":
                        raise JWTError("Invalid token type")
                    _assert_token_not_revoked(payload)
                    await _assert_token_is_current(payload)
                    tenant_context = _build_tenant_context(request, payload)
                elif internal_service:
                    payload = {
                        "sub": internal_service,
                        "role": "internal_service",
                        "tenant_id": request.headers.get("X-Tenant-Id") or request.headers.get("X-Target-Tenant-Id"),
                        "plant_ids": [],
                    }
                    tenant_context = _build_internal_context(request)
                else:
                    return _json_error(401, "MISSING_TOKEN", "Authorization header required")
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                return JSONResponse(status_code=exc.status_code, content=detail)
            except RedisError:
                logger.warning("Failed to check token revocation state", exc_info=True)
                return _json_error(
                    503,
                    "AUTH_STATE_UNAVAILABLE",
                    "Authentication state is temporarily unavailable",
                )
            except JWTError:
                return _json_error(401, "INVALID_TOKEN", "Token invalid or expired")
            except Exception:
                logger.exception("Failed to validate token freshness")
                return _json_error(
                    503,
                    "AUTH_STATE_UNAVAILABLE",
                    "Authentication state is temporarily unavailable",
                )

            if payload.get("role") != "internal_service":
                try:
                    await _load_tenant_feature_state(request, tenant_context.tenant_id, str(payload.get("role") or ""))
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                    return JSONResponse(status_code=exc.status_code, content=detail)
                tenant_context = TenantContext(
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    role=tenant_context.role,
                    plant_ids=tenant_context.plant_ids,
                    is_super_admin=tenant_context.is_super_admin,
                    entitlements=getattr(request.state, "tenant_feature_entitlements", None),
                )

            _attach_auth_state(request, tenant_context, payload)
            return await call_next(request)
        finally:
            current_http_path.reset(path_token)


def get_auth_state(request: FARequest) -> dict[str, Any]:
    ctx = TenantContext.from_request(request)
    return {
        "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id,
        "role": ctx.role,
        "plant_ids": ctx.plant_ids,
        "is_authenticated": True,
        "is_super_admin": ctx.is_super_admin,
    }


def require_authenticated(request: FARequest) -> dict[str, Any]:
    return get_auth_state(request)


def require_role(*allowed_roles: str):
    def _dep(request: FARequest) -> dict[str, Any]:
        state = get_auth_state(request)
        if state["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Role '{state['role']}' is not permitted for this action.",
                },
            )
        return state

    return _dep
