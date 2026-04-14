from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import settings
from app.database import get_db
from app.dependencies import require_any_authenticated
from app.models.auth import UserRole
from app.repositories.org_repository import OrgRepository
from app.rate_limit import limiter
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AcceptInvitationRequest,
    ActionTokenStatusResponse,
    GenericMessageResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PasswordForgotRequest,
    PasswordResetRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService, token_svc
from services.shared.feature_entitlements import BASELINE_FEATURES_BY_ROLE, build_feature_entitlement_state

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

auth_svc = AuthService()
user_repo = UserRepository()
org_repo = OrgRepository()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
@limiter.limit(settings.LOGIN_RATE_LIMIT)
async def login(request: Request, body: LoginRequest, response: Response, db=Depends(get_db)) -> TokenResponse:
    _, token_response = await auth_svc.login(db, body.email, body.password)
    _set_refresh_cookie(response, token_response.refresh_token)
    return token_response


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db=Depends(get_db),
) -> TokenResponse:
    raw_token = (body.refresh_token if body and body.refresh_token else request.cookies.get("refresh_token"))
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_REFRESH_TOKEN", "message": "No refresh token provided"},
        )

    token_response = await auth_svc.refresh(db, raw_token)
    _set_refresh_cookie(response, token_response.refresh_token)
    return token_response


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    body: LogoutRequest | None = None,
    db=Depends(get_db),
) -> dict:
    raw_token = (body.refresh_token if body and body.refresh_token else request.cookies.get("refresh_token"))
    access_claims = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header.split(" ", 1)[1].strip()
        try:
            access_claims = token_svc.decode_access_token(bearer_token)
        except Exception:
            access_claims = None
    if raw_token or access_claims is not None:
        await auth_svc.logout(db, raw_token, access_claims)
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"message": "Logged out successfully"}


@router.get("/action-token/{token}/status", response_model=ActionTokenStatusResponse, status_code=status.HTTP_200_OK)
async def action_token_status(token: str, db=Depends(get_db)) -> ActionTokenStatusResponse:
    return await auth_svc.get_action_token_status(db, token)


@router.post("/invitations/accept", response_model=GenericMessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit(settings.INVITATION_ACCEPT_RATE_LIMIT)
async def accept_invitation(
    request: Request,
    body: AcceptInvitationRequest,
    db=Depends(get_db),
) -> GenericMessageResponse:
    await auth_svc.accept_invitation(
        db,
        token=body.token,
        password=body.password,
        confirm_password=body.confirm_password,
    )
    return GenericMessageResponse(message="Password set successfully. Please sign in.")


@router.post("/password/forgot", response_model=GenericMessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit(settings.PASSWORD_FORGOT_RATE_LIMIT)
async def forgot_password(
    request: Request,
    body: PasswordForgotRequest,
    db=Depends(get_db),
) -> GenericMessageResponse:
    await auth_svc.request_password_reset(db, email=body.email)
    return GenericMessageResponse(
        message="If that email is registered, a password reset link has been sent."
    )


@router.post("/password/reset", response_model=GenericMessageResponse, status_code=status.HTTP_200_OK)
async def reset_password(body: PasswordResetRequest, db=Depends(get_db)) -> GenericMessageResponse:
    await auth_svc.reset_password(
        db,
        token=body.token,
        password=body.password,
        confirm_password=body.confirm_password,
    )
    return GenericMessageResponse(message="Password reset successfully. Please sign in.")


@router.get("/me", response_model=MeResponse, status_code=status.HTTP_200_OK)
async def me(
    request: Request,
    claims: dict = Depends(require_any_authenticated),
    db=Depends(get_db),
) -> MeResponse:
    user = await auth_svc.get_user_by_token_claims(db, claims)
    tenant = None
    if user.role == UserRole.SUPER_ADMIN:
        selected_tenant_id = request.headers.get("X-Target-Tenant-Id")
        if selected_tenant_id:
            tenant = await org_repo.get_by_id(db, selected_tenant_id)
            if tenant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "TENANT_NOT_FOUND", "message": "Tenant not found"},
                )
            if not tenant.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "TENANT_SUSPENDED", "message": "Tenant is suspended"},
                )
    elif user.tenant_id is not None:
        tenant = await org_repo.get_by_id(db, user.tenant_id)

    if user.role in {UserRole.PLANT_MANAGER, UserRole.OPERATOR, UserRole.VIEWER}:
        plant_ids = await user_repo.get_plant_ids(db, user.id)
    else:
        plant_ids = []

    entitlements = None
    if tenant is not None:
        feature_role = "org_admin" if user.role == UserRole.SUPER_ADMIN else user.role.value
        feature_state = build_feature_entitlement_state(
            role=feature_role,
            premium_feature_grants=tenant.premium_feature_grants_json,
            role_feature_matrix=tenant.role_feature_matrix_json,
            entitlements_version=tenant.entitlements_version,
        )
        entitlements = feature_state
    elif user.role == UserRole.SUPER_ADMIN:
        entitlements = None

    return MeResponse(
        user=user,
        tenant=tenant,
        plant_ids=plant_ids,
        entitlements=(
            None
            if entitlements is None
            else {
                "premium_feature_grants": entitlements.premium_feature_grants_list,
                "role_feature_matrix": entitlements.role_feature_matrix_list,
                "baseline_features_by_role": {role_name: list(features) for role_name, features in BASELINE_FEATURES_BY_ROLE.items()},
                "effective_features_by_role": entitlements.effective_features_by_role_list,
                "available_features": list(entitlements.available_features),
                "entitlements_version": entitlements.entitlements_version,
            }
        ),
    )
