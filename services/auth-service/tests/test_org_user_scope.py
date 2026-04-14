import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


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
from app.api.v1 import admin as admin_api
from app.api.v1.admin import router as admin_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1 import orgs as orgs_api
from app.services import auth_service as auth_service_module
from app.database import get_db
from app.models.auth import Plant, User, UserRole
from app.rate_limit import configure_rate_limiting
from app.services.token_service import TokenService
from services.shared.feature_entitlements import build_feature_entitlement_state


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


def _make_user(*, user_id: str, tenant_id: str | None = None, role: UserRole) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        tenant_id=tenant_id,
        email=f"{user_id}@example.com",
        hashed_password="hashed",
        full_name="Test User",
        role=role,
        permissions_version=0,
        is_active=True,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )


def _make_plant(*, plant_id: str, tenant_id: str | None = None) -> Plant:
    now = datetime.now(UTC)
    return Plant(
        id=plant_id,
        tenant_id=tenant_id,
        name=f"Plant {plant_id}",
        location="Test",
        timezone="Asia/Kolkata",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _make_org(*, tenant_id: str, premium_feature_grants_json=None, role_feature_matrix_json=None, entitlements_version: int = 0):
    return type(
        "Org",
        (),
        {
            "id": tenant_id,
            "name": f"Org {tenant_id}",
            "slug": f"org-{tenant_id}",
            "is_active": True,
            "premium_feature_grants_json": premium_feature_grants_json or [],
            "role_feature_matrix_json": role_feature_matrix_json or {"plant_manager": [], "operator": [], "viewer": []},
            "entitlements_version": entitlements_version,
        },
    )()


@pytest_asyncio.fixture
async def client(monkeypatch):
    app = FastAPI()
    configure_rate_limiting(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(orgs_router)

    async def _override_get_db():
        yield FakeDBSession()

    app.dependency_overrides[get_db] = _override_get_db

    fake_redis = FakeRedis()
    monkeypatch.setattr(TokenService, "_get_redis_client", lambda self: fake_redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as async_client:
        yield async_client, fake_redis

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_user_cross_org_returns_404(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])

    scoped_get = AsyncMock(return_value=None)
    update_mock = AsyncMock()

    monkeypatch.setattr(orgs_api.user_repo, "get_by_id_for_tenant", scoped_get)
    monkeypatch.setattr(orgs_api.user_repo, "update", update_mock)

    response = await async_client.patch(
        "/api/v1/tenants/org-a/users/user-b",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"full_name": "Changed Name"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "USER_NOT_FOUND"
    scoped_get.assert_awaited_once()
    update_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_rejects_foreign_plant_ids(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[_make_plant(plant_id="plant-a", tenant_id="org-a")]),
    )
    create_mock = AsyncMock()
    set_access_mock = AsyncMock()

    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda _: "hashed-password")

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "password": "Viewer1234!",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a", "plant-b"],
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "INVALID_PLANT_IDS"
    assert body["detail"]["rejected_ids"] == ["plant-b"]
    create_mock.assert_not_awaited()
    set_access_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_accepts_canonical_tenant_id_field(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[_make_plant(plant_id="plant-a", tenant_id="org-a")]),
    )
    created_user = _make_user(user_id="user-new", tenant_id="org-a", role=UserRole.VIEWER)
    create_mock = AsyncMock(return_value=created_user)
    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", AsyncMock())
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda _: "hashed-password")

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "password": "Viewer1234!",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a"],
        },
    )

    assert response.status_code == 201
    create_mock.assert_awaited_once_with(
        ANY,
        email="viewer@example.com",
        hashed_password="hashed-password",
        role=UserRole.VIEWER,
        tenant_id="org-a",
        full_name="Viewer",
    )
    assert response.json()["tenant_id"] == "org-a"
    assert response.json()["tenant_id"] == "org-a"


@pytest.mark.asyncio
async def test_create_plant_uses_canonical_tenant_route(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])
    created_plant = _make_plant(plant_id="plant-a", tenant_id="org-a")

    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    create_mock = AsyncMock(return_value=created_plant)
    monkeypatch.setattr(orgs_api.plant_repo, "create", create_mock)

    response = await async_client.post(
        "/api/v1/tenants/org-a/plants",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Plant A", "location": "Line 1", "timezone": "Asia/Kolkata"},
    )

    assert response.status_code == 201
    create_mock.assert_awaited_once_with(ANY, "org-a", "Plant A", "Line 1", "Asia/Kolkata")
    assert response.json()["tenant_id"] == "org-a"
    assert response.json()["tenant_id"] == "org-a"


@pytest.mark.asyncio
async def test_plant_manager_cannot_invite_elevated_roles(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="pm-a", tenant_id="org-a", role=UserRole.PLANT_MANAGER)
    access_token = TokenService().create_access_token(caller, ["plant-a"])

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    create_mock = AsyncMock()
    set_access_mock = AsyncMock()
    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "orgadmin@example.com",
            "password": "OrgAdmin123!",
            "full_name": "Org Admin",
            "role": "org_admin",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ROLE_ESCALATION_FORBIDDEN"
    create_mock.assert_not_awaited()
    set_access_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_list_users_accepts_tenant_id_query(client, monkeypatch):
    async_client, _ = client
    users = [_make_user(user_id="user-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)]

    list_mock = AsyncMock(return_value=users)
    monkeypatch.setattr(admin_api.user_repo, "list_by_tenant", list_mock)

    super_admin = _make_user(user_id="super-admin", tenant_id=None, role=UserRole.SUPER_ADMIN)
    access_token = TokenService().create_access_token(super_admin, [])

    response = await async_client.get(
        "/api/admin/users?tenant_id=org-a",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    list_mock.assert_awaited_once_with(ANY, "org-a")
    payload = response.json()
    assert payload[0]["tenant_id"] == "org-a"
    assert payload[0]["tenant_id"] == "org-a"


@pytest.mark.asyncio
async def test_create_org_still_works_for_super_admin(client, monkeypatch):
    async_client, _ = client
    now = datetime.now(UTC)
    created_org = type(
        "Org",
        (),
        {
            "id": "SH00000001",
            "name": "Org A",
            "slug": "org-a",
            "is_active": True,
            "created_at": now,
        },
    )()
    monkeypatch.setattr(admin_api.org_repo, "get_by_slug", AsyncMock(return_value=None))
    monkeypatch.setattr(admin_api.org_repo, "create", AsyncMock(return_value=created_org))

    super_admin = _make_user(user_id="super-admin", tenant_id=None, role=UserRole.SUPER_ADMIN)
    access_token = TokenService().create_access_token(super_admin, [])

    response = await async_client.post(
        "/api/admin/tenants",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Org A", "slug": "org-a"},
    )

    assert response.status_code == 201
    assert response.json()["id"] == "SH00000001"


@pytest.mark.asyncio
async def test_plant_manager_must_choose_exactly_one_plant(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="pm-a", tenant_id="org-a", role=UserRole.PLANT_MANAGER)
    access_token = TokenService().create_access_token(caller, ["plant-a", "plant-b"])

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[
            _make_plant(plant_id="plant-a", tenant_id="org-a"),
            _make_plant(plant_id="plant-b", tenant_id="org-a"),
        ]),
    )
    create_mock = AsyncMock()
    set_access_mock = AsyncMock()

    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda _: "hashed-password")

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "password": "Viewer1234!",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a", "plant-b"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INVALID_PLANT_IDS"
    create_mock.assert_not_awaited()
    set_access_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_without_password_sends_invite(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])
    created_user = _make_user(user_id="user-new", tenant_id="org-a", role=UserRole.VIEWER)

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[_make_plant(plant_id="plant-a", tenant_id="org-a")]),
    )
    create_mock = AsyncMock(return_value=created_user)
    set_access_mock = AsyncMock()
    send_invite_mock = AsyncMock()

    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)
    monkeypatch.setattr(orgs_api.auth_svc, "send_invitation", send_invite_mock)
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda *_args, **_kwargs: "hashed-password")

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a"],
        },
    )

    assert response.status_code == 201
    create_mock.assert_awaited_once()
    set_access_mock.assert_awaited_once_with(ANY, "user-new", ["plant-a"])
    send_invite_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_with_password_activates_user_without_invite(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])
    created_user = _make_user(user_id="user-new", tenant_id="org-a", role=UserRole.VIEWER)

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[_make_plant(plant_id="plant-a", tenant_id="org-a")]),
    )
    create_mock = AsyncMock(return_value=created_user)
    set_access_mock = AsyncMock()
    send_invite_mock = AsyncMock()

    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)
    monkeypatch.setattr(orgs_api.auth_svc, "send_invitation", send_invite_mock)
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda *_args, **_kwargs: "hashed-password")

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "password": "Viewer1234!",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a"],
        },
    )

    assert response.status_code == 201
    assert response.json()["is_active"] is True
    create_mock.assert_awaited_once()
    set_access_mock.assert_awaited_once_with(ANY, "user-new", ["plant-a"])
    send_invite_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_succeeds_when_invite_email_delivery_fails(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="admin-a", tenant_id="org-a", role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [])
    created_user = _make_user(user_id="user-new", tenant_id="org-a", role=UserRole.VIEWER)

    monkeypatch.setattr(orgs_api.user_repo, "get_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=type("Org", (), {"id": "org-a", "is_active": True})()),
    )
    monkeypatch.setattr(
        orgs_api.plant_repo,
        "list_by_tenant",
        AsyncMock(return_value=[_make_plant(plant_id="plant-a", tenant_id="org-a")]),
    )
    create_mock = AsyncMock(return_value=created_user)
    set_access_mock = AsyncMock()
    invalidate_mock = AsyncMock()
    create_token_mock = AsyncMock(return_value="invite-token")
    send_invite_mock = AsyncMock(side_effect=RuntimeError("smtp down"))

    monkeypatch.setattr(orgs_api.user_repo, "create", create_mock)
    monkeypatch.setattr(orgs_api.user_repo, "set_plant_access", set_access_mock)
    monkeypatch.setattr(orgs_api.pwd_ctx, "hash", lambda *_args, **_kwargs: "hashed-password")
    monkeypatch.setattr(auth_service_module.action_token_svc, "invalidate_open_tokens", invalidate_mock)
    monkeypatch.setattr(auth_service_module.action_token_svc, "create_token", create_token_mock)
    monkeypatch.setattr(auth_service_module.mailer_svc, "send_invite_email", send_invite_mock)

    response = await async_client.post(
        "/api/v1/tenants/org-a/users",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email": "viewer@example.com",
            "full_name": "Viewer",
            "role": "viewer",
            "tenant_id": "org-a",
            "plant_ids": ["plant-a"],
        },
    )

    assert response.status_code == 201
    create_mock.assert_awaited_once()
    set_access_mock.assert_awaited_once_with(ANY, "user-new", ["plant-a"])
    invalidate_mock.assert_awaited_once()
    create_token_mock.assert_awaited_once()
    send_invite_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_super_admin_can_read_org_entitlements(client, monkeypatch):
    async_client, _ = client
    caller = _make_user(user_id="super-admin", tenant_id=None, role=UserRole.SUPER_ADMIN)
    access_token = TokenService().create_access_token(caller, [])

    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(
            return_value=_make_org(
                tenant_id="org-a",
                premium_feature_grants_json=["analytics", "reports"],
                role_feature_matrix_json={"plant_manager": ["analytics"], "operator": [], "viewer": []},
                entitlements_version=0,
            )
        ),
    )

    response = await async_client.get(
        "/api/v1/tenants/org-a/entitlements",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["premium_feature_grants"] == ["analytics", "reports"]
    assert payload["available_features"] == ["machines", "calendar", "rules", "settings", "analytics", "reports"]


@pytest.mark.asyncio
async def test_org_admin_cannot_delegate_ungranted_premium_features(client, monkeypatch):
    async_client, _ = client
    tenant_id = "SH00000001"
    caller = _make_user(user_id="fb441ba8-ee0b-49b3-9564-27cdfee43a93", tenant_id=tenant_id, role=UserRole.ORG_ADMIN)
    access_token = TokenService().create_access_token(caller, [], tenant_entitlements_version=0)

    monkeypatch.setattr(
        orgs_api.org_repo,
        "get_by_id",
        AsyncMock(return_value=_make_org(tenant_id=tenant_id)),
    )

    response = await async_client.put(
        f"/api/v1/tenants/{tenant_id}/entitlements",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "role_feature_matrix": {
                "plant_manager": ["analytics"],
                "operator": [],
                "viewer": [],
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FEATURE_SCOPE_DENIED"


def test_entitlement_loader_accepts_stringified_json():
    state = build_feature_entitlement_state(
        role="org_admin",
        premium_feature_grants='["analytics", "reports"]',
        role_feature_matrix='{"plant_manager": ["analytics"], "operator": [], "viewer": []}',
        entitlements_version=2,
    )

    assert state.premium_feature_grants_list == ["analytics", "reports"]
    assert state.available_features == ("machines", "calendar", "rules", "settings", "analytics", "reports")
    assert state.effective_features_by_role["plant_manager"] == ("machines", "rules", "settings", "analytics")
