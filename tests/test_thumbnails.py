"""Tests for thumbnail generation service: speed, caching, and cache invalidation."""
import os
import time
import shutil
import hashlib
import tempfile

import pytest
from PIL import Image

from app.thumbnail import ThumbnailService


def _make_image(path: str, width: int = 800, height: int = 600, color: str = "red") -> str:
    """Helper: create a JPEG test image and return its SHA-256 hash."""
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, "JPEG")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestThumbnailGeneration:
    """Core thumbnail generation tests."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.cache_dir = str(tmp_path / "cache")
        self.service = ThumbnailService(cache_dir=self.cache_dir)
        self.img_dir = str(tmp_path / "images")
        os.makedirs(self.img_dir, exist_ok=True)

    def test_generates_thumbnail_file(self):
        """Thumbnail file is created on disk."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path)

        thumb_path = self.service.get_thumbnail(img_path, file_hash)
        assert os.path.isfile(thumb_path)

    def test_thumbnail_dimensions(self):
        """Generated thumbnail respects requested max dimensions."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path, 1600, 1200)

        thumb_path = self.service.get_thumbnail(img_path, file_hash, size=(200, 200))
        with Image.open(thumb_path) as thumb:
            assert thumb.size[0] <= 200
            assert thumb.size[1] <= 200

    def test_thumbnail_is_jpeg(self):
        """Output thumbnail is always JPEG regardless of source format."""
        img_path = os.path.join(self.img_dir, "photo.png")
        img = Image.new("RGBA", (400, 400), color=(255, 0, 0, 128))
        img.save(img_path, "PNG")
        with open(img_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        thumb_path = self.service.get_thumbnail(img_path, file_hash)
        with Image.open(thumb_path) as thumb:
            assert thumb.format == "JPEG"

    def test_generation_speed_under_50ms(self):
        """First-time thumbnail generation completes in under 50ms for a typical photo."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path, 1920, 1080)

        start = time.perf_counter()
        self.service.get_thumbnail(img_path, file_hash, size=(200, 200))
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Thumbnail generation took {elapsed_ms:.1f}ms, expected <50ms"


class TestThumbnailCaching:
    """Verify that thumbnails are cached and served from cache."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.cache_dir = str(tmp_path / "cache")
        self.service = ThumbnailService(cache_dir=self.cache_dir)
        self.img_dir = str(tmp_path / "images")
        os.makedirs(self.img_dir, exist_ok=True)

    def test_second_call_returns_cached(self):
        """Second call returns the same cached path without regenerating."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path)

        path1 = self.service.get_thumbnail(img_path, file_hash)
        path2 = self.service.get_thumbnail(img_path, file_hash)
        assert path1 == path2

    def test_cached_retrieval_is_fast(self):
        """Cached thumbnail retrieval is near-instant (well under 5ms)."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path, 1920, 1080)

        # Prime the cache
        self.service.get_thumbnail(img_path, file_hash)

        start = time.perf_counter()
        self.service.get_thumbnail(img_path, file_hash)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 5, f"Cached retrieval took {elapsed_ms:.1f}ms, expected <5ms"

    def test_is_cached_returns_true_after_generation(self):
        """is_cached() returns True after thumbnail has been generated."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path)

        assert not self.service.is_cached(file_hash)
        self.service.get_thumbnail(img_path, file_hash)
        assert self.service.is_cached(file_hash)

    def test_different_sizes_cached_separately(self):
        """Different thumbnail sizes produce separate cache entries."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path)

        path_small = self.service.get_thumbnail(img_path, file_hash, size=(100, 100))
        path_large = self.service.get_thumbnail(img_path, file_hash, size=(300, 300))
        assert path_small != path_large
        assert os.path.isfile(path_small)
        assert os.path.isfile(path_large)


class TestCacheInvalidation:
    """Verify cache invalidation when photos are modified (hash changes)."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.cache_dir = str(tmp_path / "cache")
        self.service = ThumbnailService(cache_dir=self.cache_dir)
        self.img_dir = str(tmp_path / "images")
        os.makedirs(self.img_dir, exist_ok=True)

    def test_modified_photo_gets_new_thumbnail(self):
        """When file_hash changes (photo modified), a new thumbnail is generated."""
        img_path = os.path.join(self.img_dir, "photo.jpg")

        # Original image
        hash1 = _make_image(img_path, color="red")
        thumb1 = self.service.get_thumbnail(img_path, hash1)
        assert self.service.is_cached(hash1)

        # Modified image — different content, different hash
        hash2 = _make_image(img_path, color="blue")
        assert hash1 != hash2, "Hashes should differ for different images"

        thumb2 = self.service.get_thumbnail(img_path, hash2)
        # New hash means new cache path
        assert thumb1 != thumb2
        assert os.path.isfile(thumb2)

    def test_old_hash_cache_still_exists_after_update(self):
        """Old cached thumbnail remains on disk (lazy cleanup) until explicitly invalidated."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        hash1 = _make_image(img_path, color="red")
        self.service.get_thumbnail(img_path, hash1)

        hash2 = _make_image(img_path, color="green")
        self.service.get_thumbnail(img_path, hash2)

        # Old cache entry still on disk
        assert self.service.is_cached(hash1)
        # But new one also exists
        assert self.service.is_cached(hash2)

    def test_explicit_invalidate_removes_cache(self):
        """invalidate() removes a specific cached thumbnail."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        file_hash = _make_image(img_path)
        self.service.get_thumbnail(img_path, file_hash)

        assert self.service.is_cached(file_hash)
        result = self.service.invalidate(file_hash)
        assert result is True
        assert not self.service.is_cached(file_hash)

    def test_invalidate_nonexistent_returns_false(self):
        """invalidate() returns False when no cache entry exists."""
        result = self.service.invalidate("nonexistent_hash")
        assert result is False

    def test_clear_cache_removes_all(self):
        """clear_cache() removes all cached thumbnails."""
        img_path = os.path.join(self.img_dir, "photo.jpg")
        hash1 = _make_image(img_path, color="red")
        self.service.get_thumbnail(img_path, hash1)

        hash2 = _make_image(img_path, color="blue")
        self.service.get_thumbnail(img_path, hash2)

        count = self.service.clear_cache()
        assert count == 2
        assert not self.service.is_cached(hash1)
        assert not self.service.is_cached(hash2)
