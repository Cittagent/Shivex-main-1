"""Tests for analytics status payload enrichment."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests._bootstrap import bootstrap_test_imports

bootstrap_test_imports()

from src.api.routes import analytics


class _Ctx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_build_status_response_exposes_phase_and_eta(monkeypatch):
    now = datetime.now(timezone.utc)
    job = SimpleNamespace(
        status="running",
        progress=61.5,
        message="Running model execution",
        error_message=None,
        error_code=None,
        created_at=now,
        started_at=now,
        completed_at=None,
        queue_position=9,
        attempt=1,
        worker_lease_expires_at=None,
        phase="model_execution",
        phase_label="Running model execution",
        phase_progress=0.33,
    )

    monkeypatch.setattr(analytics, "async_session_maker", lambda: _Ctx())

    class _FakeEstimator:
        def __init__(self, _session):
            pass

        async def estimate(self, _job):
            return SimpleNamespace(
                queue_position=2,
                estimated_wait_seconds=120,
                estimated_completion_seconds=300,
                estimate_quality="medium",
            )

    monkeypatch.setattr(analytics, "JobStatusEstimator", _FakeEstimator)

    response = await analytics._build_status_response("job-1", job)

    assert response.phase == "model_execution"
    assert response.phase_label == "Running model execution"
    assert response.phase_progress == pytest.approx(0.33)
    assert response.queue_position == 2
    assert response.estimated_wait_seconds == 120
    assert response.estimated_completion_seconds == 300
    assert response.estimate_quality == "medium"
