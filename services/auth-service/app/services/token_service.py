from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from jose import JWTError, jwt
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth import RefreshToken, User
from services.shared.tenant_context import normalize_tenant_id

UTC = timezone.utc
logger = logging.getLogger(__name__)
_REDIS_CLIENT: Redis | None = None


def _as_utc_datetime(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    raise ValueError("Unsupported token timestamp")


class TokenService:
    def _get_redis_client(self) -> Redis:
        global _REDIS_CLIENT
        if _REDIS_CLIENT is None:
            _REDIS_CLIENT = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return _REDIS_CLIENT

    def _revoked_key(self, jti: str) -> str:
        return f"token:revoked:{jti}"

    def _issued_key(self, user_id: str, jti: str) -> str:
        return f"user:token:{user_id}:{jti}"

    def _issued_index_key(self, user_id: str) -> str:
        return f"user:tokens:{user_id}"

    def _expires_in_seconds(self, exp_value) -> int:
        expires_at = _as_utc_datetime(exp_value)
        remaining = int((expires_at - datetime.now(UTC)).total_seconds())
        return max(1, remaining)

    def _track_access_token(self, user_id: str, jti: str, expires_in_seconds: int) -> None:
        client = self._get_redis_client()
        issued_key = self._issued_key(user_id, jti)
        index_key = self._issued_index_key(user_id)
        try:
            pipe = client.pipeline()
            pipe.set(issued_key, "1", ex=max(1, expires_in_seconds))
            pipe.sadd(index_key, jti)
            pipe.expire(index_key, max(1, expires_in_seconds))
            pipe.execute()
        except RedisError as exc:
            logger.warning("Failed to track issued access token", extra={"user_id": user_id, "jti": jti, "error": str(exc)})

    def create_access_token(
        self,
        user: User,
        plant_ids: list[str],
        *,
        tenant_entitlements_version: int | None = 0,
    ) -> str:
        if not settings.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY must not be empty")

        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        jti = str(uuid4())
        tenant_id = user.tenant_id
        payload = {
            "sub": user.id,
            "email": user.email,
            "tenant_id": tenant_id,
            "role": user.role.value,
            "plant_ids": plant_ids,
            "permissions_version": getattr(user, "permissions_version", 0) or 0,
            "tenant_entitlements_version": tenant_entitlements_version,
            "full_name": user.full_name,
            "type": "access",
            "jti": jti,
            "iat": now,
            "exp": expires_at,
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        self._track_access_token(
            user_id=user.id,
            jti=jti,
            expires_in_seconds=max(1, int((expires_at - now).total_seconds())),
        )
        return token

    def decode_access_token(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_aud": False},
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            ) from exc

        if claims.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )

        if claims.get("permissions_version") is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )

        tenant_id = normalize_tenant_id(claims.get("tenant_id"))
        claims["tenant_id"] = tenant_id

        if tenant_id is not None and claims.get("tenant_entitlements_version") is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )

        if claims.get("role") != "super_admin" and tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )

        jti = claims.get("jti")
        if not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_TOKEN", "message": "Invalid token"},
            )
        try:
            if self.is_access_token_revoked(str(jti)):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "TOKEN_REVOKED", "message": "Token has been revoked"},
                )
        except RedisError as exc:
            logger.warning("Token revocation state unavailable", extra={"error": str(exc)})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "AUTH_STATE_UNAVAILABLE",
                    "message": "Authentication state is temporarily unavailable",
                },
            ) from exc

        return claims

    def is_access_token_revoked(self, jti: str) -> bool:
        client = self._get_redis_client()
        return client.get(self._revoked_key(jti)) is not None

    def revoke_access_token(self, jti: str, expires_in_seconds: int) -> None:
        client = self._get_redis_client()
        client.set(self._revoked_key(jti), "1", ex=max(1, expires_in_seconds))

    def revoke_access_token_from_claims(self, claims: dict) -> None:
        jti = claims.get("jti")
        exp = claims.get("exp")
        if not jti or exp is None:
            return
        self.revoke_access_token(str(jti), self._expires_in_seconds(exp))

    def revoke_all_known_access_tokens(self, user_id: str) -> None:
        client = self._get_redis_client()
        index_key = self._issued_index_key(user_id)
        try:
            token_jtis = client.smembers(index_key)
            if not token_jtis:
                return
            pipe = client.pipeline()
            for jti in token_jtis:
                issued_key = self._issued_key(user_id, jti)
                ttl = client.ttl(issued_key)
                if ttl is not None and ttl > 0:
                    pipe.set(self._revoked_key(jti), "1", ex=ttl)
                pipe.delete(issued_key)
                pipe.srem(index_key, jti)
            pipe.execute()
        except RedisError as exc:
            logger.warning("Failed to revoke known access tokens", extra={"user_id": user_id, "error": str(exc)})
            raise

    def _hash_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def generate_refresh_token_pair(self) -> tuple[str, str]:
        raw_token = secrets.token_urlsafe(64)
        return raw_token, self._hash_token(raw_token)

    async def store_refresh_token(self, db: AsyncSession, user_id: str, token_hash: str) -> RefreshToken:
        now = datetime.now(UTC)
        token = RefreshToken(
            id=str(uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            created_at=now,
        )
        db.add(token)
        await db.flush()
        return token

    async def validate_refresh_token(self, db: AsyncSession, raw_token: str) -> RefreshToken:
        token_hash = self._hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        refresh_token = result.scalar_one_or_none()
        if refresh_token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_REFRESH_TOKEN", "message": "Invalid refresh token"},
            )

        if refresh_token.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "REFRESH_TOKEN_REVOKED", "message": "Refresh token revoked"},
            )

        expires_at = refresh_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "REFRESH_TOKEN_EXPIRED", "message": "Refresh token expired"},
            )

        return refresh_token

    async def revoke_refresh_token(self, db: AsyncSession, raw_token: str) -> None:
        token_hash = self._hash_token(raw_token)
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_user_tokens(self, db: AsyncSession, user_id: str) -> None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        self.revoke_all_known_access_tokens(user_id)


def revoke_access_token(jti: str, expires_in_seconds: int) -> None:
    TokenService().revoke_access_token(jti, expires_in_seconds)
