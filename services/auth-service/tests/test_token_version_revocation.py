import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, AsyncMock, Mock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from jose import JWTError, jwt


AUTH_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
for path in (REPO_ROOT, SERVICES_ROOT, AUTH_SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.chdir(AUTH_SERVICE_ROOT)
os.environ.setdefault("DATABASE_URL", "mysql+aiomysql://energy:energy@localhost:3306/ai_factoryops")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")

from app.api.v1.auth import router as auth_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1 import auth as auth_api
from app.api.v1 import orgs as orgs_api
from app.database import get_db
from app.dependencies import assert_tenant_access
from app.models.auth import User, UserRole
from app.repositories.org_repository import OrgRepository
from app.repositories.user_repository import UserRepository
from app.rate_limit import configure_rate_limiting
from app.services import auth_service as auth_service_module
from app.services.auth_service import AuthService, org_repo, user_repo
from app.services.action_token_service import action_token_svc
from app.services.mailer_service import mailer_svc
from app.services.token_service import TokenService
from shared import auth_middleware as middleware


UTC = timezone.utc


class FakeRedisPipeline:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append(lambda: self._redis.set(key, value, ex=ex))
        return self

    def sadd(self, key, value):
        self._ops.append(lambda: self._redis.sadd(key, value))
        return self

    def expire(self, key, ttl):
        self._ops.append(lambda: self._redis.expire(key, ttl))
        return self

    def delete(self, key):
        self._ops.append(lambda: self._redis.delete(key))
        return self

    def srem(self, key, value):
        self._ops.append(lambda: self._redis.srem(key, value))
        return self

    def execute(self):
        return [op() for op in self._ops]


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.sets = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def expire(self, key, ttl):
        self.ttls[key] = int(ttl)
        return True

    def ttl(self, key):
        return self.ttls.get(key, -1)

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)
        return 1

    def pipeline(self):
        return FakeRedisPipeline(self)


class FakeDBSession:
    async def execute(self, *args, **kwargs):
        return None


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._row)


class _FakeSessionFactory:
    def __init__(self, row):
        self._row = row

    def __call__(self):
        return _FakeSession(self._row)


def _make_user(
    *,
    user_id: str,
    tenant_id: str | None = None,
    role: UserRole,
    permissions_version: int = 0,
) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        tenant_id=tenant_id,
        email=f"{user_id}@example.com",
        hashed_password="hashed",
        full_name="Test User",
        role=role,
        permissions_version=permissions_version,
        is_active=True,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )


@pytest_asyncio.fixture
async def client(monkeypatch):
    app = FastAPI()
    configure_rate_limiting(app)
    app.include_router(auth_router)
    app.include_router(orgs_router)

    async def _override_get_db():
        yield FakeDBSession()

    app.dependency_overrides[get_db] = _override_get_db

    fake_redis = FakeRedis()
    monkeypatch.setattr(TokenService, "_get_redis_client", lambda self: fake_redis)
    monkeypatch.setattr(middleware, "_get_redis_client", lambda: fake_redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as async_client:
        yield async_client, fake_redis

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_access_token_embeds_permissions_version_and_jti(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(TokenService, "_get_redis_client", lambda self: fake_redis)

    user = _make_user(user_id="user-1", tenant_id="SH00000001", role=UserRole.VIEWER, permissions_version=7)
    token = TokenService().create_access_token(user, ["plant-1"])
    claims = jwt.get_unverified_claims(token)

    assert claims["permissions_version"] == 7
    assert claims["tenant_id"] == "SH00000001"
    assert claims["plant_ids"] == ["plant-1"]
    assert claims["jti"]
    assert fake_redis.smembers(f"user:tokens:{user.id}") == {claims["jti"]}


@pytest.mark.asyncio
async def test_decode_access_token_rejects_missing_tenant_id_claim(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(TokenService, "_get_redis_client", lambda self: fake_redis)

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "email": "user-1@example.com",
            "role": "viewer",
            "plant_ids": ["plant-1"],
            "permissions_version": 7,
            "tenant_entitlements_version": 0,
            "type": "access",
            "jti": "jti-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        os.environ["JWT_SECRET_KEY"],
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc_info:
        TokenService().decode_access_token(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_decode_access_token_accepts_canonical_tenant_id_only_claims(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(TokenService, "_get_redis_client", lambda self: fake_redis)

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "email": "user-1@example.com",
            "tenant_id": "SH00000001",
            "role": "viewer",
            "plant_ids": ["plant-1"],
            "permissions_version": 7,
            "tenant_entitlements_version": 0,
            "type": "access",
            "jti": "jti-tenant-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        os.environ["JWT_SECRET_KEY"],
        algorithm="HS256",
    )

    claims = TokenService().decode_access_token(token)
    assert claims["tenant_id"] == "SH00000001"
    assert claims["tenant_id"] == "SH00000001"


@pytest.mark.asyncio
async def test_assert_tenant_access_uses_effective_tenant_claim():
    claims = {"role": "org_admin", "tenant_id": "org-a"}

    assert_tenant_access(claims, "org-a")

    with pytest.raises(HTTPException):
        assert_tenant_access(claims, "org-b")


@pytest.mark.asyncio
async def test_deactivate_user_revokes_access_token(client, monkeypatch):
    async_client, _ = client
    admin_user = _make_user(user_id="admin-1", tenant_id="org-a", role=UserRole.ORG_ADMIN, permissions_version=1)
    target_user = _make_user(user_id="user-2", tenant_id="org-a", role=UserRole.VIEWER, permissions_version=1)

    admin_token = TokenService().create_access_token(admin_user, [])
    target_token = TokenService().create_access_token(target_user, ["plant-1"])

    monkeypatch.setattr(orgs_api.user_repo, "get_by_id_for_tenant", AsyncMock(return_value=target_user))
    monkeypatch.setattr(orgs_api.user_repo, "update", AsyncMock(return_value=target_user))
    monkeypatch.setattr(orgs_api.user_repo, "increment_permissions_version", AsyncMock(return_value=target_user))
    get_user_by_claims = AsyncMock(return_value=target_user)
    monkeypatch.setattr(auth_api.auth_svc, "get_user_by_token_claims", get_user_by_claims)

    deactivate_response = await async_client.patch(
        "/api/v1/tenants/org-a/users/user-2/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert deactivate_response.status_code == 200


@pytest.mark.asyncio
async def test_me_response_exposes_canonical_tenant_id_only(client, monkeypatch):
    async_client, _ = client
    user = _make_user(user_id="user-me", tenant_id="SH00000001", role=UserRole.ORG_ADMIN, permissions_version=2)
    access_token = TokenService().create_access_token(user, [])
    org = type(
        "Org",
        (),
        {
            "id": "SH00000001",
            "name": "Org A",
            "slug": "org-a",
            "is_active": True,
            "premium_feature_grants_json": [],
            "role_feature_matrix_json": {"org_admin": []},
            "entitlements_version": 0,
            "created_at": datetime.now(UTC),
        },
    )()

    monkeypatch.setattr(auth_api.auth_svc, "get_user_by_token_claims", AsyncMock(return_value=user))
    monkeypatch.setattr(auth_api.org_repo, "get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(auth_api.user_repo, "get_plant_ids", AsyncMock(return_value=[]))

    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["tenant_id"] == "SH00000001"
@pytest.mark.asyncio
async def test_login_rejects_suspended_org(client, monkeypatch):
    async_client, _ = client
    user = _make_user(user_id="user-3", tenant_id="org-1", role=UserRole.VIEWER, permissions_version=1)
    org = type("Org", (), {"is_active": False})()

    monkeypatch.setattr(user_repo, "get_by_email", AsyncMock(return_value=user))
    monkeypatch.setattr(auth_service_module.pwd_ctx, "verify", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(org_repo, "get_by_id", AsyncMock(return_value=org))
    create_token = Mock()
    store_token = AsyncMock()
    monkeypatch.setattr(auth_service_module.token_svc, "create_access_token", create_token)
    monkeypatch.setattr(auth_service_module.token_svc, "store_refresh_token", store_token)

    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "user-3@example.com", "password": "secret"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORG_SUSPENDED"
    create_token.assert_not_called()
    store_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_service_rejects_stale_permissions_version(monkeypatch):
    user = _make_user(user_id="user-4", tenant_id="org-1", role=UserRole.VIEWER, permissions_version=4)
    org = type("Org", (), {"is_active": True})()

    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(org_repo, "get_by_id", AsyncMock(return_value=org))

    with pytest.raises(Exception) as exc:
        await AuthService().get_user_by_token_claims(
            db=object(),
            claims={"sub": "user-4", "permissions_version": 3},
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_auth_service_rejects_inactive_org_on_refresh(monkeypatch):
    user = _make_user(user_id="user-5", tenant_id="org-1", role=UserRole.VIEWER, permissions_version=2)
    org = type("Org", (), {"is_active": False})()

    monkeypatch.setattr(auth_service_module.token_svc, "validate_refresh_token", AsyncMock(return_value=type("Refresh", (), {"user_id": user.id})()))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(org_repo, "get_by_id", AsyncMock(return_value=org))
    revoke_token = AsyncMock()
    monkeypatch.setattr(auth_service_module.token_svc, "revoke_refresh_token", revoke_token)

    with pytest.raises(Exception) as exc:
        await AuthService().refresh(db=object(), raw_refresh_token="refresh-token")

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_SUSPENDED"
    revoke_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_service_accept_invitation_activates_user_and_revokes_tokens(monkeypatch):
    user = _make_user(user_id="user-6", tenant_id="org-1", role=UserRole.VIEWER, permissions_version=2)
    user.is_active = False
    token_row = type("TokenRow", (), {"user_id": user.id})()
    revoke_all = AsyncMock()

    monkeypatch.setattr(action_token_svc, "consume_token", AsyncMock(return_value=token_row))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(org_repo, "get_by_id", AsyncMock(return_value=type("Org", (), {"is_active": True})()))
    monkeypatch.setattr(auth_service_module.token_svc, "revoke_all_user_tokens", revoke_all)
    monkeypatch.setattr(auth_service_module.pwd_ctx, "hash", lambda value: f"hashed::{value}")

    class FakeDB:
        async def flush(self):
            return None

    await AuthService().accept_invitation(
        FakeDB(),
        token="invite-token",
        password="Password123!",
        confirm_password="Password123!",
    )

    assert user.is_active is True
    assert user.hashed_password == "hashed::Password123!"
    revoke_all.assert_awaited_once_with(ANY, user.id)


@pytest.mark.asyncio
async def test_auth_service_password_reset_revokes_all_sessions(monkeypatch):
    user = _make_user(user_id="user-7", tenant_id="org-1", role=UserRole.VIEWER, permissions_version=2)
    token_row = type("TokenRow", (), {"user_id": user.id})()
    revoke_all = AsyncMock()

    monkeypatch.setattr(action_token_svc, "consume_token", AsyncMock(return_value=token_row))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(org_repo, "get_by_id", AsyncMock(return_value=type("Org", (), {"is_active": True})()))
    monkeypatch.setattr(auth_service_module.token_svc, "revoke_all_user_tokens", revoke_all)
    monkeypatch.setattr(auth_service_module.pwd_ctx, "hash", lambda value: f"hashed::{value}")

    class FakeDB:
        async def flush(self):
            return None

    await AuthService().reset_password(
        FakeDB(),
        token="reset-token",
        password="Password123!",
        confirm_password="Password123!",
    )

    assert user.hashed_password == "hashed::Password123!"
    revoke_all.assert_awaited_once_with(ANY, user.id)


@pytest.mark.asyncio
async def test_auth_service_password_reset_generic_for_unknown_email(monkeypatch):
    send_reset = AsyncMock()
    monkeypatch.setattr(user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(mailer_svc, "send_password_reset_email", send_reset)

    class FakeDB:
        pass

    await AuthService().request_password_reset(FakeDB(), email="missing@example.com")
    send_reset.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_middleware_accepts_current_permissions_version(monkeypatch):
    row = {
        "permissions_version": 9,
        "user_is_active": True,
        "tenant_id": "org-1",
        "tenant_is_active": True,
        "tenant_entitlements_version": 0,
    }
    monkeypatch.setattr(middleware, "_get_auth_session_factory", lambda: _FakeSessionFactory(row))
    monkeypatch.setattr(middleware, "_get_redis_client", lambda: FakeRedis())

    await middleware._assert_token_is_current(
        {"sub": "user-3", "permissions_version": 9, "tenant_id": "org-1", "tenant_entitlements_version": 0}
    )


@pytest.mark.asyncio
async def test_shared_middleware_rejects_token_revoked(monkeypatch):
    fake_redis = FakeRedis()
    fake_redis.set("token:revoked:revoked-jti", "1", ex=300)
    monkeypatch.setattr(middleware, "_get_redis_client", lambda: fake_redis)

    with pytest.raises(Exception) as exc:
        middleware._assert_token_not_revoked({"jti": "revoked-jti"})

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_shared_middleware_rejects_stale_permissions_version(monkeypatch):
    row = {
        "permissions_version": 10,
        "user_is_active": True,
        "tenant_id": "org-1",
        "tenant_is_active": True,
        "tenant_entitlements_version": 0,
    }
    monkeypatch.setattr(middleware, "_get_auth_session_factory", lambda: _FakeSessionFactory(row))

    with pytest.raises(JWTError):
        await middleware._assert_token_is_current(
            {"sub": "user-3", "permissions_version": 9, "tenant_id": "org-1", "tenant_entitlements_version": 0}
        )


@pytest.mark.asyncio
async def test_shared_middleware_rejects_inactive_org(monkeypatch):
    row = {
        "permissions_version": 9,
        "user_is_active": True,
        "tenant_id": "org-1",
        "tenant_is_active": False,
        "tenant_entitlements_version": 0,
    }
    monkeypatch.setattr(middleware, "_get_auth_session_factory", lambda: _FakeSessionFactory(row))

    with pytest.raises(JWTError):
        await middleware._assert_token_is_current(
            {"sub": "user-3", "permissions_version": 9, "tenant_id": "org-1", "tenant_entitlements_version": 0}
        )
