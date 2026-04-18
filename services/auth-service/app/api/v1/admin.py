from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select

from app.database import get_db
from app.dependencies import require_super_admin
from app.models.auth import User, UserRole
from app.repositories.org_repository import OrgRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import CreateTenantRequest, CreateUserRequest, TenantResponse, UserResponse
from app.services.tenant_id_service import TenantIdAllocationError
router = APIRouter(prefix="/api/admin", tags=["super-admin"], dependencies=[Depends(require_super_admin)])

org_repo = OrgRepository()
user_repo = UserRepository()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
UTC = timezone.utc


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: CreateTenantRequest, db=Depends(get_db)) -> TenantResponse:
    existing = await org_repo.get_by_slug(db, body.slug)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SLUG_TAKEN", "message": "Tenant slug already exists"},
        )

    try:
        org = await org_repo.create(db, body.name, body.slug)
    except TenantIdAllocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "TENANT_ID_ALLOCATION_FAILED",
                "message": "Tenant identity allocation is temporarily unavailable",
            },
        ) from exc
    return TenantResponse.model_validate(org)

@router.get("/tenants", response_model=list[TenantResponse], status_code=status.HTTP_200_OK)
async def list_tenants(db=Depends(get_db)) -> list[TenantResponse]:
    orgs = await org_repo.list_all(db)
    return [TenantResponse.model_validate(org) for org in orgs]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: CreateUserRequest, db=Depends(get_db)) -> UserResponse:
    if body.role != "org_admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_ROLE",
                "message": "This endpoint only creates org_admin users. Use /api/v1/tenants/{tenant_id}/users for other roles.",
            },
        )

    tenant_id = body.tenant_id
    org = await org_repo.get_by_id(db, tenant_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TENANT_NOT_FOUND", "message": "Tenant not found"},
        )

    existing = await user_repo.get_by_email(db, body.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": "Email already exists"},
        )

    if not body.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PASSWORD_REQUIRED", "message": "Password is required for tenant admin creation."},
        )

    hashed_password = pwd_ctx.hash(body.password)
    user = await user_repo.create(
        db,
        email=body.email,
        hashed_password=hashed_password,
        role=UserRole.ORG_ADMIN,
        tenant_id=tenant_id,
        full_name=body.full_name,
    )
    user.activated_at = datetime.now(UTC).replace(tzinfo=None)
    return UserResponse.model_validate(user)


@router.get("/users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def list_users(
    tenant_id: str | None = None,
    db=Depends(get_db),
) -> list[UserResponse]:
    if tenant_id is None:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = list(result.scalars().all())
    else:
        users = await user_repo.list_by_tenant(db, tenant_id)
    return [UserResponse.model_validate(user) for user in users]
