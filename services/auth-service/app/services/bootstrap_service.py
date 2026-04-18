from __future__ import annotations

from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth import User, UserRole

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
UTC = timezone.utc


async def ensure_bootstrap_super_admin(db: AsyncSession) -> bool:
    """Create the configured bootstrap super-admin exactly once."""
    existing_super_admin = await db.execute(
        select(User.id).where(User.role == UserRole.SUPER_ADMIN).limit(1)
    )
    if existing_super_admin.scalar_one_or_none() is not None:
        return False

    existing_email = await db.execute(
        select(User).where(User.email == settings.BOOTSTRAP_SUPER_ADMIN_EMAIL).limit(1)
    )
    conflicting_user = existing_email.scalar_one_or_none()
    if conflicting_user is not None and conflicting_user.role != UserRole.SUPER_ADMIN:
        raise RuntimeError(
            "STARTUP BLOCKED: BOOTSTRAP_SUPER_ADMIN_EMAIL is already used by a non-super-admin user."
        )

    if conflicting_user is None:
        db.add(
            User(
                email=settings.BOOTSTRAP_SUPER_ADMIN_EMAIL,
                hashed_password=pwd_ctx.hash(settings.BOOTSTRAP_SUPER_ADMIN_PASSWORD),
                full_name=settings.BOOTSTRAP_SUPER_ADMIN_FULL_NAME,
                role=UserRole.SUPER_ADMIN,
                tenant_id=None,
                is_active=True,
                activated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    else:
        conflicting_user.hashed_password = pwd_ctx.hash(settings.BOOTSTRAP_SUPER_ADMIN_PASSWORD)
        conflicting_user.full_name = settings.BOOTSTRAP_SUPER_ADMIN_FULL_NAME
        conflicting_user.role = UserRole.SUPER_ADMIN
        conflicting_user.tenant_id = None
        conflicting_user.is_active = True
        conflicting_user.activated_at = datetime.now(UTC).replace(tzinfo=None)
        conflicting_user.deactivated_at = None

    await db.commit()
    return True
