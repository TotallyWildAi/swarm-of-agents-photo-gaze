"""Tests for comprehensive error handling: invalid paths, processing failures, API errors."""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestInvalidPathErrors:
    """Invalid paths should return clear, user-friendly error messages."""

    def test_rescan_nonexistent_path_returns_400(self):
        """A path that doesn't exist at all should say so clearly."""
        resp = client.post("/rescan", params={"folder_path": "/nonexistent/path/abc123"})
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert "does not exist" in body["error"]

    def test_rescan_file_instead_of_directory_returns_400(self):
        """A path that exists but is a file (not a dir) should explain the problem."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        try:
            resp = client.post("/rescan", params={"folder_path": temp_path})
            assert resp.status_code == 400
            body = resp.json()
            assert "error" in body
            assert "not a directory" in body["error"]
        finally:
            os.unlink(temp_path)

    def test_rescan_valid_empty_folder(self):
        """A valid but empty folder should succeed with 'no changes' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            resp = client.post("/rescan", params={"folder_path": tmpdir})
            # Should succeed (200) with no changes, not error
            assert resp.status_code in (200, 202)


class TestApiErrorStructure:
    """All API errors should return a consistent JSON structure with 'error' key."""

    def test_404_returns_json_error(self):
        """Non-existent similarity group returns structured JSON error."""
        resp = client.get("/similarity-groups/nonexistent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body

    def test_invalid_sort_by_returns_400(self):
        """Invalid sort_by parameter returns structured error."""
        resp = client.get("/similarity-groups", params={"sort_by": "invalid_field"})
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body

    def test_health_check_always_works(self):
        """Health endpoint should always return 200 with status."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestProcessingFailureLogging:
    """Processing failures should be logged and reported, not silently swallowed."""

    @pytest.mark.asyncio
    async def test_process_photo_failure_is_logged(self):
        """When photo processing fails, the error is logged."""
        from app.job_queue import JobQueueManager
        manager = JobQueueManager.__new__(JobQueueManager)
        manager.active_jobs = {"test-job": {"processed_photos": 0}}
        manager.SessionLocal = MagicMock()
        manager.metadata_extractor = MagicMock()
        manager.embedding_generator = MagicMock()

        # Make the session query return a photo
        mock_session = MagicMock()
        mock_photo = MagicMock()
        mock_photo.file_path = "/fake/photo.jpg"
        mock_session.query.return_value.filter.return_value.first.return_value = mock_photo
        manager.SessionLocal.return_value = mock_session

        # Make metadata extraction fail
        manager.metadata_extractor.extract = AsyncMock(side_effect=Exception("Corrupt EXIF data"))

        with patch("app.job_queue.logger") as mock_logger:
            result = await manager.process_photo("test-job", 1)
            assert result is False
            mock_logger.error.assert_called()
            # Verify the error message mentions the photo and job
            call_args = mock_logger.error.call_args[0]
            assert "1" in str(call_args)  # photo_id
            assert "test-job" in str(call_args)  # job_id
