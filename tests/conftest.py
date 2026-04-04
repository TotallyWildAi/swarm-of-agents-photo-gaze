"""Shared fixtures for integration and unit tests."""
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# Ensure DATABASE_URL points to a test-safe value during import
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")


@pytest.fixture
def temp_photo_dir():
    """Create a temporary directory with fake image files for folder scanning tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create minimal valid JPEG files (smallest valid JPEG)
        from PIL import Image
        for name in ["photo1.jpg", "photo2.jpg", "photo3.png"]:
            img = Image.new("RGB", (100, 100), color="red")
            fmt = "JPEG" if name.endswith(".jpg") else "PNG"
            img.save(os.path.join(tmpdir, name), fmt)
        # Create a subdirectory with one more photo
        subdir = os.path.join(tmpdir, "subdir")
        os.makedirs(subdir)
        img = Image.new("RGB", (200, 200), color="blue")
        img.save(os.path.join(subdir, "photo4.jpg"), "JPEG")
        # Create a non-image file that should be skipped
        with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
            f.write("not an image")
        yield tmpdir


@pytest.fixture
def single_jpeg(tmp_path):
    """Create a single valid JPEG file and return its path."""
    from PIL import Image
    p = tmp_path / "test.jpg"
    img = Image.new("RGB", (64, 64), color="green")
    img.save(str(p), "JPEG")
    return str(p)
