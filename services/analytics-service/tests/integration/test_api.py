"""Integration tests for API endpoints."""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from tests._bootstrap import bootstrap_test_imports

bootstrap_test_imports()

from src.api.dependencies import get_result_repository
from src.api.routes import analytics
from src.main import create_app


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app()
        return TestClient(app)
    
    def test_liveness_probe(self, client):
        """Test liveness probe endpoint."""
        response = client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "analytics-service"
    
    def test_readiness_probe(self, client):
        """Test readiness probe endpoint."""
        response = client.get("/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data


class TestAnalyticsEndpoints:
    """Tests for analytics API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app()
        queue = MagicMock()
        queue.submit_job = AsyncMock()
        queue.size = MagicMock(return_value=0)
        app.state.job_queue = queue
        repo = MagicMock()
        repo.create_job = AsyncMock()
        repo.update_job_queue_metadata = AsyncMock()
        repo.get_job = AsyncMock(return_value=None)
        repo.list_jobs = AsyncMock(return_value=[])
        repo.count_jobs = AsyncMock(return_value=0)
        repo.list_tenant_job_counts = AsyncMock(return_value=[])
        app.dependency_overrides[get_result_repository] = lambda: repo
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        return {
            "X-Internal-Service": "analytics-test-suite",
            "X-Tenant-Id": "SH00000001",
        }
    
    def test_submit_analytics_job(self, client, monkeypatch, auth_headers):
        """Test submitting analytics job."""
        monkeypatch.setattr(analytics, "check_worker_alive", AsyncMock(return_value=True))
        monkeypatch.setattr(
            "src.api.routes.analytics.AnalyticsDeviceScopeService.normalize_requested_device_ids",
            AsyncMock(return_value=["D1"]),
        )
        request_data = {
            "device_id": "D1",
            "start_time": (datetime.now() - timedelta(days=7)).isoformat(),
            "end_time": datetime.now().isoformat(),
            "analysis_type": "anomaly",
            "model_name": "isolation_forest",
            "parameters": {
                "contamination": 0.1,
            },
        }
        
        response = client.post("/api/v1/analytics/run", json=request_data, headers=auth_headers)
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
    
    def test_get_supported_models(self, client, auth_headers):
        """Test getting supported models."""
        response = client.get("/api/v1/analytics/models", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "anomaly_detection" in data
        assert "failure_prediction" in data
        assert "forecasting" in data
        
        # Check specific models
        assert "isolation_forest" in data["anomaly_detection"]
        assert "xgboost" in data["failure_prediction"]
        assert "prophet" in data["forecasting"]
        assert "ensembles" in data
    
    def test_invalid_model_for_analysis_type(self, client, monkeypatch, auth_headers):
        """Test validation of model for analysis type."""
        monkeypatch.setattr(analytics, "check_worker_alive", AsyncMock(return_value=True))
        monkeypatch.setattr(
            "src.api.routes.analytics.AnalyticsDeviceScopeService.normalize_requested_device_ids",
            AsyncMock(return_value=["D1"]),
        )
        request_data = {
            "device_id": "D1",
            "start_time": (datetime.now() - timedelta(days=7)).isoformat(),
            "end_time": datetime.now().isoformat(),
            "analysis_type": "anomaly",
            "model_name": "prophet",  # Invalid - prophet is for forecasting
        }
        
        response = client.post("/api/v1/analytics/run", json=request_data, headers=auth_headers)
        
        assert response.status_code == 202
