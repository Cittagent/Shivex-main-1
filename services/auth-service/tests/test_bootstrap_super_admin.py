import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select


AUTH_SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path = [p for p in sys.path if p not in {str(AUTH_SERVICE_ROOT), str(REPO_ROOT)}]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AUTH_SERVICE_ROOT))

for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

os.chdir(AUTH_SERVICE_ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long")

from app.models.auth import Base, User, UserRole
from app.services import bootstrap_service
from app.services.bootstrap_service import ensure_bootstrap_super_admin
from app.config import settings


@pytest.mark.asyncio
async def test_ensure_bootstrap_super_admin_creates_exactly_one_user(monkeypatch):
    monkeypatch.setattr(settings, "BOOTSTRAP_SUPER_ADMIN_EMAIL", "manash.ray@cittagent.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_SUPER_ADMIN_PASSWORD", "Shivex@2706")
    monkeypatch.setattr(settings, "BOOTSTRAP_SUPER_ADMIN_FULL_NAME", "Shivex Super-Admin")
    monkeypatch.setattr(bootstrap_service.pwd_ctx, "hash", lambda secret: f"hashed::{secret}")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        created = await ensure_bootstrap_super_admin(session)
        assert created is True

    async with session_factory() as session:
        created_again = await ensure_bootstrap_super_admin(session)
        assert created_again is False
        users = (await session.execute(select(User).order_by(User.email.asc()))).scalars().all()
        assert len(users) == 1
        assert users[0].email == "manash.ray@cittagent.com"
        assert users[0].hashed_password == "hashed::Shivex@2706"
        assert users[0].role == UserRole.SUPER_ADMIN
        assert users[0].is_active is True

    await engine.dispose()
