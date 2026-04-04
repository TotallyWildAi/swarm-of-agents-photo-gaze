"""Unit tests for FastAPI application startup and endpoints."""
import pytest
from fastapi.testclient import TestClient
from main import app


class TestAppStartup:
    """Test FastAPI application initialization."""

    def test_app_title(self):
        """Verify FastAPI app is initialized with correct title."""
        assert app.title == "App API"

    def test_app_has_routes(self):
        """Verify FastAPI app has registered routes."""
        routes = [route.path for route in app.routes]
        assert "/health" in routes


class TestHealthEndpoint:
    """Test /health endpoint functionality."""

    def test_health_check_returns_200(self, client):
        """Verify /health endpoint returns 200 status code."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_returns_healthy_status(self, client):
        """Verify /health endpoint returns healthy status in response body."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_check_response_structure(self, client):
        """Verify /health endpoint response has expected structure."""
        response = client.get("/health")
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data

