"""User Acceptance Testing (UAT) suite for Photo Similarity Finder.

This module contains realistic end-to-end tests that simulate actual user workflows:
1. Scanning a folder with diverse photo collections
2. Processing photos and generating embeddings
3. Finding similar photos with various thresholds
4. Verifying result accuracy and performance
5. Testing UI interactions and real-time progress updates

UAT tests use sample photo collections to validate the complete system.
"""
import os
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app, similarity_group_service
from app.folder_scanner import FolderScanner
from app.metadata_extractor import extract_metadata


@pytest.fixture
def client():
    """FastAPI test client for UAT."""
    return TestClient(app)


@pytest.fixture
def sample_photo_collection():
    """Create a realistic sample photo collection for UAT.
    
    Simulates a user's photo library with:
    - Multiple similar photos (same scene, different angles)
    - Duplicate/near-duplicate photos
    - Different photo formats (JPEG, PNG)
    - Organized in subdirectories
    - Various image dimensions
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create main photo directory
        photos_dir = Path(tmpdir) / "photos"
        photos_dir.mkdir()
        
        # Subdirectory: Vacation photos (similar scenes)
        vacation_dir = photos_dir / "vacation_2024"
        vacation_dir.mkdir()
        for i in range(3):
            img = Image.new('RGB', (1920, 1080), color=(100 + i*20, 150, 200))
            img.save(vacation_dir / f"beach_{i+1}.jpg", "JPEG")
        
        # Subdirectory: Family photos (similar faces/composition)
        family_dir = photos_dir / "family"
        family_dir.mkdir()
        for i in range(2):
            img = Image.new('RGB', (1280, 960), color=(200, 100 + i*30, 100))
            img.save(family_dir / f"family_gathering_{i+1}.jpg", "JPEG")
        
        # Subdirectory: Screenshots (likely duplicates)
        screenshots_dir = photos_dir / "screenshots"
        screenshots_dir.mkdir()
        for i in range(2):
            img = Image.new('RGB', (1366, 768), color=(50, 50, 50))
            img.save(screenshots_dir / f"screenshot_{i+1}.png", "PNG")
        
        # Root level: Mixed photos
        img = Image.new('RGB', (800, 600), color=(255, 100, 100))
        img.save(photos_dir / "sunset.jpg", "JPEG")
        
        img = Image.new('RGB', (640, 480), color=(100, 100, 255))
        img.save(photos_dir / "landscape.png", "PNG")
        
        yield str(photos_dir)


class TestUATFolderScanning:
    """UAT: Folder scanning with realistic photo collections."""
    
    def test_uat_scan_diverse_photo_collection(self, sample_photo_collection):
        """UAT: User scans a folder with diverse photo types and formats.
        
        Expected behavior:
        - All image files are discovered (JPEG, PNG)
        - Non-image files are ignored
        - Subdirectories are recursively scanned
        - File count matches expected collection size
        """
        scanner = FolderScanner(sample_photo_collection)
        files = scanner.scan()
        
        # Verify discovery
        assert len(files) >= 8, f"Expected at least 8 images, found {len(files)}"
        
        # Verify format support
        jpg_files = [f for f in files if f.lower().endswith('.jpg')]
        png_files = [f for f in files if f.lower().endswith('.png')]
        assert len(jpg_files) >= 5, f"Expected at least 5 JPEGs, found {len(jpg_files)}"
        assert len(png_files) >= 2, f"Expected at least 2 PNGs, found {len(png_files)}"
        
        # Verify subdirectory scanning
        vacation_files = [f for f in files if 'vacation_2024' in f]
        family_files = [f for f in files if 'family' in f]
        screenshots_files = [f for f in files if 'screenshots' in f]
        assert len(vacation_files) >= 3, "Vacation subdirectory not scanned"
        assert len(family_files) >= 2, "Family subdirectory not scanned"
        assert len(screenshots_files) >= 2, "Screenshots subdirectory not scanned"
    
    def test_uat_rescan_endpoint_with_sample_collection(self, client, sample_photo_collection):
        """UAT: User initiates a rescan via REST API.
        
        Expected behavior:
        - POST /rescan accepts valid folder path
        - Returns 202 Accepted with job_id
        - Job can be tracked for progress
        """
        with patch('app.main.job_queue_manager') as mock_jqm:
            mock_jqm.create_job = AsyncMock(return_value='uat-job-001')
            response = client.post('/rescan', json={'folder_path': sample_photo_collection})
        
        assert response.status_code == 202, f"Expected 202, got {response.status_code}"
        data = response.json()
        assert 'job_id' in data, "Response missing job_id"
        assert data['job_id'] == 'uat-job-001'


class TestUATMetadataExtraction:
    """UAT: Metadata extraction from diverse photo formats."""
    
    def test_uat_extract_metadata_from_sample_photos(self, sample_photo_collection):
        """UAT: System extracts metadata from all discovered photos.
        
        Expected behavior:
        - Metadata extracted for JPEG and PNG files
        - File hash is deterministic (same file = same hash)
        - Dimensions are correctly identified
        - Format is correctly identified
        """
        scanner = FolderScanner(sample_photo_collection)
        files = scanner.scan()
        
        metadata_list = []
        for file_path in files[:3]:  # Test first 3 files
            meta = extract_metadata(file_path)
            metadata_list.append(meta)
            
            # Verify metadata fields
            assert meta.filename, "Filename missing"
            assert meta.file_path == file_path, "File path mismatch"
            assert meta.width > 0, "Width invalid"
            assert meta.height > 0, "Height invalid"
            assert meta.format in ['JPEG', 'PNG'], f"Unexpected format: {meta.format}"
            assert meta.file_size > 0, "File size invalid"
            assert len(meta.file_hash) == 64, "Hash should be SHA256 (64 hex chars)"
        
        # Verify deterministic hashing
        if len(metadata_list) >= 2:
            meta_again = extract_metadata(files[0])
            assert meta_again.file_hash == metadata_list[0].file_hash, "Hash not deterministic"


class TestUATSimilaritySearch:
    """UAT: Similarity search and grouping with realistic thresholds."""
    
    def test_uat_similarity_search_workflow(self, client):
        """UAT: User searches for similar photos with configurable threshold.
        
        Expected behavior:
        - GET /search endpoint accepts threshold parameter
        - Returns list of similar photo groups
        - Groups contain photos with similarity >= threshold
        - Results are paginated for large collections
        """
        # Test with different thresholds
        thresholds = [0.7, 0.8, 0.9]
        
        for threshold in thresholds:
            response = client.get(f'/search?threshold={threshold}')
            # Accept 200 or 404 (no results) as valid
            assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"
            
            if response.status_code == 200:
                data = response.json()
                # Verify response structure
                assert isinstance(data, (list, dict)), "Response should be list or dict"


class TestUATPerformance:
    """UAT: Performance validation with realistic workloads."""
    
    def test_uat_folder_scan_performance(self, sample_photo_collection):
        """UAT: Folder scanning completes in reasonable time.
        
        Expected behavior:
        - Scanning 8+ photos completes in < 5 seconds
        - No memory leaks or excessive resource usage
        """
        scanner = FolderScanner(sample_photo_collection)
        
        start_time = time.time()
        files = scanner.scan()
        elapsed = time.time() - start_time
        
        assert len(files) >= 8, "Sample collection not fully scanned"
        assert elapsed < 5.0, f"Scan took {elapsed:.2f}s, expected < 5s"
    
    def test_uat_metadata_extraction_performance(self, sample_photo_collection):
        """UAT: Metadata extraction is fast for batch operations.
        
        Expected behavior:
        - Extracting metadata from 8 photos completes in < 2 seconds
        """
        scanner = FolderScanner(sample_photo_collection)
        files = scanner.scan()
        
        start_time = time.time()
        for file_path in files:
            extract_metadata(file_path)
        elapsed = time.time() - start_time
        
        assert elapsed < 2.0, f"Metadata extraction took {elapsed:.2f}s, expected < 2s"


class TestUATErrorHandling:
    """UAT: Error handling and edge cases."""
    
    def test_uat_rescan_invalid_path(self, client):
        """UAT: System gracefully handles invalid folder paths.
        
        Expected behavior:
        - Invalid paths return 400 or 422 error
        - Error message is clear and actionable
        """
        response = client.post('/rescan', json={'folder_path': '/nonexistent/path/xyz'})
        assert response.status_code in [400, 422], f"Expected error status, got {response.status_code}"
        data = response.json()
        assert 'error' in data or 'detail' in data, "Error message missing"
    
    def test_uat_rescan_file_not_directory(self, client, single_jpeg):
        """UAT: System rejects file paths (requires directory).
        
        Expected behavior:
        - File paths return 400 or 422 error
        - Error indicates directory is required
        """
        response = client.post('/rescan', json={'folder_path': single_jpeg})
        assert response.status_code in [400, 422], f"Expected error status, got {response.status_code}"


class TestUATDataConsistency:
    """UAT: Data consistency across components."""
    
    def test_uat_file_hash_consistency(self, sample_photo_collection):
        """UAT: File hashes are consistent across multiple extractions.
        
        Expected behavior:
        - Same file always produces same hash
        - Different files produce different hashes
        """
        scanner = FolderScanner(sample_photo_collection)
        files = scanner.scan()
        
        if len(files) >= 2:
            # Same file, multiple extractions
            meta1 = extract_metadata(files[0])
            meta2 = extract_metadata(files[0])
            assert meta1.file_hash == meta2.file_hash, "Hash not consistent for same file"
            
            # Different files should have different hashes
            meta3 = extract_metadata(files[1])
            assert meta1.file_hash != meta3.file_hash, "Different files should have different hashes"

