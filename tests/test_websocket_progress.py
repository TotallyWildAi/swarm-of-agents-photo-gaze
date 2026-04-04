"""Unit tests for WebSocket progress endpoint with real-time updates."""
import pytest
import asyncio
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.models import Base, JobQueue
from app.job_queue import JobQueueManager


class TestWebSocketProgress:
    """Unit tests for WebSocket progress endpoint."""
    
    @pytest.fixture
    def client(self):
        """Provide a test client for the FastAPI app."""
        return TestClient(app)
    
    @pytest.fixture
    def db_url(self):
        """Provide in-memory SQLite database URL for testing."""
        return "sqlite:///:memory:"
    
    @pytest.fixture
    def job_queue(self, db_url):
        """Create JobQueueManager with test database."""
        manager = JobQueueManager(database_url=db_url)
        Base.metadata.create_all(manager.engine)
        return manager
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_progress_returns_percentage(self, job_queue):
        """Verify progress calculation returns correct percentage."""
        job_id = "test_job_progress_001"
        job_queue.create_job(job_id, 100)
        
        # Process 25 photos
        for i in range(25):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        progress = await job_queue.get_progress(job_id)
        assert progress["percentage"] == 25
        assert progress["processed_photos"] == 25
        assert progress["total_photos"] == 100
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_progress_returns_eta(self, job_queue):
        """Verify progress calculation returns ETA in seconds."""
        job_id = "test_job_progress_002"
        job_queue.create_job(job_id, 100)
        
        # Set started_at to simulate processing
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        job.started_at = datetime.utcnow() - timedelta(seconds=10)
        session.commit()
        session.close()
        
        # Process 50 photos (should take ~10 seconds for 50 photos)
        for i in range(50):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        progress = await job_queue.get_progress(job_id)
        assert progress["percentage"] == 50
        assert progress["eta_seconds"] is not None
        assert progress["eta_seconds"] >= 0
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_progress_not_found(self, job_queue):
        """Verify progress returns not_found for non-existent job."""
        progress = await job_queue.get_progress("nonexistent_job")
        assert progress["status"] == "not_found"
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_progress_zero_percentage(self, job_queue):
        """Verify progress returns 0% for newly created job."""
        job_id = "test_job_progress_003"
        job_queue.create_job(job_id, 50)
        
        progress = await job_queue.get_progress(job_id)
        assert progress["percentage"] == 0
        assert progress["processed_photos"] == 0
        assert progress["total_photos"] == 50
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_progress_100_percentage(self, job_queue):
        """Verify progress returns 100% when all photos processed."""
        job_id = "test_job_progress_004"
        total = 10
        job_queue.create_job(job_id, total)
        
        # Process all photos
        for i in range(total):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        progress = await job_queue.get_progress(job_id)
        assert progress["percentage"] == 100
        assert progress["processed_photos"] == total
        assert progress["total_photos"] == total
