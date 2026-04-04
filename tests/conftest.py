"""Pytest configuration and shared fixtures."""
import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    """Provide a TestClient for FastAPI app testing."""
    return TestClient(app)

