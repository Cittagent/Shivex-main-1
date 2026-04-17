"""Result repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.schemas import JobStatus

UNSET = object()


class ResultRepository(ABC):
    """Abstract interface for analytics result storage."""

    @abstractmethod
    async def create_job(
        self,
        job_id: str,
        device_id: str,
        analysis_type: str,
        model_name: str,
        date_range_start: datetime,
        date_range_end: datetime,
        parameters: Optional[Dict[str, Any]],
    ) -> None:
        pass

    @abstractmethod
    async def get_job(self, job_id: str) -> Any:
        pass

    @abstractmethod
    async def get_job_scoped(
        self,
        job_id: str,
        tenant_id: Optional[str] = None,
        accessible_device_ids: Optional[list[str]] = None,
    ) -> Any:
        pass

    @abstractmethod
    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error_message: Optional[str] = None,
        phase: Optional[str] = None,
        phase_label: Optional[str] = None,
        phase_progress: Optional[float] = None,
    ) -> None:
        pass

    @abstractmethod
    async def update_job_progress(
        self,
        job_id: str,
        progress: float,
        message: str,
        phase: Optional[str] = None,
        phase_label: Optional[str] = None,
        phase_progress: Optional[float] = None,
    ) -> None:
        pass

    @abstractmethod
    async def save_results(
        self,
        job_id: str,
        results: Dict[str, Any],
        accuracy_metrics: Optional[Dict[str, float]],
        execution_time_seconds: int,
    ) -> None:
        pass

    @abstractmethod
    async def list_jobs(
        self,
        status: Optional[str] = None,
        device_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        accessible_device_ids: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Any]:
        pass

    @abstractmethod
    async def update_job_queue_metadata(
        self,
        job_id: str,
        attempt: Optional[int] = None,
        queue_position: Optional[int] = None,
        queue_enqueued_at: Optional[datetime] | object = UNSET,
        queue_started_at: Optional[datetime] | object = UNSET,
        worker_lease_expires_at: Optional[datetime] | object = UNSET,
        last_heartbeat_at: Optional[datetime] | object = UNSET,
        error_code: Optional[str] | object = UNSET,
    ) -> None:
        pass

    # -------------------------------------------------
    # ✅ REQUIRED for async SQLAlchemy correctness
    # -------------------------------------------------
    @abstractmethod
    async def rollback(self) -> None:
        """Rollback current transaction."""
        pass

    @abstractmethod
    async def count_jobs(
        self,
        statuses: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        attempts_gte: Optional[int] = None,
    ) -> int:
        """Return count of jobs matching the given filters."""
        pass

    @abstractmethod
    async def list_tenant_job_counts(
        self,
        statuses: Optional[list[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return top tenants by job volume for the given statuses."""
        pass

    @abstractmethod
    async def list_jobs_for_parent(
        self,
        parent_job_id: str,
    ) -> List[Any]:
        """Return child jobs for a fleet parent ordered by creation time."""
        pass

    @abstractmethod
    async def get_model_artifact(
        self,
        device_id: str,
        analysis_type: str,
        model_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Return latest artifact payload + metadata for model or None."""
        pass

    @abstractmethod
    async def upsert_model_artifact(
        self,
        device_id: str,
        analysis_type: str,
        model_key: str,
        feature_schema_hash: str,
        artifact_payload: bytes,
        model_version: str = "v1",
        metrics: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Create/update latest artifact for device/model/schema."""
        pass
