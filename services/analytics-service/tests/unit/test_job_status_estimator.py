"""Tests for history-backed job status estimation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests._bootstrap import bootstrap_test_imports

bootstrap_test_imports()

from src.services.job_status_estimator import JobStatusEstimator


class _Result:
    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)

    async def execute(self, _query):
        if not self._responses:
            raise AssertionError("No response left for execute()")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_pending_wait_uses_history_runtime_not_placeholder_queue_math():
    now = datetime.now(timezone.utc)
    completed_rows = [
        SimpleNamespace(
            execution_time_seconds=120,
            date_range_start=now - timedelta(days=2),
            date_range_end=now - timedelta(days=1),
            device_id="D1",
            parameters={},
        )
        for _ in range(12)
    ]
    session = _Session(
        [
            _Result(rows=completed_rows),
            _Result(scalar_value=2),
            _Result(scalar_value=3),
        ]
    )
    estimator = JobStatusEstimator(session)
    job = SimpleNamespace(
        status="pending",
        analysis_type="anomaly",
        device_id="D1",
        parameters={},
        created_at=now,
        date_range_start=now - timedelta(days=1),
        date_range_end=now,
        started_at=None,
    )

    estimate = await estimator.estimate(job)

    assert estimate.queue_position == 3
    # (queue_position + 1) * expected_runtime / active_workers = 4 * 120 / 2 = 240
    assert estimate.estimated_wait_seconds == 240
    assert estimate.estimated_wait_seconds != 15
    assert estimate.estimate_quality == "medium"


@pytest.mark.asyncio
async def test_running_job_reports_completion_eta_from_elapsed_time():
    now = datetime.now(timezone.utc)
    completed_rows = [
        SimpleNamespace(
            execution_time_seconds=180,
            date_range_start=now - timedelta(days=2),
            date_range_end=now - timedelta(days=1),
            device_id="ALL",
            parameters={"fleet_mode": "best_effort_exact"},
        )
        for _ in range(24)
    ]
    session = _Session(
        [
            _Result(rows=completed_rows),
            _Result(scalar_value=4),
        ]
    )
    estimator = JobStatusEstimator(session)
    job = SimpleNamespace(
        status="running",
        analysis_type="prediction",
        device_id="ALL",
        parameters={"fleet_mode": "best_effort_exact"},
        created_at=now,
        date_range_start=now - timedelta(days=1),
        date_range_end=now,
        started_at=now - timedelta(seconds=60),
    )

    estimate = await estimator.estimate(job)

    assert estimate.queue_position is None
    assert estimate.estimated_wait_seconds is None
    assert estimate.estimated_completion_seconds is not None
    assert 100 <= estimate.estimated_completion_seconds <= 140
    assert estimate.estimate_quality == "high"
