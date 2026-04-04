import pytest
from fastapi.testclient import TestClient
from app.main import app


class TestHealthEndpoint:
    """Unit tests for FastAPI health check endpoint."""

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
        """Verify health endpoint returns healthy status in response body."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.unit
    def test_health_check_response_structure(self, client):
        """Verify health endpoint response has correct structure."""
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data
