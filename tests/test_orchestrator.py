"""Integration tests for orchestrator coordinating folder scanning and photo processing."""
import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Photo, ProcessingState, JobQueue
from app.job_queue import JobQueueManager
from app.orchestrator import Orchestrator
from app.folder_scanner import FolderScanner


class TestOrchestrator:
    """Integration tests for orchestrator with folder scanning and checkpointing."""
    
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
    
    @pytest.fixture
    def orchestrator(self, job_queue):
        """Create Orchestrator with test job queue."""
        return Orchestrator(job_queue)
    
    @pytest.fixture
    def temp_photo_folder(self):
        """Create temporary folder with test image files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create dummy image files
            for i in range(12):
                img_path = os.path.join(tmpdir, f"photo_{i:02d}.jpg")
                # Create minimal JPEG file (1x1 pixel)
                with open(img_path, "wb") as f:
                    f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
                    f.write(b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t")
                    f.write(b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a")
                    f.write(b"\x1f\x1e\x1d\x1a\x1c\x1c $.\'\"\x2c\x20\x20(7,01444\x1f\'9=82<.342")
                    f.write(b"\xff\xd9")  # JPEG end marker
            yield tmpdir
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_scan_and_queue_folder(self, orchestrator, temp_photo_folder):
        """Verify folder scanning queues all photos correctly."""
        job_id = await orchestrator.scan_and_queue_folder(temp_photo_folder)
        assert job_id is not None
        
        # Verify job created in database
        session = orchestrator.job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job is not None
        assert job.total_photos == 12
        assert job.status == "processing"
        session.close()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_folder_scanner_creates_photo_records(self, job_queue, temp_photo_folder):
        """Verify folder scanner creates Photo and ProcessingState records."""
        scanner = FolderScanner()
        session = job_queue.SessionLocal()
        
        photo_ids, total_count = scanner.scan_folder(temp_photo_folder, session)
        
        assert total_count == 12
        assert len(photo_ids) == 12
        
        # Verify Photo records created
        photos = session.query(Photo).all()
        assert len(photos) == 12
        
        # Verify ProcessingState records created
        states = session.query(ProcessingState).all()
        assert len(states) == 12
        for state in states:
            assert state.status == "pending"
            assert state.extraction_status == "pending"
            assert state.embedding_status == "pending"
        
        session.close()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_checkpoint_after_5_photos(self, orchestrator, temp_photo_folder):
        """Verify checkpoint is saved after processing 5 photos."""
        job_id = await orchestrator.scan_and_queue_folder(temp_photo_folder)
        
        # Wait for async processing to complete
        await asyncio.sleep(2)
        
        # Verify checkpoint saved
        session = orchestrator.job_queue.SessionLocal()
        job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
        assert job.checkpoint_count >= 1  # At least one checkpoint (5 photos)
        assert job.last_checkpoint_at is not None
        session.close()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_processing_state_updated(self, orchestrator, temp_photo_folder):
        """Verify processing state is updated during photo processing."""
        job_id = await orchestrator.scan_and_queue_folder(temp_photo_folder)
        
        # Wait for async processing to complete
        await asyncio.sleep(2)
        
        # Verify processing states updated
        session = orchestrator.job_queue.SessionLocal()
        states = session.query(ProcessingState).all()
        for state in states:
            assert state.status == "completed"
            assert state.extraction_status == "completed"
            assert state.embedding_status == "completed"
            assert state.completed_at is not None
        session.close()

