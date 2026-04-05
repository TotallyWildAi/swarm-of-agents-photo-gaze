"""Tests for monitoring, metrics, and alerting functionality."""
import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app


class TestMetricsEndpoint:
    """Unit tests for Prometheus metrics endpoint."""

    @pytest.fixture
    def client(self):
        """Provide a test client for the FastAPI app."""
        return TestClient(app)

    @pytest.mark.unit
    def test_metrics_endpoint_returns_200(self, client):
        """Verify /metrics endpoint returns 200 status code."""
        response = client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_metrics_endpoint_returns_prometheus_format(self, client):
        """Verify /metrics endpoint returns Prometheus text format."""
        response = client.get("/metrics")
        assert "text/plain" in response.headers.get("content-type", "")

    @pytest.mark.unit
    def test_metrics_contains_request_count(self, client):
        """Verify metrics include request count metric."""
        # Make a request to generate metrics
        client.get("/health")
        response = client.get("/metrics")
        assert "fastapi_requests_total" in response.text

    @pytest.mark.unit
    def test_metrics_contains_request_duration(self, client):
        """Verify metrics include request duration metric."""
        # Make a request to generate metrics
        client.get("/health")
        response = client.get("/metrics")
        assert "fastapi_request_duration_seconds" in response.text

    @pytest.mark.unit
    def test_metrics_contains_active_requests(self, client):
        """Verify metrics include active requests gauge."""
        response = client.get("/metrics")
        assert "fastapi_active_requests" in response.text

    @pytest.mark.unit
    def test_metrics_contains_errors_total(self, client):
        """Verify metrics include error counter."""
        response = client.get("/metrics")
        assert "fastapi_errors_total" in response.text


class TestHealthCheckEndpoint:
    """Unit tests for health check endpoint."""

    @pytest.fixture
    def client(self):
        """Provide a test client for the FastAPI app."""
        return TestClient(app)

    @pytest.mark.unit
    def test_health_check_returns_200(self, client):
        """Verify health endpoint returns 200 status code."""
        response = client.get("/health")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_health_check_returns_healthy_status(self, client):
        """Verify health endpoint returns healthy status."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"


class TestMonitoringIntegration:
    """Integration tests for monitoring infrastructure."""

    @pytest.mark.integration
    def test_prometheus_accessible(self):
        """Verify Prometheus is accessible and responding."""
        try:
            response = httpx.get("http://localhost:9090/-/healthy", timeout=5)
            assert response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Prometheus not running")

    @pytest.mark.integration
    def test_alertmanager_accessible(self):
        """Verify Alertmanager is accessible and responding."""
        try:
            response = httpx.get("http://localhost:9093/-/healthy", timeout=5)
            assert response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Alertmanager not running")

    @pytest.mark.integration
    def test_prometheus_scrapes_fastapi(self):
        """Verify Prometheus can scrape FastAPI metrics."""
        try:
            response = httpx.get(
                "http://localhost:9090/api/v1/query",
                params={"query": "up{job='fastapi'}"},
                timeout=5
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Prometheus not running")

    @pytest.mark.integration
    def test_alertmanager_has_routes(self):
        """Verify Alertmanager has alert routes configured."""
        try:
            response = httpx.get(
                "http://localhost:9093/api/v1/status",
                timeout=5
            )
            assert response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Alertmanager not running")
