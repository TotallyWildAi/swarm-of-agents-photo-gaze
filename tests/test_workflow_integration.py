"""Comprehensive integration tests covering complete workflows:

1. Folder selection and validation
2. Photo processing pipeline (scan → metadata → embedding → storage)
3. Similarity search and group management
4. Result display with thumbnails and pagination
5. Data consistency across components
6. Performance requirements validation
"""
import os
import time
import tempfile
import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from fastapi.testclient import TestClient

from app.main import app, similarity_group_service, thumbnail_generator
from app.folder_scanner import FolderScanner
from app.metadata_extractor import extract_metadata, validate_image_format, ImageMetadata
from app.similarity_search import SimilarityGroupService
from app.thumbnail import ThumbnailService


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_similarity_groups():
    """Ensure similarity groups are clean before/after each test."""
    similarity_group_service.clear()
    yield
    similarity_group_service.clear()


# ---------------------------------------------------------------------------
# 1. FOLDER SELECTION WORKFLOW
# ---------------------------------------------------------------------------

class TestFolderSelectionWorkflow:
    """Integration tests for folder selection and validation."""

    def test_rescan_valid_directory(self, client, temp_photo_dir):
        """POST /rescan with a valid directory returns 202 and a job_id."""
        with patch('app.main.job_queue_manager') as mock_jqm:
            mock_jqm.create_job = AsyncMock(return_value='test-job-123')
            response = client.post('/rescan', json={'folder_path': temp_photo_dir})
        assert response.status_code == 202
        data = response.json()
        assert 'job_id' in data

    def test_rescan_nonexistent_directory(self, client):
        """POST /rescan with a nonexistent path returns an error."""
        response = client.post('/rescan', json={'folder_path': '/nonexistent/path/xyz'})
        assert response.status_code in (400, 422)

    def test_rescan_file_instead_of_directory(self, client, single_jpeg):
        """POST /rescan with a file path (not directory) returns an error."""
        response = client.post('/rescan', json={'folder_path': single_jpeg})
        assert response.status_code in (400, 422)

    def test_folder_scanner_finds_images(self, temp_photo_dir):
        """FolderScanner discovers all supported image files recursively."""
        scanner = FolderScanner(temp_photo_dir)
        files = scanner.scan()
        # Should find photo1.jpg, photo2.jpg, photo3.png, subdir/photo4.jpg
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        image_files = [f for f in files if Path(f).suffix.lower() in image_extensions]
        assert len(image_files) >= 4, f"Expected at least 4 images, found {len(image_files)}: {image_files}"

    def test_folder_scanner_skips_non_images(self, temp_photo_dir):
        """FolderScanner does not include non-image files like .txt."""
        scanner = FolderScanner(temp_photo_dir)
        files = scanner.scan()
        txt_files = [f for f in files if f.endswith('.txt')]
        assert len(txt_files) == 0, f"Non-image files found: {txt_files}"

    def test_folder_scanner_empty_directory(self):
        """FolderScanner returns empty list for directory with no images."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = FolderScanner(tmpdir)
            files = scanner.scan()
            assert files == [] or len(files) == 0

    def test_folder_scanner_handles_nested_directories(self, temp_photo_dir):
        """FolderScanner recurses into subdirectories."""
        scanner = FolderScanner(temp_photo_dir)
        files = scanner.scan()
        subdir_files = [f for f in files if 'subdir' in f]
        assert len(subdir_files) >= 1, "Should find images in subdirectories"


# ---------------------------------------------------------------------------
# 2. PHOTO PROCESSING PIPELINE
# ---------------------------------------------------------------------------

class TestPhotoProcessingWorkflow:
    """Integration tests for the photo processing pipeline:
    scan → metadata extraction → embedding generation → storage."""

    def test_metadata_extraction_from_jpeg(self, single_jpeg):
        """extract_metadata returns correct fields for a valid JPEG."""
        meta = extract_metadata(single_jpeg)
        assert meta.filename == 'test.jpg'
        assert meta.file_path == single_jpeg
        assert meta.width == 64
        assert meta.height == 64
        assert meta.format == 'JPEG'
        assert meta.file_size > 0
        assert len(meta.file_hash) == 64  # SHA256 hex digest

    def test_metadata_extraction_from_png(self, tmp_path):
        """extract_metadata works for PNG files."""
        from PIL import Image
        p = tmp_path / 'test.png'
        Image.new('RGB', (128, 256), color='blue').save(str(p), 'PNG')
        meta = extract_metadata(str(p))
        assert meta.format == 'PNG'
        assert meta.width == 128
        assert meta.height == 256

    def test_metadata_extraction_nonexistent_file(self):
        """extract_metadata raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            extract_metadata('/nonexistent/photo.jpg')

    def test_metadata_extraction_unsupported_format(self, tmp_path):
        """extract_metadata raises ValueError for unsupported formats."""
        # Create a BMP file (not in SUPPORTED_FORMATS)
        from PIL import Image
        p = tmp_path / 'test.bmp'
        Image.new('RGB', (10, 10)).save(str(p), 'BMP')
        with pytest.raises(ValueError, match='Unsupported image format'):
            extract_metadata(str(p))

    def test_validate_image_format_supported(self, single_jpeg):
        """validate_image_format returns True for supported formats."""
        assert validate_image_format(single_jpeg) is True

    def test_validate_image_format_unsupported(self, tmp_path):
        """validate_image_format returns False for unsupported formats."""
        p = tmp_path / 'test.bmp'
        from PIL import Image
        Image.new('RGB', (10, 10)).save(str(p), 'BMP')
        assert validate_image_format(str(p)) is False

    def test_validate_image_format_nonexistent(self):
        """validate_image_format returns False for missing files."""
        assert validate_image_format('/no/such/file.jpg') is False

    def test_file_hash_deterministic(self, single_jpeg):
        """Same file always produces the same hash."""
        meta1 = extract_metadata(single_jpeg)
        meta2 = extract_metadata(single_jpeg)
        assert meta1.file_hash == meta2.file_hash

    def test_file_hash_changes_with_content(self, tmp_path):
        """Different file contents produce different hashes."""
        from PIL import Image
        p1 = tmp_path / 'a.jpg'
        p2 = tmp_path / 'b.jpg'
        Image.new('RGB', (10, 10), color='red').save(str(p1), 'JPEG')
        Image.new('RGB', (10, 10), color='blue').save(str(p2), 'JPEG')
        m1 = extract_metadata(str(p1))
        m2 = extract_metadata(str(p2))
        assert m1.file_hash != m2.file_hash

    def test_scan_then_extract_metadata_pipeline(self, temp_photo_dir):
        """Full pipeline: scan folder → extract metadata for each file."""
        scanner = FolderScanner(temp_photo_dir)
        files = scanner.scan()
        assert len(files) >= 4

        metadata_list = []
        for f in files:
            meta = extract_metadata(f)
            metadata_list.append(meta)

        # All metadata should have valid hashes and dimensions
        for meta in metadata_list:
            assert len(meta.file_hash) == 64
            assert meta.width > 0
            assert meta.height > 0
            assert meta.file_size > 0
            assert meta.format in {'JPEG', 'PNG', 'WEBP'}

        # Hashes should be unique (different files)
        hashes = [m.file_hash for m in metadata_list]
        assert len(set(hashes)) == len(hashes), "All files should have unique hashes"


# ---------------------------------------------------------------------------
# 3. SIMILARITY SEARCH WORKFLOW
# ---------------------------------------------------------------------------

class TestSimilaritySearchWorkflow:
    """Integration tests for similarity search and group management."""

    def test_add_and_retrieve_similarity_group(self):
        """Groups added to SimilarityGroupService can be retrieved."""
        svc = SimilarityGroupService()
        group = {
            'group_id': 'test-g1',
            'similarity_score': 0.92,
            'quality_score': 0.85,
            'members': [
                {'photo_id': 1, 'file_path': '/a.jpg', 'file_hash': 'aaa', 'filename': 'a.jpg'},
                {'photo_id': 2, 'file_path': '/b.jpg', 'file_hash': 'bbb', 'filename': 'b.jpg'},
            ],
        }
        svc.add_group(group)
        retrieved = svc.get_group('test-g1')
        assert retrieved is not None
        assert retrieved['similarity_score'] == 0.92
        assert len(retrieved['members']) == 2

    def test_group_not_found_returns_none(self):
        """Querying a nonexistent group returns None."""
        svc = SimilarityGroupService()
        assert svc.get_group('nonexistent') is None

    def test_remove_group(self):
        """Removing a group makes it no longer retrievable."""
        svc = SimilarityGroupService()
        svc.add_group({'group_id': 'g1', 'similarity_score': 0.5, 'quality_score': 0.5, 'members': []})
        assert svc.remove_group('g1') is True
        assert svc.get_group('g1') is None
        assert svc.remove_group('g1') is False  # already removed

    def test_clear_removes_all_groups(self):
        """clear() empties the service."""
        svc = SimilarityGroupService()
        for i in range(5):
            svc.add_group({'group_id': f'g{i}', 'similarity_score': 0.5, 'quality_score': 0.5, 'members': []})
        assert len(svc.get_all_groups()) == 5
        svc.clear()
        assert len(svc.get_all_groups()) == 0

    def test_replace_group_with_same_id(self):
        """Adding a group with an existing ID replaces it."""
        svc = SimilarityGroupService()
        svc.add_group({'group_id': 'g1', 'similarity_score': 0.5, 'quality_score': 0.5, 'members': []})
        svc.add_group({'group_id': 'g1', 'similarity_score': 0.99, 'quality_score': 0.99, 'members': []})
        assert len(svc.get_all_groups()) == 1
        assert svc.get_group('g1')['similarity_score'] == 0.99

    def test_thread_safety_concurrent_adds(self):
        """SimilarityGroupService handles concurrent adds without data loss."""
        import threading
        svc = SimilarityGroupService()
        num_threads = 10
        groups_per_thread = 50

        def add_groups(thread_id):
            for i in range(groups_per_thread):
                svc.add_group({
                    'group_id': f't{thread_id}_g{i}',
                    'similarity_score': 0.5,
                    'quality_score': 0.5,
                    'members': [],
                })

        threads = [threading.Thread(target=add_groups, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_groups = svc.get_all_groups()
        assert len(all_groups) == num_threads * groups_per_thread

    def test_similarity_groups_api_end_to_end(self, client):
        """Full workflow: add groups → list via API → get detail via API."""
        # Add groups to the global service
        groups = [
            {
                'group_id': 'workflow-g1',
                'similarity_score': 0.95,
                'quality_score': 0.88,
                'members': [
                    {'photo_id': 10, 'file_path': '/photos/x.jpg', 'file_hash': 'xxx', 'filename': 'x.jpg'},
                    {'photo_id': 11, 'file_path': '/photos/y.jpg', 'file_hash': 'yyy', 'filename': 'y.jpg'},
                ],
            },
            {
                'group_id': 'workflow-g2',
                'similarity_score': 0.72,
                'quality_score': 0.65,
                'members': [
                    {'photo_id': 12, 'file_path': '/photos/z.jpg', 'file_hash': 'zzz', 'filename': 'z.jpg'},
                ],
            },
        ]
        for g in groups:
            similarity_group_service.add_group(g)

        # List all groups
        response = client.get('/similarity-groups')
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 2
        group_ids = {g['group_id'] for g in data['groups']}
        assert 'workflow-g1' in group_ids
        assert 'workflow-g2' in group_ids

        # Get detail for workflow-g1
        with patch.object(thumbnail_generator, 'get_thumbnail', return_value='/cache/thumb.jpg'):
            response = client.get('/similarity-groups/workflow-g1')
        assert response.status_code == 200
        detail = response.json()
        assert detail['group_id'] == 'workflow-g1'
        assert detail['similarity_score'] == 0.95
        assert len(detail['members']) == 2

    def test_filter_then_paginate_workflow(self, client):
        """Workflow: filter by similarity → paginate results."""
        # Add many groups with varying scores
        for i in range(20):
            similarity_group_service.add_group({
                'group_id': f'bulk-g{i}',
                'similarity_score': 0.5 + (i * 0.025),  # 0.50 to 0.975
                'quality_score': 0.6,
                'members': [],
            })

        # Filter: only groups with similarity >= 0.8
        response = client.get('/similarity-groups?min_similarity=0.8')
        assert response.status_code == 200
        data = response.json()
        high_sim_count = data['total']
        assert high_sim_count > 0
        for g in data['groups']:
            assert g['similarity_score'] >= 0.8

        # Paginate: get first page of 3
        response = client.get('/similarity-groups?min_similarity=0.8&limit=3&skip=0')
        assert response.status_code == 200
        page1 = response.json()
        assert len(page1['groups']) <= 3
        assert page1['total'] == high_sim_count

        # Get second page
        response = client.get('/similarity-groups?min_similarity=0.8&limit=3&skip=3')
        assert response.status_code == 200
        page2 = response.json()
        # Pages should not overlap
        page1_ids = {g['group_id'] for g in page1['groups']}
        page2_ids = {g['group_id'] for g in page2['groups']}
        assert page1_ids.isdisjoint(page2_ids)


# ---------------------------------------------------------------------------
# 4. RESULT DISPLAY WORKFLOW (thumbnails, detail views)
# ---------------------------------------------------------------------------

class TestResultDisplayWorkflow:
    """Integration tests for result display with thumbnails."""

    def test_thumbnail_generation_and_caching(self, single_jpeg):
        """ThumbnailService generates and caches thumbnails correctly."""
        with tempfile.TemporaryDirectory() as cache_dir:
            svc = ThumbnailService(cache_dir=cache_dir)
            file_hash = extract_metadata(single_jpeg).file_hash

            # First call generates the thumbnail
            assert not svc.is_cached(file_hash)
            thumb_path = svc.get_thumbnail(single_jpeg, file_hash)
            assert os.path.isfile(thumb_path)
            assert svc.is_cached(file_hash)

            # Second call returns cached version
            thumb_path2 = svc.get_thumbnail(single_jpeg, file_hash)
            assert thumb_path == thumb_path2

    def test_thumbnail_invalidation(self, single_jpeg):
        """Invalidating a thumbnail removes it from cache."""
        with tempfile.TemporaryDirectory() as cache_dir:
            svc = ThumbnailService(cache_dir=cache_dir)
            file_hash = extract_metadata(single_jpeg).file_hash
            svc.get_thumbnail(single_jpeg, file_hash)
            assert svc.is_cached(file_hash)
            assert svc.invalidate(file_hash) is True
            assert not svc.is_cached(file_hash)

    def test_thumbnail_clear_cache(self, single_jpeg):
        """clear_cache removes all cached thumbnails."""
        with tempfile.TemporaryDirectory() as cache_dir:
            svc = ThumbnailService(cache_dir=cache_dir)
            file_hash = extract_metadata(single_jpeg).file_hash
            svc.get_thumbnail(single_jpeg, file_hash)
            count = svc.clear_cache()
            assert count >= 1
            assert not svc.is_cached(file_hash)

    def test_group_detail_with_thumbnails_via_api(self, client):
        """GET /similarity-groups/{id} returns members with thumbnail paths."""
        similarity_group_service.add_group({
            'group_id': 'display-g1',
            'similarity_score': 0.9,
            'quality_score': 0.8,
            'members': [
                {'photo_id': 1, 'file_path': '/photos/a.jpg', 'file_hash': 'hash_a', 'filename': 'a.jpg'},
                {'photo_id': 2, 'file_path': '/photos/b.jpg', 'file_hash': 'hash_b', 'filename': 'b.jpg'},
            ],
        })

        with patch.object(thumbnail_generator, 'get_thumbnail', return_value='/cache/thumb.jpg'):
            response = client.get('/similarity-groups/display-g1')
        assert response.status_code == 200
        data = response.json()
        assert len(data['members']) == 2
        for member in data['members']:
            assert 'thumbnail' in member
            assert 'photo_id' in member
            assert 'file_path' in member
            assert 'filename' in member

    def test_group_detail_thumbnail_failure_graceful(self, client):
        """When thumbnail generation fails, members get thumbnail=None."""
        similarity_group_service.add_group({
            'group_id': 'fail-thumb-g1',
            'similarity_score': 0.8,
            'quality_score': 0.7,
            'members': [
                {'photo_id': 1, 'file_path': '/missing.jpg', 'file_hash': 'nope', 'filename': 'missing.jpg'},
            ],
        })

        with patch.object(thumbnail_generator, 'get_thumbnail', side_effect=Exception('file not found')):
            response = client.get('/similarity-groups/fail-thumb-g1')
        assert response.status_code == 200
        data = response.json()
        assert data['members'][0]['thumbnail'] is None

    def test_nonexistent_group_returns_404(self, client):
        """GET /similarity-groups/{id} for unknown group returns 404."""
        response = client.get('/similarity-groups/does-not-exist')
        assert response.status_code == 404

    def test_sorted_results_display(self, client):
        """Results sorted by similarity show highest scores first."""
        for i, score in enumerate([0.6, 0.9, 0.75, 0.85]):
            similarity_group_service.add_group({
                'group_id': f'sort-g{i}',
                'similarity_score': score,
                'quality_score': 0.5,
                'members': [],
            })

        response = client.get('/similarity-groups?sort_by=similarity')
        assert response.status_code == 200
        groups = response.json()['groups']
        scores = [g['similarity_score'] for g in groups]
        assert scores == sorted(scores, reverse=True), f"Expected descending order: {scores}"


# ---------------------------------------------------------------------------
# 5. DATA CONSISTENCY
# ---------------------------------------------------------------------------

class TestDataConsistency:
    """Tests verifying data consistency across components."""

    def test_metadata_hash_matches_thumbnail_key(self, single_jpeg):
        """The file_hash from metadata extraction is the same key used for thumbnails."""
        meta = extract_metadata(single_jpeg)
        with tempfile.TemporaryDirectory() as cache_dir:
            svc = ThumbnailService(cache_dir=cache_dir)
            thumb = svc.get_thumbnail(single_jpeg, meta.file_hash)
            assert svc.is_cached(meta.file_hash)

    def test_modified_file_gets_new_hash_and_thumbnail(self, tmp_path):
        """When a photo is modified, its hash changes, causing a cache miss."""
        from PIL import Image
        p = tmp_path / 'mutable.jpg'
        Image.new('RGB', (50, 50), color='red').save(str(p), 'JPEG')

        meta1 = extract_metadata(str(p))
        hash1 = meta1.file_hash

        # Modify the file
        Image.new('RGB', (50, 50), color='green').save(str(p), 'JPEG')

        meta2 = extract_metadata(str(p))
        hash2 = meta2.file_hash

        assert hash1 != hash2, "Modified file should have a different hash"

        with tempfile.TemporaryDirectory() as cache_dir:
            svc = ThumbnailService(cache_dir=cache_dir)
            svc.get_thumbnail(str(p), hash1)
            # Old hash is cached, new hash is not
            assert svc.is_cached(hash1)
            assert not svc.is_cached(hash2)

    def test_scan_metadata_consistency(self, temp_photo_dir):
        """All scanned files produce valid, consistent metadata."""
        scanner = FolderScanner(temp_photo_dir)
        files = scanner.scan()

        for f in files:
            meta = extract_metadata(f)
            # file_path in metadata matches the scanned path
            assert meta.file_path == f
            # filename matches the basename
            assert meta.filename == os.path.basename(f)
            # file exists and size matches
            assert os.path.getsize(f) == meta.file_size

    def test_similarity_group_data_integrity(self, client):
        """Group data returned by API matches what was stored."""
        original = {
            'group_id': 'integrity-g1',
            'similarity_score': 0.87,
            'quality_score': 0.73,
            'members': [
                {'photo_id': 42, 'file_path': '/photos/test.jpg', 'file_hash': 'abc123', 'filename': 'test.jpg'},
            ],
        }
        similarity_group_service.add_group(original)

        # Verify via list endpoint
        response = client.get('/similarity-groups')
        data = response.json()
        api_group = next(g for g in data['groups'] if g['group_id'] == 'integrity-g1')
        assert api_group['similarity_score'] == original['similarity_score']
        assert api_group['quality_score'] == original['quality_score']

        # Verify via detail endpoint
        with patch.object(thumbnail_generator, 'get_thumbnail', return_value='/thumb.jpg'):
            response = client.get('/similarity-groups/integrity-g1')
        detail = response.json()
        assert detail['members'][0]['photo_id'] == 42
        assert detail['members'][0]['file_path'] == '/photos/test.jpg'


# ---------------------------------------------------------------------------
# 6. PERFORMANCE REQUIREMENTS
# ---------------------------------------------------------------------------

class TestPerformanceRequirements:
    """Tests validating performance requirements for key operations."""

    def test_folder_scan_performance(self, tmp_path):
        """Scanning a directory with 100 files completes in under 2 seconds."""
        from PIL import Image
        for i in range(100):
            img = Image.new('RGB', (10, 10), color='red')
            img.save(str(tmp_path / f'img_{i:03d}.jpg'), 'JPEG')

        start = time.time()
        scanner = FolderScanner(str(tmp_path))
        files = scanner.scan()
        elapsed = time.time() - start

        assert len(files) == 100
        assert elapsed < 2.0, f"Folder scan took {elapsed:.2f}s, expected < 2.0s"

    def test_metadata_extraction_performance(self, tmp_path):
        """Extracting metadata from 50 files completes in under 5 seconds."""
        from PIL import Image
        paths = []
        for i in range(50):
            p = tmp_path / f'perf_{i:03d}.jpg'
            Image.new('RGB', (100, 100), color='blue').save(str(p), 'JPEG')
            paths.append(str(p))

        start = time.time()
        for p in paths:
            extract_metadata(p)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Metadata extraction took {elapsed:.2f}s, expected < 5.0s"

    def test_thumbnail_generation_performance(self, tmp_path):
        """Generating 20 thumbnails completes in under 5 seconds."""
        from PIL import Image
        cache_dir = str(tmp_path / 'cache')
        os.makedirs(cache_dir)
        svc = ThumbnailService(cache_dir=cache_dir)

        paths_and_hashes = []
        for i in range(20):
            p = tmp_path / f'thumb_{i:03d}.jpg'
            Image.new('RGB', (800, 600), color='green').save(str(p), 'JPEG')
            meta = extract_metadata(str(p))
            paths_and_hashes.append((str(p), meta.file_hash))

        start = time.time()
        for path, fhash in paths_and_hashes:
            svc.get_thumbnail(path, fhash)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Thumbnail generation took {elapsed:.2f}s, expected < 5.0s"

    def test_similarity_group_api_response_time(self, client):
        """API response for listing 100 groups completes in under 1 second."""
        for i in range(100):
            similarity_group_service.add_group({
                'group_id': f'perf-g{i}',
                'similarity_score': 0.5 + (i % 50) * 0.01,
                'quality_score': 0.6,
                'members': [{'photo_id': i, 'file_path': f'/p{i}.jpg', 'file_hash': f'h{i}', 'filename': f'p{i}.jpg'}],
            })

        start = time.time()
        response = client.get('/similarity-groups')
        elapsed = time.time() - start

        assert response.status_code == 200
        assert response.json()['total'] == 100
        assert elapsed < 1.0, f"API response took {elapsed:.2f}s, expected < 1.0s"

    def test_similarity_group_service_bulk_operations(self):
        """Adding and retrieving 1000 groups completes in under 2 seconds."""
        svc = SimilarityGroupService()

        start = time.time()
        for i in range(1000):
            svc.add_group({
                'group_id': f'bulk-{i}',
                'similarity_score': 0.5,
                'quality_score': 0.5,
                'members': [],
            })
        all_groups = svc.get_all_groups()
        elapsed = time.time() - start

        assert len(all_groups) == 1000
        assert elapsed < 2.0, f"Bulk operations took {elapsed:.2f}s, expected < 2.0s"


# ---------------------------------------------------------------------------
# 7. HEALTH CHECK INTEGRATION
# ---------------------------------------------------------------------------

class TestHealthCheckIntegration:
    """Verify health endpoint works as part of the full app."""

    def test_health_returns_200(self, client):
        """Health endpoint returns 200 with healthy status."""
        response = client.get('/health')
        assert response.status_code == 200
        assert response.json()['status'] == 'healthy'

    def test_health_response_is_json(self, client):
        """Health endpoint returns JSON content type."""
        response = client.get('/health')
        assert response.headers['content-type'] == 'application/json'
