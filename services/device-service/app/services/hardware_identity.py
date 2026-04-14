"""Helpers for persistent hardware unit identity allocation."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import HardwareUnitSequence
from app.services.device_errors import HardwareUnitIdAllocationError

_HARDWARE_UNIT_PREFIX = "HWU"
_SEQUENCE_WIDTH = 8
_MAX_SEQUENCE_VALUE = 99_999_999
_ALLOCATION_ATTEMPTS = 20


def format_hardware_unit_id(sequence_value: int) -> str:
    if sequence_value < 1 or sequence_value > _MAX_SEQUENCE_VALUE:
        raise HardwareUnitIdAllocationError(
            f"Sequence value {sequence_value} is outside the supported hardware unit ID range"
        )
    return f"{_HARDWARE_UNIT_PREFIX}{sequence_value:0{_SEQUENCE_WIDTH}d}"


class HardwareUnitIdAllocator:
    """Allocates platform-wide hardware unit IDs from a persistent sequence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate(self) -> str:
        for _ in range(_ALLOCATION_ATTEMPTS):
            current_value = await self._load_current_value()
            if current_value is None:
                raise HardwareUnitIdAllocationError(
                    "Hardware unit ID sequence is not configured. Run the device-service migration before creating hardware units."
                )
            if current_value > _MAX_SEQUENCE_VALUE:
                raise HardwareUnitIdAllocationError("Hardware unit ID sequence is exhausted")

            result = await self._session.execute(
                update(HardwareUnitSequence)
                .where(
                    HardwareUnitSequence.prefix == _HARDWARE_UNIT_PREFIX,
                    HardwareUnitSequence.next_value == current_value,
                )
                .values(next_value=current_value + 1)
            )
            if int(result.rowcount or 0) == 1:
                return format_hardware_unit_id(current_value)

        raise HardwareUnitIdAllocationError("Unable to allocate a unique hardware unit ID")

    async def _load_current_value(self) -> int | None:
        result = await self._session.execute(
            select(HardwareUnitSequence.next_value).where(
                HardwareUnitSequence.prefix == _HARDWARE_UNIT_PREFIX
            )
        )
        value = result.scalar_one_or_none()
        return int(value) if value is not None else None
