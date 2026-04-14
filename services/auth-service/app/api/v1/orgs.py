from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.dependencies import (
    assert_tenant_access,
    require_any_authenticated,
    require_tenant_admin_or_above,
)
from app.models.auth import UserRole
from app.repositories.org_repository import OrgRepository
from app.repositories.plant_repository import PlantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    CreatePlantRequest,
    CreateUserRequest,
    FeatureEntitlementsResponse,
    GenericMessageResponse,
    PlantResponse,
    UpdateEntitlementsRequest,
    UpdateUserRequest,
    UserResponse,
)
from app.services.auth_service import AuthService, pwd_ctx, token_svc
from services.shared.feature_entitlements import (
    BASELINE_FEATURES_BY_ROLE,
    build_feature_entitlement_state,
    validate_premium_grants,
    validate_role_feature_matrix,
)
from services.shared.tenant_context import TenantContext
from services.shared.tenant_guards import assert_plants_belong_to_tenant, assert_same_tenant

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

org_repo = OrgRepository()
plant_repo = PlantRepository()
user_repo = UserRepository()
auth_svc = AuthService()


def _tenant_route_ctx(claims: dict, tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=str(claims.get("sub") or "unknown"),
        role=str(claims.get("role") or "anonymous"),
        plant_ids=[str(plant_id) for plant_id in (claims.get("plant_ids") or [])],
        is_super_admin=False,
    )


async def _get_tenant_scoped_user_or_404(db, user_id: str, tenant_id: str):
    user = await user_repo.get_by_id_for_tenant(db, user_id, tenant_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found"},
        )
    return user


async def _assert_fresh_token(db, claims: dict) -> None:
    if db is None or not hasattr(db, "sync_session"):
        return
    await auth_svc.get_user_by_token_claims(db, claims)


def _entitlements_response(org, role: str) -> FeatureEntitlementsResponse:
    state = build_feature_entitlement_state(
        role=role,
        premium_feature_grants=org.premium_feature_grants_json,
        role_feature_matrix=org.role_feature_matrix_json,
        entitlements_version=org.entitlements_version,
    )
    return FeatureEntitlementsResponse(
        premium_feature_grants=state.premium_feature_grants_list,
        role_feature_matrix=state.role_feature_matrix_list,
        baseline_features_by_role={key: list(value) for key, value in BASELINE_FEATURES_BY_ROLE.items()},
        effective_features_by_role=state.effective_features_by_role_list,
        available_features=list(state.available_features),
        entitlements_version=state.entitlements_version,
    )


@router.post("/{tenant_id}/plants", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
async def create_plant(
    tenant_id: str,
    body: CreatePlantRequest,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> PlantResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    org = await org_repo.get_by_id(db, tenant_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": "Organization not found"},
        )

    plant = await plant_repo.create(db, tenant_id, body.name, body.location, body.timezone)
    return PlantResponse.model_validate(plant)


@router.get("/{tenant_id}/plants", response_model=list[PlantResponse], status_code=status.HTTP_200_OK)
async def list_plants(
    tenant_id: str,
    claims: dict = Depends(require_any_authenticated),
    db=Depends(get_db),
) -> list[PlantResponse]:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    plants = await plant_repo.list_by_tenant(db, tenant_id)
    return [PlantResponse.model_validate(plant) for plant in plants]


@router.post("/{tenant_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    tenant_id: str,
    body: CreateUserRequest,
    claims: dict = Depends(require_any_authenticated),
    db=Depends(get_db),
) -> UserResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    ctx = _tenant_route_ctx(claims, tenant_id)
    caller_role = str(claims.get("role") or "")
    caller_plant_ids = {str(plant_id) for plant_id in (claims.get("plant_ids") or [])}

    if caller_role not in {"super_admin", "org_admin", "plant_manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only organization admins and plant managers can invite users.",
            },
        )

    if caller_role == "plant_manager" and body.role not in ("operator", "viewer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_ESCALATION_FORBIDDEN",
                "message": "Plant managers can only create operator or viewer users.",
            },
        )

    if caller_role == "org_admin" and body.role in ("super_admin", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_ESCALATION_FORBIDDEN",
                "message": "Org admins cannot create org_admin or super_admin users.",
            },
        )

    if body.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "TENANT_ID_MISMATCH",
                "message": "tenant_id must match the path parameter.",
            },
        )

    existing = await user_repo.get_by_email(db, body.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": "Email already exists"},
        )

    user_role = UserRole(body.role)
    if caller_role == "org_admin" and user_role in {UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_ESCALATION_FORBIDDEN",
                "message": "Org admins cannot create org_admin or super_admin users.",
            },
        )

    org = await org_repo.get_by_id(db, tenant_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": "Organization not found"},
        )

    validated_plant_ids: list[str] = []
    if user_role in {UserRole.PLANT_MANAGER, UserRole.OPERATOR, UserRole.VIEWER}:
        validated_plant_ids = list(dict.fromkeys(body.plant_ids))
        if not validated_plant_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INVALID_PLANT_IDS",
                    "message": "At least one plant must be selected.",
                },
            )
        if caller_role == "plant_manager" and len(validated_plant_ids) != 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INVALID_PLANT_IDS",
                    "message": "Plant managers must assign exactly one plant.",
                },
            )
        org_plants = await plant_repo.list_by_tenant(db, tenant_id)
        valid_plant_ids = {plant.id for plant in org_plants}
        if caller_role == "plant_manager":
            assert_plants_belong_to_tenant(validated_plant_ids, caller_plant_ids & valid_plant_ids, ctx)
        else:
            assert_plants_belong_to_tenant(validated_plant_ids, valid_plant_ids, ctx)

    supplied_password = body.password.strip() if body.password else None

    user = await user_repo.create(
        db,
        email=body.email,
        hashed_password=pwd_ctx.hash(supplied_password or secrets.token_urlsafe(32)),
        role=user_role,
        tenant_id=body.tenant_id,
        full_name=body.full_name,
    )
    user.is_active = supplied_password is not None

    if validated_plant_ids:
        await user_repo.set_plant_access(db, user.id, validated_plant_ids)

    if supplied_password is None:
        await auth_svc.send_invitation(
            db,
            user=user,
            created_by_user_id=ctx.user_id,
            created_by_role=ctx.role,
            tenant_id=ctx.tenant_id,
        )

    return UserResponse.model_validate(user)


@router.get("/{tenant_id}/users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def list_users(
    tenant_id: str,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> list[UserResponse]:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    users = await user_repo.list_by_tenant(db, tenant_id)
    return [UserResponse.model_validate(user) for user in users]


@router.get("/{tenant_id}/entitlements", response_model=FeatureEntitlementsResponse, status_code=status.HTTP_200_OK)
async def get_entitlements(
    tenant_id: str,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> FeatureEntitlementsResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    org = await org_repo.get_by_id(db, tenant_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": "Organization not found"},
        )

    feature_role = "org_admin" if claims["role"] == "super_admin" else claims["role"]
    return _entitlements_response(org, feature_role)


@router.put("/{tenant_id}/entitlements", response_model=FeatureEntitlementsResponse, status_code=status.HTTP_200_OK)
async def update_entitlements(
    tenant_id: str,
    body: UpdateEntitlementsRequest,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> FeatureEntitlementsResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    org = await org_repo.get_by_id(db, tenant_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": "Organization not found"},
        )

    caller_role = str(claims.get("role") or "")
    if caller_role == "org_admin":
        if body.premium_feature_grants is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FEATURE_SCOPE_DENIED",
                    "message": "Org admins cannot modify organisation-level premium grants.",
                },
            )
        if body.role_feature_matrix is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "ROLE_MATRIX_REQUIRED",
                    "message": "Org admins must submit a role feature matrix.",
                },
            )
    else:
        if body.role_feature_matrix is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FEATURE_SCOPE_DENIED",
                    "message": "Super admins manage organisation grants only.",
                },
            )
        if body.premium_feature_grants is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "PREMIUM_GRANTS_REQUIRED",
                    "message": "Premium feature grants must be provided.",
                },
            )

    if caller_role == "org_admin":
        validated_matrix = validate_role_feature_matrix(
            role_feature_matrix=body.role_feature_matrix,
            allowed_premium_features=org.premium_feature_grants_json,
            caller_role=caller_role,
        )
        org = await org_repo.update_entitlements(
            db,
            tenant_id,
            role_feature_matrix=validated_matrix,
        )
    else:
        validated_grants = validate_premium_grants(body.premium_feature_grants)
        org = await org_repo.update_entitlements(
            db,
            tenant_id,
            premium_feature_grants=validated_grants,
        )

    return _entitlements_response(org, "org_admin" if caller_role == "super_admin" else caller_role)


@router.put("/{tenant_id}/users/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
@router.patch("/{tenant_id}/users/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def update_user(
    tenant_id: str,
    user_id: str,
    body: UpdateUserRequest,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> UserResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    ctx = _tenant_route_ctx(claims, tenant_id)

    target_user = await _get_tenant_scoped_user_or_404(db, user_id, tenant_id)
    assert_same_tenant(ctx, target_user.tenant_id, "user", user_id)

    if claims["role"] == "org_admin" and body.role in ("super_admin", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ROLE_ESCALATION_FORBIDDEN",
                "message": "Org admins cannot create org_admin or super_admin users.",
            },
        )

    updates: dict = {}
    if body.full_name is not None:
        updates["full_name"] = body.full_name
    if body.role is not None:
        updates["role"] = UserRole(body.role)
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    validated_plant_ids: list[str] | None = None
    if body.plant_ids is not None:
        validated_plant_ids = list(dict.fromkeys(body.plant_ids))
        org_plants = await plant_repo.list_by_tenant(db, tenant_id)
        valid_plant_ids = {plant.id for plant in org_plants}
        assert_plants_belong_to_tenant(validated_plant_ids, valid_plant_ids, ctx)

    updated_user = await user_repo.update(db, user_id, updates)

    permissions_changed = validated_plant_ids is not None or "role" in updates or "is_active" in updates
    if validated_plant_ids is not None:
        await user_repo.set_plant_access(db, user_id, validated_plant_ids)

    if permissions_changed:
        await user_repo.increment_permissions_version(db, user_id)
        await token_svc.revoke_all_user_tokens(db, user_id)

    return UserResponse.model_validate(updated_user)


@router.get("/{tenant_id}/users/{user_id}/plant-access", status_code=status.HTTP_200_OK)
async def get_user_plant_access(
    tenant_id: str,
    user_id: str,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> dict:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    ctx = _tenant_route_ctx(claims, tenant_id)
    target_user = await _get_tenant_scoped_user_or_404(db, user_id, tenant_id)
    assert_same_tenant(ctx, target_user.tenant_id, "user", user_id)
    plant_ids = await user_repo.get_plant_ids(db, user_id)
    return {"plant_ids": plant_ids}


@router.post("/{tenant_id}/users/{user_id}/resend-invite", response_model=GenericMessageResponse, status_code=status.HTTP_200_OK)
async def resend_user_invite(
    tenant_id: str,
    user_id: str,
    claims: dict = Depends(require_any_authenticated),
    db=Depends(get_db),
) -> GenericMessageResponse:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    ctx = _tenant_route_ctx(claims, tenant_id)
    caller_role = str(claims.get("role") or "")
    target_user = await _get_tenant_scoped_user_or_404(db, user_id, tenant_id)
    assert_same_tenant(ctx, target_user.tenant_id, "user", user_id)

    if target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVITE_NOT_PENDING", "message": "Only pending invite users can receive a resent invite."},
        )

    if caller_role not in {"super_admin", "org_admin", "plant_manager"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "You are not allowed to resend invites."},
        )

    if caller_role == "plant_manager":
        if target_user.role not in {UserRole.OPERATOR, UserRole.VIEWER}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "ROLE_ESCALATION_FORBIDDEN", "message": "Plant managers can only resend invites for operator or viewer users."},
            )
        caller_plant_ids = {str(plant_id) for plant_id in (claims.get("plant_ids") or [])}
        target_plant_ids = set(await user_repo.get_plant_ids(db, user_id))
        assert_plants_belong_to_tenant(list(target_plant_ids), caller_plant_ids, ctx)

    await auth_svc.resend_invitation(
        db,
        user=target_user,
        created_by_user_id=ctx.user_id,
        created_by_role=ctx.role,
        tenant_id=ctx.tenant_id,
    )
    return GenericMessageResponse(message="Invitation email resent.")


@router.patch("/{tenant_id}/users/{user_id}/deactivate", status_code=status.HTTP_200_OK)
async def deactivate_user(
    tenant_id: str,
    user_id: str,
    claims: dict = Depends(require_tenant_admin_or_above),
    db=Depends(get_db),
) -> dict:
    await _assert_fresh_token(db, claims)
    assert_tenant_access(claims, tenant_id)
    ctx = _tenant_route_ctx(claims, tenant_id)
    target_user = await _get_tenant_scoped_user_or_404(db, user_id, tenant_id)
    assert_same_tenant(ctx, target_user.tenant_id, "user", user_id)
    await user_repo.update(db, user_id, {"is_active": False})
    await user_repo.increment_permissions_version(db, user_id)
    await token_svc.revoke_all_user_tokens(db, user_id)
    return {"message": "User deactivated"}
