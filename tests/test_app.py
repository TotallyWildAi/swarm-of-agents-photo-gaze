"""Unit tests for FastAPI application initialization and endpoints."""
import pytest
from fastapi import FastAPI
from main import app


class TestAppInitialization:
    """Test FastAPI app is properly initialized."""

    def test_app_is_fastapi_instance(self):
        """Verify app is a FastAPI instance."""
        assert isinstance(app, FastAPI)

    def test_app_title(self):
        """Verify app has correct title."""
        assert app.title == "App API"


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check_status_code(self, client):
        """Verify health endpoint returns 200 status code."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_response_body(self, client):
        """Verify health endpoint returns correct response body."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_check_response_type(self, client):
        """Verify health endpoint returns JSON response."""
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"

