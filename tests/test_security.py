"""Security tests for input validation and path traversal protection."""
import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from app.main import app
from app.validators import (
    validate_folder_path,
    validate_photo_id,
    validate_thumbnail_size,
    validate_pagination,
    validate_similarity_filters,
    validate_sort_by,
    validate_job_id,
)
from app.security import is_safe_path, sanitize_path


class TestPathTraversalProtection:
    """Tests for directory traversal attack prevention."""
    
    def test_path_traversal_with_dotdot(self):
        """Reject paths with .. components."""
        assert not is_safe_path("./photos/../../../etc/passwd")
    
    def test_path_traversal_absolute(self):
        """Reject absolute paths outside allowed directories."""
        assert not is_safe_path("/etc/passwd")
    
    def test_safe_path_within_photos(self):
        """Accept paths within allowed photos directory."""
        # Create a temporary directory to test with
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["PHOTOS_FOLDER"] = tmpdir
            test_file = os.path.join(tmpdir, "test.jpg")
            assert is_safe_path(test_file)
    
    def test_empty_path_rejected(self):
        """Reject empty paths."""
        assert not is_safe_path("")
        assert not is_safe_path(None)


class TestFolderPathValidation:
    """Tests for folder path validation."""
    
    def test_nonexistent_path(self):
        """Reject paths that don't exist."""
        error = validate_folder_path("/nonexistent/path/12345")
        assert error is not None
        assert "does not exist" in error
    
    def test_file_path_not_directory(self):
        """Reject file paths (not directories)."""
        with tempfile.NamedTemporaryFile() as tmp:
            error = validate_folder_path(tmp.name)
            assert error is not None
            assert "not a directory" in error
    
    def test_valid_directory(self):
        """Accept valid directory paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            error = validate_folder_path(tmpdir)
            assert error is None
    
    def test_empty_string_rejected(self):
        """Reject empty folder path."""
        error = validate_folder_path("")
        assert error is not None


class TestPhotoIdValidation:
    """Tests for photo ID validation."""
    
    def test_valid_photo_id(self):
        """Accept valid positive integer photo IDs."""
        assert validate_photo_id(1) is None
        assert validate_photo_id(999999) is None
    
    def test_zero_photo_id(self):
        """Reject zero photo ID."""
        error = validate_photo_id(0)
        assert error is not None
        assert "positive" in error
    
    def test_negative_photo_id(self):
        """Reject negative photo ID."""
        error = validate_photo_id(-1)
        assert error is not None
        assert "positive" in error
    
    def test_non_integer_photo_id(self):
        """Reject non-integer photo ID."""
        error = validate_photo_id("123")
        assert error is not None
        assert "integer" in error
    
    def test_overflow_photo_id(self):
        """Reject photo ID exceeding max value."""
        error = validate_photo_id(2147483648)
        assert error is not None
        assert "exceeds" in error


class TestThumbnailSizeValidation:
    """Tests for thumbnail size validation."""
    
    def test_valid_thumbnail_size(self):
        """Accept valid thumbnail sizes."""
        assert validate_thumbnail_size(200) is None
        assert validate_thumbnail_size(512) is None
    
    def test_too_small_size(self):
        """Reject thumbnail size below minimum."""
        error = validate_thumbnail_size(16)
        assert error is not None
        assert "at least 32" in error
    
    def test_too_large_size(self):
        """Reject thumbnail size above maximum."""
        error = validate_thumbnail_size(4096)
        assert error is not None
        assert "2048" in error
    
    def test_non_integer_size(self):
        """Reject non-integer size."""
        error = validate_thumbnail_size("200")
        assert error is not None
        assert "integer" in error


class TestPaginationValidation:
    """Tests for pagination parameter validation."""
    
    def test_valid_pagination(self):
        """Accept valid pagination parameters."""
        assert validate_pagination(0, 50) is None
        assert validate_pagination(100, 25) is None
    
    def test_negative_skip(self):
        """Reject negative skip value."""
        error = validate_pagination(-1, 50)
        assert error is not None
        assert "non-negative" in error
    
    def test_zero_limit(self):
        """Reject zero limit."""
        error = validate_pagination(0, 0)
        assert error is not None
        assert "at least 1" in error
    
    def test_excessive_limit(self):
        """Reject limit exceeding maximum."""
        error = validate_pagination(0, 2000)
        assert error is not None
        assert "1000" in error
    
    def test_excessive_skip(self):
        """Reject skip exceeding maximum."""
        error = validate_pagination(2000000, 50)
        assert error is not None
        assert "1000000" in error


class TestSimilarityFiltersValidation:
    """Tests for similarity and quality filter validation."""
    
    def test_valid_filters(self):
        """Accept valid filter values."""
        assert validate_similarity_filters(0.5, 0.7) is None
        assert validate_similarity_filters(0.0, 1.0) is None
    
    def test_negative_similarity(self):
        """Reject negative similarity score."""
        error = validate_similarity_filters(-0.1, 0.5)
        assert error is not None
        assert "0.0 and 1.0" in error
    
    def test_similarity_exceeds_one(self):
        """Reject similarity score > 1.0."""
        error = validate_similarity_filters(1.5, 0.5)
        assert error is not None
        assert "0.0 and 1.0" in error
    
    def test_negative_quality(self):
        """Reject negative quality score."""
        error = validate_similarity_filters(0.5, -0.1)
        assert error is not None
        assert "0.0 and 1.0" in error


class TestSortByValidation:
    """Tests for sort_by parameter validation."""
    
    def test_valid_sort_by_similarity(self):
        """Accept 'similarity' sort option."""
        assert validate_sort_by("similarity") is None
    
    def test_valid_sort_by_quality(self):
        """Accept 'quality' sort option."""
        assert validate_sort_by("quality") is None
    
    def test_invalid_sort_by(self):
        """Reject invalid sort option."""
        error = validate_sort_by("invalid")
        assert error is not None
        assert "Invalid sort_by" in error
    
    def test_non_string_sort_by(self):
        """Reject non-string sort_by."""
        error = validate_sort_by(123)
        assert error is not None
        assert "string" in error


class TestJobIdValidation:
    """Tests for job ID validation."""
    
    def test_valid_uuid_job_id(self):
        """Accept valid UUID format job IDs."""
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_job_id(valid_uuid) is None
    
    def test_invalid_uuid_format(self):
        """Reject invalid UUID format."""
        error = validate_job_id("not-a-uuid")
        assert error is not None
        assert "Invalid job ID format" in error
    
    def test_empty_job_id(self):
        """Reject empty job ID."""
        error = validate_job_id("")
        assert error is not None
        assert "not be empty" in error
    
    def test_non_string_job_id(self):
        """Reject non-string job ID."""
        error = validate_job_id(123)
        assert error is not None
        assert "string" in error


class TestEndpointInputValidation:
    """Integration tests for endpoint input validation."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_rescan_with_invalid_path(self, client):
        """POST /rescan rejects invalid paths."""
        response = client.post("/rescan", json={"folder_path": "/nonexistent/path"})
        assert response.status_code == 400
    
    def test_thumbnail_with_invalid_photo_id(self, client):
        """GET /thumbnails/{photo_id} rejects invalid photo IDs."""
        response = client.get("/thumbnails/0")
        assert response.status_code == 400
    
    def test_thumbnail_with_invalid_size(self, client):
        """GET /thumbnails/{photo_id} rejects invalid size."""
        response = client.get("/thumbnails/1?size=10000")
        assert response.status_code == 400
    
    def test_similarity_groups_with_invalid_pagination(self, client):
        """GET /similarity-groups rejects invalid pagination."""
        response = client.get("/similarity-groups?skip=-1")
        assert response.status_code == 400
    
    def test_similarity_groups_with_invalid_filters(self, client):
        """GET /similarity-groups rejects invalid filter values."""
        response = client.get("/similarity-groups?min_similarity=1.5")
        assert response.status_code == 400
    
    def test_similarity_groups_with_invalid_sort(self, client):
        """GET /similarity-groups rejects invalid sort_by."""
        response = client.get("/similarity-groups?sort_by=invalid")
        assert response.status_code == 400
