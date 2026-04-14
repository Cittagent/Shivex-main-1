"""Helpers for persistent device identity allocation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import DeviceIdClass, DeviceIdSequence
from app.services.device_errors import DeviceIdAllocationError

_SEQUENCE_WIDTH = 8
_MAX_SEQUENCE_VALUE = 99_999_999
_ALLOCATION_ATTEMPTS = 20


@dataclass(frozen=True)
class DeviceIdClassDefinition:
    value: str
    prefix: str
    label: str


DEVICE_ID_CLASS_DEFINITIONS: tuple[DeviceIdClassDefinition, ...] = (
    DeviceIdClassDefinition(DeviceIdClass.ACTIVE.value, "AD", "Active Device"),
    DeviceIdClassDefinition(DeviceIdClass.TEST.value, "TD", "Test Device"),
    DeviceIdClassDefinition(DeviceIdClass.VIRTUAL.value, "VD", "Virtual Device"),
)
DEVICE_ID_CLASS_PREFIXES = {definition.value: definition.prefix for definition in DEVICE_ID_CLASS_DEFINITIONS}


def normalize_device_id_class(device_id_class: str) -> str:
    normalized = (device_id_class or "").strip().lower()
    if normalized not in DEVICE_ID_CLASS_PREFIXES:
        valid_values = ", ".join(sorted(DEVICE_ID_CLASS_PREFIXES))
        raise DeviceIdAllocationError(f"Unsupported device_id_class '{device_id_class}'. Expected one of: {valid_values}")
    return normalized


def format_device_id(prefix: str, sequence_value: int) -> str:
    if sequence_value < 1 or sequence_value > _MAX_SEQUENCE_VALUE:
        raise DeviceIdAllocationError(f"Sequence value {sequence_value} is outside the supported device ID range")
    return f"{prefix}{sequence_value:0{_SEQUENCE_WIDTH}d}"


class DeviceIdAllocator:
    """Allocates platform-wide device IDs from persistent per-prefix sequences."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate(self, device_id_class: str) -> str:
        normalized_class = normalize_device_id_class(device_id_class)
        prefix = DEVICE_ID_CLASS_PREFIXES[normalized_class]

        for _ in range(_ALLOCATION_ATTEMPTS):
            current_value = await self._load_current_value(prefix)
            if current_value is None:
                raise DeviceIdAllocationError(
                    f"Device ID sequence is not configured for prefix '{prefix}'. Run the device-service migration/reset before creating devices."
                )
            if current_value > _MAX_SEQUENCE_VALUE:
                raise DeviceIdAllocationError(f"Device ID sequence for prefix '{prefix}' is exhausted")

            result = await self._session.execute(
                update(DeviceIdSequence)
                .where(
                    DeviceIdSequence.prefix == prefix,
                    DeviceIdSequence.next_value == current_value,
                )
                .values(next_value=current_value + 1)
            )
            if int(result.rowcount or 0) == 1:
                return format_device_id(prefix, current_value)

        raise DeviceIdAllocationError(f"Unable to allocate a unique device ID for prefix '{prefix}'")

    async def _load_current_value(self, prefix: str) -> int | None:
        result = await self._session.execute(
            select(DeviceIdSequence.next_value).where(DeviceIdSequence.prefix == prefix)
        )
        value = result.scalar_one_or_none()
        return int(value) if value is not None else None
