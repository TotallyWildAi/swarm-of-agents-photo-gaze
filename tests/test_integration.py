import pytest
import httpx
import asyncio
from time import sleep


class TestDockerComposeIntegration:
    """Integration tests to verify Docker Compose services are running and healthy."""

    @pytest.fixture(scope="class", autouse=True)
    def wait_for_services(self):
        """Wait for services to be ready before running tests."""
        max_retries = 30
        retry_count = 0
        services_ready = False

        while retry_count < max_retries and not services_ready:
            try:
                # Check FastAPI health
                response = httpx.get("http://localhost:8000/health", timeout=2)
                if response.status_code == 200:
                    services_ready = True
            except (httpx.ConnectError, httpx.TimeoutException):
                retry_count += 1
                sleep(1)

        if not services_ready:
            pytest.skip("Services not ready after 30 seconds")

    def test_fastapi_service_health(self):
        """Verify FastAPI service is running and health endpoint responds."""
        response = httpx.get("http://localhost:8000/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_fastapi_port_accessible(self):
        """Verify FastAPI service port 8000 is accessible."""
        try:
            response = httpx.get("http://localhost:8000/health", timeout=5)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("FastAPI service not accessible on port 8000")

    def test_postgres_port_accessible(self):
        """Verify PostgreSQL service port 5432 is accessible."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
        assert result == 0, "PostgreSQL service not accessible on port 5432"

    def test_qdrant_port_accessible(self):
        """Verify Qdrant service port 6333 is accessible."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("localhost", 6333))
        sock.close()
        assert result == 0, "Qdrant service not accessible on port 6333"

    def test_qdrant_health_endpoint(self):
        """Verify Qdrant health endpoint responds."""
        try:
            response = httpx.get("http://localhost:6333/health", timeout=5)
            assert response.status_code == 200
        except httpx.ConnectError:
            pytest.fail("Qdrant health endpoint not accessible")
