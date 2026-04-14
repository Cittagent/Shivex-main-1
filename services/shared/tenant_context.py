from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.params import Param

from .feature_entitlements import FeatureEntitlementState

INTERNAL_SERVICE_HEADER = "X-Internal-Service"
TENANT_HEADER = "X-Tenant-Id"
TARGET_TENANT_HEADER = "X-Target-Tenant-Id"


@dataclass(frozen=True)
class TenantContext:
    tenant_id: Optional[str]
    user_id: str
    role: str
    plant_ids: list[str]
    is_super_admin: bool
    entitlements: FeatureEntitlementState | None = None

    def require_tenant(self) -> str:
        if self.tenant_id is None:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "TENANT_SCOPE_REQUIRED",
                    "message": "Tenant scope is required for this action.",
                },
            )
        return self.tenant_id

    def has_feature(self, feature_key: str) -> bool:
        if self.entitlements is None:
            return False
        return feature_key in self.entitlements.available_features

    @classmethod
    def system(cls, service_name: str) -> TenantContext:
        return cls(
            tenant_id=None,
            user_id=service_name,
            role="super_admin",
            plant_ids=[],
            is_super_admin=True,
        )

    @classmethod
    def from_request(cls, request: Request) -> TenantContext:
        ctx = getattr(request.state, "tenant_context", None)
        if ctx is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "MISSING_AUTH_CONTEXT",
                    "message": "Authentication context is missing.",
                },
            )
        return ctx


def normalize_tenant_id(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Param):
        return normalize_tenant_id(value.default)
    resolved = str(value).strip()
    return resolved or None


def _coalesce_tenant_candidates(
    *candidates: tuple[str, object | None],
    error_code: str = "TENANT_SCOPE_MISMATCH",
    error_message: str = "Conflicting tenant scope provided.",
) -> str | None:
    resolved_values: list[tuple[str, str]] = []
    for label, value in candidates:
        normalized = normalize_tenant_id(value)
        if normalized is not None:
            resolved_values.append((label, normalized))

    if not resolved_values:
        return None

    distinct_values = {value for _, value in resolved_values}
    if len(distinct_values) > 1:
        raise HTTPException(
            status_code=403,
            detail={
                "code": error_code,
                "message": error_message,
                "sources": [label for label, _ in resolved_values],
            },
        )

    return resolved_values[0][1]


def resolve_request_tenant_id(
    request: Request,
    *,
    explicit_tenant_id: object | None = None,
    required: bool = False,
    allow_superadmin_query_fallback: bool = True,
    allow_query_fallback: bool = True,
) -> str | None:
    headers = getattr(request, "headers", {}) or {}
    query_params = getattr(request, "query_params", {}) or {}

    ctx = getattr(request.state, "tenant_context", None)
    state_tenant_id = None if ctx is None else ctx.tenant_id

    role = getattr(request.state, "role", "anonymous")
    query_fallback_enabled = allow_query_fallback and role != "internal_service"
    if role == "super_admin" and not allow_superadmin_query_fallback:
        query_fallback_enabled = False

    requested_candidates: list[tuple[str, object | None]] = [
        ("explicit_tenant_id", explicit_tenant_id),
        (f"header:{TENANT_HEADER}", headers.get(TENANT_HEADER)),
        (f"header:{TARGET_TENANT_HEADER}", headers.get(TARGET_TENANT_HEADER)),
    ]
    if query_fallback_enabled:
        requested_candidates.extend(
            [
                ("query:tenant_id", query_params.get("tenant_id")),
            ]
        )

    requested_tenant_id = _coalesce_tenant_candidates(
        *requested_candidates,
        error_message="Conflicting tenant scope provided.",
    )

    if state_tenant_id is not None:
        if requested_tenant_id is not None and requested_tenant_id != state_tenant_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "TENANT_SCOPE_MISMATCH",
                    "message": "Requested tenant scope does not match the authenticated tenant.",
                },
            )
        return state_tenant_id

    if requested_tenant_id is None and required:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_SCOPE_REQUIRED",
                "message": "Tenant scope is required for this action.",
            },
        )

    return requested_tenant_id


def require_tenant(request: Request) -> str:
    return resolve_request_tenant_id(request, required=True)  # type: ignore[return-value]


def build_internal_headers(service_name: str, tenant_id: str | None = None) -> dict[str, str]:
    headers = {INTERNAL_SERVICE_HEADER: service_name}
    if tenant_id:
        headers[TENANT_HEADER] = tenant_id
    return headers


def build_tenant_scoped_internal_headers(service_name: str, tenant_id: str) -> dict[str, str]:
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    if normalized_tenant_id is None:
        raise ValueError("Tenant scope is required for tenant-owned internal requests.")
    return build_internal_headers(service_name, normalized_tenant_id)
