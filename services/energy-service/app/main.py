from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import settings
from app.services.broadcaster import energy_broadcaster
from shared.auth_middleware import AuthMiddleware
from services.shared.startup_contract import validate_startup_contract


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_startup_contract()
    await energy_broadcaster.start(settings.REDIS_URL, settings.ENERGY_STREAM_REDIS_CHANNEL)
    yield
    await energy_broadcaster.stop()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "energy-service"}


app.include_router(router)
