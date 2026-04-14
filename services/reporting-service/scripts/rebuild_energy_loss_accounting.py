from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTING_ROOT = REPO_ROOT / "services" / "reporting-service"
ENERGY_ROOT = REPO_ROOT / "services" / "energy-service"

for path in (REPORTING_ROOT, ENERGY_ROOT, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.config import settings as reporting_settings  # type: ignore  # noqa: E402
from src.services.influx_reader import influx_reader  # type: ignore  # noqa: E402
from app.models import EnergyDeviceDay, EnergyDeviceMonth, EnergyFleetDay, EnergyFleetMonth  # type: ignore  # noqa: E402
from services.shared.energy_accounting import aggregate_window  # type: ignore  # noqa: E402


TELEMETRY_FIELDS = [
    "power",
    "power_w",
    "active_power",
    "current",
    "voltage",
    "power_factor",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild canonical energy loss buckets for a date range.")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tenant-id", default=None, help="Optional tenant scope")
    parser.add_argument("--device-id", action="append", dest="device_ids", default=[], help="Optional device filter")
    return parser.parse_args()


def _service_headers(service_name: str, tenant_id: str | None = None) -> dict[str, str]:
    headers = {"X-Internal-Service": service_name}
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    return headers


async def _list_devices(client: httpx.AsyncClient, tenant_id: str | None) -> list[dict[str, Any]]:
    resp = await client.get(
        f"{reporting_settings.DEVICE_SERVICE_URL}/api/v1/devices",
        headers=_service_headers("energy-loss-rebuild", tenant_id),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"device list fetch failed: {resp.status_code}")
    payload = resp.json()
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    return [row for row in rows if isinstance(row, dict) and row.get("device_id")]


async def _device_meta(client: httpx.AsyncClient, device_id: str, tenant_id: str | None) -> dict[str, Any]:
    headers = _service_headers("energy-loss-rebuild", tenant_id)
    idle_resp, waste_resp, shift_resp = await asyncio.gather(
        client.get(f"{reporting_settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/idle-config", headers=headers),
        client.get(f"{reporting_settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/waste-config", headers=headers),
        client.get(f"{reporting_settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/shifts", headers=headers),
    )

    idle_payload = idle_resp.json() if idle_resp.status_code == 200 else {}
    waste_payload = waste_resp.json() if waste_resp.status_code == 200 else {}
    shift_payload = shift_resp.json() if shift_resp.status_code == 200 else {}

    idle_data = idle_payload.get("data", idle_payload) if isinstance(idle_payload, dict) else {}
    waste_data = waste_payload.get("data", waste_payload) if isinstance(waste_payload, dict) else {}
    shift_data = shift_payload.get("data", shift_payload) if isinstance(shift_payload, dict) else shift_payload

    return {
        "idle_threshold": idle_data.get("idle_current_threshold") if isinstance(idle_data, dict) else None,
        "over_threshold": waste_data.get("overconsumption_current_threshold_a") if isinstance(waste_data, dict) else None,
        "shifts": shift_data if isinstance(shift_data, list) else [],
    }


async def _recompute_device_day(
    session,
    device_id: str,
    day: date,
    tenant_id: str | None,
    meta: dict[str, Any],
    platform_tz: ZoneInfo,
) -> None:
    start_dt = datetime.combine(day, time.min)
    end_dt = datetime.combine(day, time.max)
    rows = await influx_reader.query_telemetry(
        device_id=device_id,
        start_dt=start_dt,
        end_dt=end_dt,
        fields=TELEMETRY_FIELDS,
    )
    accounting = aggregate_window(
        rows,
        platform_tz=platform_tz,
        shifts=meta.get("shifts") or [],
        idle_threshold=meta.get("idle_threshold"),
        over_threshold=meta.get("over_threshold"),
    )

    stmt = select(EnergyDeviceDay).where(EnergyDeviceDay.device_id == device_id, EnergyDeviceDay.day == day)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = EnergyDeviceDay(device_id=device_id, day=day)
        session.add(row)

    row.energy_kwh = round(accounting.total.energy_kwh, 6)
    row.idle_kwh = round(accounting.total.idle_kwh, 6)
    row.offhours_kwh = round(accounting.total.offhours_kwh, 6)
    row.overconsumption_kwh = round(accounting.total.overconsumption_kwh, 6)
    row.loss_kwh = round(accounting.total.total_loss_kwh, 6)
    row.version = int(row.version or 0) + 1


async def _rebuild_device_month(session, device_id: str, month_bucket: date) -> None:
    month_end = (month_bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = (
        await session.execute(
            select(EnergyDeviceDay).where(
                EnergyDeviceDay.device_id == device_id,
                EnergyDeviceDay.day >= month_bucket,
                EnergyDeviceDay.day < month_end,
            )
        )
    ).scalars().all()

    month = (
        await session.execute(
            select(EnergyDeviceMonth).where(
                EnergyDeviceMonth.device_id == device_id,
                EnergyDeviceMonth.month == month_bucket,
            )
        )
    ).scalar_one_or_none()
    if month is None:
        month = EnergyDeviceMonth(device_id=device_id, month=month_bucket)
        session.add(month)

    month.energy_kwh = round(sum(float(r.energy_kwh or 0.0) for r in rows), 6)
    month.idle_kwh = round(sum(float(r.idle_kwh or 0.0) for r in rows), 6)
    month.offhours_kwh = round(sum(float(r.offhours_kwh or 0.0) for r in rows), 6)
    month.overconsumption_kwh = round(sum(float(r.overconsumption_kwh or 0.0) for r in rows), 6)
    month.loss_kwh = round(sum(float(r.loss_kwh or 0.0) for r in rows), 6)
    month.version = int(month.version or 0) + 1


async def _rebuild_fleet_day(session, day: date) -> None:
    rows = (await session.execute(select(EnergyDeviceDay).where(EnergyDeviceDay.day == day))).scalars().all()
    fleet = (await session.execute(select(EnergyFleetDay).where(EnergyFleetDay.day == day))).scalar_one_or_none()
    if fleet is None:
        fleet = EnergyFleetDay(day=day)
        session.add(fleet)

    fleet.energy_kwh = round(sum(float(r.energy_kwh or 0.0) for r in rows), 6)
    fleet.idle_kwh = round(sum(float(r.idle_kwh or 0.0) for r in rows), 6)
    fleet.offhours_kwh = round(sum(float(r.offhours_kwh or 0.0) for r in rows), 6)
    fleet.overconsumption_kwh = round(sum(float(r.overconsumption_kwh or 0.0) for r in rows), 6)
    fleet.loss_kwh = round(sum(float(r.loss_kwh or 0.0) for r in rows), 6)
    fleet.version = int(fleet.version or 0) + 1


async def _rebuild_fleet_month(session, month_bucket: date) -> None:
    month_end = (month_bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = (
        await session.execute(
            select(EnergyFleetDay).where(
                EnergyFleetDay.day >= month_bucket,
                EnergyFleetDay.day < month_end,
            )
        )
    ).scalars().all()
    fleet = (await session.execute(select(EnergyFleetMonth).where(EnergyFleetMonth.month == month_bucket))).scalar_one_or_none()
    if fleet is None:
        fleet = EnergyFleetMonth(month=month_bucket)
        session.add(fleet)

    fleet.energy_kwh = round(sum(float(r.energy_kwh or 0.0) for r in rows), 6)
    fleet.idle_kwh = round(sum(float(r.idle_kwh or 0.0) for r in rows), 6)
    fleet.offhours_kwh = round(sum(float(r.offhours_kwh or 0.0) for r in rows), 6)
    fleet.overconsumption_kwh = round(sum(float(r.overconsumption_kwh or 0.0) for r in rows), 6)
    fleet.loss_kwh = round(sum(float(r.loss_kwh or 0.0) for r in rows), 6)
    fleet.version = int(fleet.version or 0) + 1


async def main() -> None:
    args = _parse_args()
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise SystemExit("end-date must be on or after start-date")

    engine = create_async_engine(
        reporting_settings.DATABASE_URL,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    platform_tz = ZoneInfo(reporting_settings.PLATFORM_TIMEZONE)

    async with httpx.AsyncClient(timeout=20.0) as client:
        devices = await _list_devices(client, args.tenant_id)
        if args.device_ids:
            selected = set(args.device_ids)
            devices = [d for d in devices if str(d.get("device_id")) in selected]
        meta_by_device = {
            str(device["device_id"]): await _device_meta(client, str(device["device_id"]), args.tenant_id)
            for device in devices
        }

    touched_days: set[date] = set()
    touched_months: set[date] = set()
    device_months: dict[str, set[date]] = defaultdict(set)

    async with session_factory() as session:
        cur = start
        while cur <= end:
            for device in devices:
                device_id = str(device["device_id"])
                await _recompute_device_day(session, device_id, cur, args.tenant_id, meta_by_device[device_id], platform_tz)
                month_bucket = cur.replace(day=1)
                device_months[device_id].add(month_bucket)
                touched_days.add(cur)
                touched_months.add(month_bucket)
            cur += timedelta(days=1)

        for device_id, months in device_months.items():
            for month_bucket in months:
                await _rebuild_device_month(session, device_id, month_bucket)

        for day in touched_days:
            await _rebuild_fleet_day(session, day)
        for month_bucket in touched_months:
            await _rebuild_fleet_month(session, month_bucket)

        await session.commit()

    await engine.dispose()
    influx_reader.close()


if __name__ == "__main__":
    asyncio.run(main())
