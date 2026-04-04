"""Unit tests for async job queue with checkpoint persistence and state recovery."""
import pytest
import asyncio
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, JobQueue
from app.job_queue import JobQueueManager


class TestJobQueueManager:
    """Unit tests for JobQueueManager async job processing and checkpointing."""
    
    @pytest.fixture
    def db_url(self):
        """Provide in-memory SQLite database URL for testing."""
        return "sqlite:///:memory:"
    
    @pytest.fixture
    def job_queue(self, db_url):
        """Create JobQueueManager with test database."""
        manager = JobQueueManager(database_url=db_url)
        # Create tables
        Base.metadata.create_all(manager.engine)
        return manager
    
    @pytest.mark.unit
    def test_create_job(self, job_queue):
        """Verify job creation stores job in database with correct initial state."""
        job_id = "test_job_001"
        total_photos = 25
        
        result = job_queue.create_job(job_id, total_photos)
        assert result is True
        
        # Verify job in database
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job is not None
        assert job.status == "pending"
        assert job.total_photos == 25
        assert job.processed_photos == 0
        assert job.checkpoint_count == 0
        session.close()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_process_photo_increments_counter(self, job_queue):
        """Verify processing a photo increments the processed_photos counter."""
        job_id = "test_job_002"
        job_queue.create_job(job_id, 10)
        
        # Process 3 photos
        for i in range(3):
            result = await job_queue.process_photo(job_id, photo_id=i+1)
            assert result is True
        
        # Verify counter in memory
        assert job_queue.active_jobs[job_id]["processed_photos"] == 3
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_checkpoint_saved_after_5_photos(self, job_queue):
        """Verify checkpoint is saved to database after processing 5 photos."""
        job_id = "test_job_003"
        job_queue.create_job(job_id, 10)
        
        # Process 5 photos (should trigger checkpoint)
        for i in range(5):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        # Verify checkpoint saved in database
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job.processed_photos == 5
        assert job.checkpoint_count == 1
        assert job.last_checkpoint_at is not None
        session.close()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_checkpoints(self, job_queue):
        """Verify multiple checkpoints are saved correctly for 10+ photos."""
        job_id = "test_job_004"
        job_queue.create_job(job_id, 15)
        
        # Process 12 photos (should create 2 checkpoints at 5 and 10)
        for i in range(12):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        # Verify checkpoints in database
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job.processed_photos == 12
        assert job.checkpoint_count == 2  # 12 // 5 = 2
        session.close()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_complete_job_success(self, job_queue):
        """Verify job completion marks status as completed and clears active job."""
        job_id = "test_job_005"
        job_queue.create_job(job_id, 5)
        
        # Process all photos
        for i in range(5):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        # Complete job
        result = await job_queue.complete_job(job_id, success=True)
        assert result is True
        
        # Verify job status in database
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job.status == "completed"
        assert job.completed_at is not None
        session.close()
        
        # Verify removed from active jobs
        assert job_id not in job_queue.active_jobs
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_complete_job_failure(self, job_queue):
        """Verify job failure marks status as failed with error message."""
        job_id = "test_job_006"
        job_queue.create_job(job_id, 5)
        
        # Complete job with failure
        error_msg = "Processing failed: invalid image format"
        result = await job_queue.complete_job(job_id, success=False, error_message=error_msg)
        assert result is True
        
        # Verify job status and error in database
        session = job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job.status == "failed"
        assert job.error_message == error_msg
        session.close()
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_recover_from_checkpoint(self, job_queue):
        """Verify state recovery restores incomplete job from last checkpoint."""
        job_id = "test_job_007"
        job_queue.create_job(job_id, 15)
        
        # Process 7 photos (checkpoint at 5)
        for i in range(7):
            await job_queue.process_photo(job_id, photo_id=i+1)
        
        # Create new manager instance (simulating restart)
        new_manager = JobQueueManager(database_url=job_queue.database_url)
        
        # Recover from checkpoint
        recovered_job_id = await new_manager.recover_from_checkpoint()
        assert recovered_job_id == job_id
        
        # Verify recovered state
        assert job_id in new_manager.active_jobs
        assert new_manager.active_jobs[job_id]["processed_photos"] == 7
        assert new_manager.active_jobs[job_id]["checkpoint_count"] == 1
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_status(self, job_queue):
        """Verify queue status returns correct job counts and statistics."""
        # Create multiple jobs with different statuses
        job_queue.create_job("job_001", 5)
        job_queue.create_job("job_002", 10)
        await job_queue.complete_job("job_001", success=True)
        
        status = await job_queue.get_status()
        assert status["total_jobs"] == 2
        assert status["completed_jobs"] == 1
        assert status["pending_jobs"] == 1
        assert status["checkpoint_interval"] == 5
    
    @pytest.mark.unit
    def test_no_incomplete_job_recovery(self, job_queue):
        """Verify recovery returns None when no incomplete jobs exist."""
        job_id = "test_job_008"
        job_queue.create_job(job_id, 5)
        asyncio.run(job_queue.complete_job(job_id, success=True))
        
        recovered_job_id = asyncio.run(job_queue.recover_from_checkpoint())
        assert recovered_job_id is None
