from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

FEATURE_KEYS: tuple[str, ...] = (
    "machines",
    "calendar",
    "analytics",
    "reports",
    "waste_analysis",
    "copilot",
    "rules",
    "settings",
)

BASELINE_FEATURES_BY_ROLE: dict[str, tuple[str, ...]] = {
    "org_admin": ("machines", "calendar", "rules", "settings"),
    "plant_manager": ("machines", "rules", "settings"),
    "operator": ("machines", "rules"),
    "viewer": ("machines",),
}

ORG_GRANTABLE_FEATURES: tuple[str, ...] = (
    "analytics",
    "reports",
    "waste_analysis",
    "copilot",
)

PLANT_MANAGER_DELEGATABLE_FEATURES: tuple[str, ...] = (
    "analytics",
    "reports",
    "waste_analysis",
)

DEFAULT_ROLE_DELEGATIONS: dict[str, tuple[str, ...]] = {
    "plant_manager": (),
    "operator": (),
    "viewer": (),
}

ROLE_KEYS: tuple[str, ...] = tuple(BASELINE_FEATURES_BY_ROLE.keys())


def _resolve_entitlement_role(role: str) -> str:
    if role == "super_admin":
        return "org_admin"
    return role


def _coerce_json_value(value, *, expected_type: type, default):
    if value is None:
        return default

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            logger.warning("Malformed feature entitlement JSON stored in DB; falling back to defaults", extra={"value_type": "str"})
            return default

    if not isinstance(value, expected_type):
        logger.warning(
            "Unexpected feature entitlement value type stored in DB; falling back to defaults",
            extra={"value_type": type(value).__name__},
        )
        return default

    return value


def coerce_feature_list(value) -> list[str]:
    coerced = _coerce_json_value(value, expected_type=list, default=[])
    return [str(item) for item in coerced]


def coerce_feature_matrix(value) -> dict[str, list[str]]:
    coerced = _coerce_json_value(value, expected_type=dict, default={})
    return {str(role): [str(feature) for feature in features] for role, features in coerced.items()}


def normalize_feature_keys(features: Iterable[str] | None) -> list[str]:
    if features is None:
        return []

    seen: set[str] = set()
    normalized: list[str] = []
    for feature in features:
        if feature not in FEATURE_KEYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_FEATURE_KEY",
                    "message": f"Unknown feature '{feature}'.",
                },
            )
        if feature in seen:
            continue
        seen.add(feature)
        normalized.append(feature)
    return normalized


def normalize_role_feature_matrix(matrix: Mapping[str, Iterable[str]] | None) -> dict[str, list[str]]:
    matrix = matrix or {}
    unknown_roles = sorted(set(matrix.keys()) - set(ROLE_KEYS))
    if unknown_roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_ROLE_KEY",
                "message": "Unknown role key in feature matrix.",
                "invalid_roles": unknown_roles,
            },
        )

    normalized: dict[str, list[str]] = {}
    for role in ROLE_KEYS:
        # Preserve every supported role key so responses stay stable.
        normalized[role] = normalize_feature_keys(matrix.get(role, ()))
    return normalized


def _unique_ordered(features: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for feature in features:
        if feature in seen:
            continue
        seen.add(feature)
        ordered.append(feature)
    return tuple(ordered)


def _ensure_subset(features: Iterable[str], allowed: Iterable[str], *, error_message: str) -> list[str]:
    allowed_set = set(allowed)
    normalized = normalize_feature_keys(features)
    invalid = [feature for feature in normalized if feature not in allowed_set]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_SCOPE_DENIED",
                "message": error_message,
                "invalid_features": invalid,
            },
        )
    return normalized


def get_allowed_premium_features_for_role(role: str) -> tuple[str, ...]:
    role = _resolve_entitlement_role(role)
    if role == "plant_manager":
        return PLANT_MANAGER_DELEGATABLE_FEATURES
    if role == "org_admin":
        return ORG_GRANTABLE_FEATURES
    return ()


def get_baseline_features_for_role(role: str) -> tuple[str, ...]:
    role = _resolve_entitlement_role(role)
    return BASELINE_FEATURES_BY_ROLE.get(role, ())


@dataclass(frozen=True)
class FeatureEntitlementState:
    premium_feature_grants: tuple[str, ...]
    role_feature_matrix: dict[str, tuple[str, ...]]
    available_features: tuple[str, ...]
    effective_features_by_role: dict[str, tuple[str, ...]]
    entitlements_version: int = 0

    @property
    def premium_feature_grants_list(self) -> list[str]:
        return list(self.premium_feature_grants)

    @property
    def role_feature_matrix_list(self) -> dict[str, list[str]]:
        return {role: list(features) for role, features in self.role_feature_matrix.items()}

    @property
    def effective_features_by_role_list(self) -> dict[str, list[str]]:
        return {role: list(features) for role, features in self.effective_features_by_role.items()}


def build_feature_entitlement_state(
    *,
    role: str,
    premium_feature_grants: Iterable[str] | None,
    role_feature_matrix: Mapping[str, Iterable[str]] | None,
    entitlements_version: int = 0,
) -> FeatureEntitlementState:
    normalized_grants = tuple(normalize_feature_keys(coerce_feature_list(premium_feature_grants)))
    premium_grants_set = set(normalized_grants)
    normalized_matrix = normalize_role_feature_matrix(coerce_feature_matrix(role_feature_matrix))

    effective_by_role: dict[str, tuple[str, ...]] = {}
    for role_name in ROLE_KEYS:
        baseline = get_baseline_features_for_role(role_name)
        if role_name == "org_admin":
            effective_by_role[role_name] = _unique_ordered((*baseline, *normalized_grants))
            continue

        if role_name == "plant_manager":
            delegated = tuple(
                feature
                for feature in normalized_matrix.get(role_name, ())
                if feature in premium_grants_set and feature in PLANT_MANAGER_DELEGATABLE_FEATURES
            )
            effective_by_role[role_name] = _unique_ordered((*baseline, *delegated))
            continue

        effective_by_role[role_name] = baseline

    resolved_role = _resolve_entitlement_role(role)
    if resolved_role not in effective_by_role:
        resolved_role = "viewer"
    available_features = effective_by_role.get(resolved_role, ())

    return FeatureEntitlementState(
        premium_feature_grants=normalized_grants,
        role_feature_matrix={role_name: tuple(features) for role_name, features in normalized_matrix.items()},
        available_features=available_features,
        effective_features_by_role=effective_by_role,
        entitlements_version=int(entitlements_version or 0),
    )


def validate_role_feature_matrix(
    *,
    role_feature_matrix: Mapping[str, Iterable[str]] | None,
    allowed_premium_features: Iterable[str] | None,
    caller_role: str,
) -> dict[str, list[str]]:
    if caller_role not in {"org_admin", "super_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_SCOPE_DENIED",
                "message": "Only organisation administrators can manage feature delegation.",
            },
        )

    allowed_set = set(validate_premium_grants(allowed_premium_features or ()))
    normalized_matrix = normalize_role_feature_matrix(role_feature_matrix)
    if normalized_matrix.get("org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_SCOPE_DENIED",
                "message": "Org admins cannot edit their own feature grant set.",
            },
        )

    plant_manager_features = normalized_matrix.get("plant_manager", [])

    invalid = [feature for feature in plant_manager_features if feature not in allowed_set]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_SCOPE_DENIED",
                "message": "Org admins can only assign features already granted to the organisation.",
                "invalid_features": invalid,
            },
        )

    restricted = [feature for feature in plant_manager_features if feature not in PLANT_MANAGER_DELEGATABLE_FEATURES]
    if restricted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_SCOPE_DENIED",
                "message": "Org admins can only delegate analytics, reports, and waste analysis to plant managers.",
                "invalid_features": restricted,
            },
        )

    for role in ("operator", "viewer"):
        disallowed = [feature for feature in normalized_matrix.get(role, []) if feature]
        if disallowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FEATURE_SCOPE_DENIED",
                    "message": f"{role.replace('_', ' ').title()}s cannot be assigned premium features.",
                    "invalid_features": disallowed,
                },
            )

    return normalized_matrix


def validate_premium_grants(granted_features: Iterable[str] | None) -> list[str]:
    return _ensure_subset(
        coerce_feature_list(granted_features),
        ORG_GRANTABLE_FEATURES,
        error_message="Only premium organisation features can be enabled here.",
    )


def require_feature(feature_key: str):
    if feature_key not in FEATURE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INVALID_FEATURE_KEY",
                "message": f"Unknown feature '{feature_key}'.",
            },
        )

    def dependency(request: Request) -> None:
        ctx = getattr(request.state, "tenant_context", None)
        if ctx is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "MISSING_AUTH_CONTEXT",
                "message": "Authentication context is missing.",
                },
            )

        if getattr(ctx, "role", None) == "internal_service":
            return

        entitlements = getattr(ctx, "entitlements", None) or getattr(request.state, "feature_entitlements", None)
        if entitlements is None or feature_key not in entitlements.available_features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FEATURE_DISABLED",
                    "message": f"Feature '{feature_key}' is not enabled for this organisation.",
                },
            )

    return dependency
