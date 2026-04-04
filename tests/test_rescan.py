"""Unit and integration tests for POST /rescan endpoint with change detection."""
import pytest
import os
import tempfile
import shutil
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.models import Base, Photo


class TestRescanEndpoint:
    """Test POST /rescan endpoint for folder re-scanning with change detection."""
    
    @pytest.fixture
    def client(self):
        """Provide a test client for the FastAPI app."""
        return TestClient(app)
    
    @pytest.fixture
    def temp_folder(self):
        """Create a temporary folder for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.mark.unit
    def test_rescan_no_changes_detected(self, client, temp_folder):
        """Verify rescan returns 200 with no changes when folder is empty."""
        response = client.post("/rescan", params={"folder_path": temp_folder})
        assert response.status_code == 200
        data = response.json()
        assert data["changes_found"] == 0
        assert "message" in data
    
    @pytest.mark.unit
    def test_rescan_invalid_folder_path(self, client):
        """Verify rescan returns 400 for non-existent folder."""
        response = client.post("/rescan", params={"folder_path": "/nonexistent/path"})
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
    
    @pytest.mark.integration
    def test_rescan_detects_new_photos(self, client, temp_folder):
        """Verify rescan detects new photos and returns job_id for processing."""
        # Create a test image
        img_path = os.path.join(temp_folder, 'test_new.jpg')
        img = Image.new('RGB', (100, 100), color='red')
        img.save(img_path, 'JPEG')
        
        # Trigger rescan
        response = client.post("/rescan", params={"folder_path": temp_folder})
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["changes_found"] >= 1
        assert data["photos_queued"] >= 1
    
    @pytest.mark.integration
    def test_rescan_returns_job_id_for_tracking(self, client, temp_folder):
        """Verify rescan returns valid job_id that can be used for progress tracking."""
        # Create test image
        img_path = os.path.join(temp_folder, 'test_track.jpg')
        img = Image.new('RGB', (100, 100), color='blue')
        img.save(img_path, 'JPEG')
        
        # Trigger rescan
        response = client.post("/rescan", params={"folder_path": temp_folder})
        assert response.status_code == 202
        data = response.json()
        job_id = data["job_id"]
        
        # Verify job_id is a valid UUID string
        assert len(job_id) == 36  # UUID4 format
        assert job_id.count('-') == 4
    
    @pytest.mark.integration
    def test_rescan_detects_modified_photos(self, client, temp_folder):
        """Verify rescan detects modified photos via hash comparison."""
        img_path = os.path.join(temp_folder, 'test_modify.jpg')
        
        # Create initial image
        img = Image.new('RGB', (100, 100), color='red')
        img.save(img_path, 'JPEG')
        
        # First scan
        response1 = client.post("/rescan", params={"folder_path": temp_folder})
        assert response1.status_code == 202
        
        # Modify image
        img = Image.new('RGB', (100, 100), color='green')
        img.save(img_path, 'JPEG')
        
        # Second scan should detect change
        response2 = client.post("/rescan", params={"folder_path": temp_folder})
        assert response2.status_code == 202
        data = response2.json()
        assert data["changes_found"] >= 1
