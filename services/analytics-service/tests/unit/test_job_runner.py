"""Unit tests for job runner."""

import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pandas as pd

from tests._bootstrap import bootstrap_test_imports

bootstrap_test_imports()

from src.models.schemas import AnalyticsRequest, AnalyticsType, JobStatus
from src.services.job_runner import JobRunner
from src.utils.exceptions import DatasetNotFoundError


class TestJobRunner:
    """Tests for JobRunner."""
    
    @pytest.fixture
    def job_runner(self, mock_s3_client, mock_result_repository):
        """Create JobRunner instance with mocks."""
        from src.services.dataset_service import DatasetService
        
        dataset_service = DatasetService(mock_s3_client)
        return JobRunner(dataset_service, mock_result_repository)
    
    @pytest.mark.asyncio
    async def test_run_job_success(self, job_runner, mock_result_repository, sample_telemetry_data):
        """Test successful job execution."""
        # Mock dataset loading
        job_runner._dataset_service.load_dataset = AsyncMock(return_value=sample_telemetry_data)
        
        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="isolation_forest",
        )
        
        await job_runner.run_job("test-job-123", request)
        
        # Verify status updates
        assert mock_result_repository.update_job_status.called
        assert mock_result_repository.save_results.called
        
        # Verify job was marked completed
        final_call = mock_result_repository.update_job_status.call_args_list[-1]
        assert final_call.kwargs["status"] == JobStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_run_job_dataset_not_found(self, job_runner, mock_result_repository):
        """Test job failure when dataset not found."""
        job_runner._dataset_service.load_dataset = AsyncMock(
            side_effect=DatasetNotFoundError("Dataset not found")
        )
        
        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="isolation_forest",
        )
        
        with pytest.raises(Exception):
            await job_runner.run_job("test-job-123", request)
    
    @pytest.mark.asyncio
    async def test_run_job_updates_progress(self, job_runner, mock_result_repository, sample_telemetry_data):
        """Test that job progress is updated during execution."""
        job_runner._dataset_service.load_dataset = AsyncMock(return_value=sample_telemetry_data)
        
        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="isolation_forest",
        )
        
        await job_runner.run_job("test-job-123", request)
        
        # Verify progress updates were called
        assert mock_result_repository.update_job_progress.called
        
        # Check that progress increases
        progress_calls = [
            call for call in mock_result_repository.update_job_progress.call_args_list
        ]
        assert len(progress_calls) > 0

    @pytest.mark.asyncio
    async def test_run_job_long_phase_reports_in_phase_progress_not_early_90(
        self, job_runner, mock_result_repository, sample_telemetry_data
    ):
        """Long model phase should emit progressive updates and avoid jumping near 90% early."""
        job_runner._dataset_service.load_dataset = AsyncMock(return_value=sample_telemetry_data)

        class _SlowAnomalyEnsemble:
            def run(self, df, params):
                time.sleep(2.2)
                n = min(25, len(df))
                return {
                    "is_anomaly": [False] * n,
                    "anomaly_score": [0.1] * n,
                }

        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="anomaly_ensemble",
        )

        with patch(
            "src.services.job_runner.AnomalyEnsemble",
            return_value=_SlowAnomalyEnsemble(),
        ), patch(
            "src.services.job_runner.get_settings",
            return_value=MagicMock(
                app_env="test",
                ml_require_exact_dataset_range=False,
                ml_data_readiness_gate_enabled=False,
                ml_formatted_results_enabled=False,
            ),
        ):
            await job_runner.run_job("test-job-long-phase", request)

        model_phase_calls = [
            call for call in mock_result_repository.update_job_progress.call_args_list
            if call.kwargs.get("phase") == "model_execution"
        ]
        assert len(model_phase_calls) >= 2
        assert max(float(call.kwargs.get("progress", 0.0)) for call in model_phase_calls) <= 85.0

    @pytest.mark.asyncio
    async def test_run_job_falls_back_to_direct_data_when_readiness_unavailable(
        self, job_runner, mock_result_repository, sample_telemetry_data
    ):
        """If export/S3 readiness path times out, job should still run via direct exact-range load."""
        job_runner._dataset_service.load_dataset = AsyncMock(return_value=sample_telemetry_data)
        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=1),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="isolation_forest",
        )

        with patch(
            "src.services.job_runner.ensure_device_ready",
            AsyncMock(return_value=("D1", None, {"reason": "export_timeout", "export_attempted": True, "wait_seconds": 60.0})),
        ) as readiness_mock, patch(
            "src.services.job_runner.get_settings",
            return_value=MagicMock(
                app_env="development",
                ml_require_exact_dataset_range=True,
                ml_data_readiness_gate_enabled=True,
                ml_formatted_results_enabled=True,
            ),
        ):
            await job_runner.run_job("test-job-fallback-123", request)

        assert readiness_mock.await_args.kwargs["tenant_id"] is None
        final_call = mock_result_repository.update_job_status.call_args_list[-1]
        assert final_call.kwargs["status"] == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_job_passes_tenant_scope_to_exact_range_readiness(
        self, job_runner, mock_result_repository, sample_telemetry_data
    ):
        job_runner._dataset_service.load_dataset = AsyncMock(return_value=sample_telemetry_data)
        request = AnalyticsRequest(
            device_id="D1",
            start_time=datetime.now() - timedelta(days=1),
            end_time=datetime.now(),
            analysis_type=AnalyticsType.ANOMALY,
            model_name="isolation_forest",
            parameters={"tenant_id": "ORG-A"},
        )

        with patch(
            "src.services.job_runner.ensure_device_ready",
            AsyncMock(return_value=("D1", "datasets/D1/20260401_20260401.parquet", {"reason": "ready_exact"})),
        ) as readiness_mock, patch(
            "src.services.job_runner.get_settings",
            return_value=MagicMock(
                app_env="development",
                ml_require_exact_dataset_range=True,
                ml_data_readiness_gate_enabled=True,
                ml_formatted_results_enabled=True,
            ),
        ):
            await job_runner.run_job("test-job-tenant-readiness", request)

        assert readiness_mock.await_args.kwargs["tenant_id"] == "ORG-A"

    def test_model_phase_time_estimate_scales_with_dataset_size(self, job_runner):
        small = job_runner._estimate_model_phase_seconds(
            analysis_type=AnalyticsType.ANOMALY,
            current_rows=500,
        )
        large = job_runner._estimate_model_phase_seconds(
            analysis_type=AnalyticsType.ANOMALY,
            current_rows=50000,
        )
        assert large > small
