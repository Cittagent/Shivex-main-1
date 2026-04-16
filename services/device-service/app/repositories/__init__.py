"""Repository exports."""

from app.repositories.device import DeviceRepository
from app.repositories.device_state_intervals import DeviceStateIntervalRepository

__all__ = ["DeviceRepository", "DeviceStateIntervalRepository"]
