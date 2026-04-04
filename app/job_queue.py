"""Async job queue manager for photo processing with checkpoint persistence and state recovery."""
import asyncio
import json
import os
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from app.models import JobQueue, Base, Photo, ProcessingState
from app.embedding_generator import EmbeddingGenerator
from app.metadata_extractor import MetadataExtractor


class JobQueueManager:
    """Manages async photo processing jobs with checkpoint persistence every 5 photos."""
    
    CHECKPOINT_INTERVAL = 5  # Save checkpoint after processing 5 photos
    
    def __init__(self, database_url: str = None):
        """Initialize job queue manager with database connection.
        
        Args:
            database_url: PostgreSQL connection URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/app_db"
        )
        self.engine = create_engine(self.database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.active_jobs: Dict[str, Dict] = {}  # In-memory tracking of active jobs
        self.embedding_generator = EmbeddingGenerator()
        self.metadata_extractor = MetadataExtractor()
    
    def create_job(self, job_id: str, total_photos: int) -> bool:
        """Create a new processing job in the queue.
        
        Args:
            job_id: Unique job identifier
            total_photos: Total number of photos to process
        
        Returns:
            True if job created successfully, False otherwise
        """
        try:
            session = self.SessionLocal()
            job = JobQueue(
                job_id=job_id,
                status="pending",
                total_photos=total_photos,
                processed_photos=0,
                checkpoint_count=0
            )
            session.add(job)
            session.commit()
            session.close()
            self.active_jobs[job_id] = {
                "status": "pending",
                "processed_photos": 0,
                "checkpoint_count": 0
            }
            return True
        except Exception as e:
            print(f"Error creating job {job_id}: {e}")
            return False
    
    async def process_photo(self, job_id: str, photo_id: int) -> bool:
        """Process a single photo: extract metadata and generate embedding.
        
        Args:
            job_id: Job identifier
            photo_id: Photo ID to process
        
        Returns:
            True if photo processed successfully, False otherwise
        """
        try:
            session = self.SessionLocal()
            photo = session.query(Photo).filter(Photo.id == photo_id).first()
            if not photo:
                session.close()
                return False
            
            # Extract metadata from photo file
            metadata = await self.metadata_extractor.extract(photo.file_path)
            
            # Generate embedding for photo
            embedding_vector = await self.embedding_generator.generate(photo.file_path)
            
            # Update processing state
            processing_state = session.query(ProcessingState).filter(
                ProcessingState.photo_id == photo_id
            ).first()
            if processing_state:
                processing_state.extraction_status = "completed"
                processing_state.embedding_status = "completed"
                processing_state.status = "completed"
                processing_state.completed_at = datetime.utcnow()
                processing_state.updated_at = datetime.utcnow()
            
            session.commit()
            session.close()
            
            # Update in-memory tracking
            if job_id in self.active_jobs:
                self.active_jobs[job_id]["processed_photos"] += 1
                processed = self.active_jobs[job_id]["processed_photos"]
                
                # Check if checkpoint interval reached
                if processed % self.CHECKPOINT_INTERVAL == 0:
                    await self.save_checkpoint(job_id)
            
            return True
        except Exception as e:
            print(f"Error processing photo {photo_id} in job {job_id}: {e}")
            return False
    
    async def get_progress(self, job_id: str) -> dict:
        """Get current progress for a job including percentage and ETA.
        
        Args:
            job_id: Job identifier
        
        Returns:
            Dictionary with progress data: percentage, processed_photos, total_photos, eta_seconds
        """
        if job_id not in self.active_jobs:
            return {"status": "not_found"}
        
        try:
            session = self.SessionLocal()
            job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
            session.close()
            
            if not job:
                return {"status": "not_found"}
            
            processed = job.processed_photos
            total = job.total_photos
            
            # Calculate percentage
            percentage = int((processed / total * 100)) if total > 0 else 0
            
            # Calculate ETA in seconds
            eta_seconds = None
            if job.started_at and processed > 0:
                elapsed = (datetime.utcnow() - job.started_at).total_seconds()
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = total - processed
                eta_seconds = int(remaining / rate) if rate > 0 else None
            
            return {
                "job_id": job_id,
                "status": job.status,
                "percentage": percentage,
                "processed_photos": processed,
                "total_photos": total,
                "eta_seconds": eta_seconds
            }
        except Exception as e:
            print(f"Error getting progress for job {job_id}: {e}")
            return {"error": str(e)}
    
    async def save_checkpoint(self, job_id: str) -> bool:
        """Save checkpoint after processing CHECKPOINT_INTERVAL photos.
        
        Args:
            job_id: Job identifier
        
        Returns:
            True if checkpoint saved successfully, False otherwise
        """
        try:
            session = self.SessionLocal()
            job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
            if job:
                if job_id in self.active_jobs:
                    job.processed_photos = self.active_jobs[job_id]["processed_photos"]
                    job.checkpoint_count = job.processed_photos // self.CHECKPOINT_INTERVAL
                    job.last_checkpoint_at = datetime.utcnow()
                    job.updated_at = datetime.utcnow()
                    session.commit()
                    print(f"Checkpoint saved for job {job_id}: {job.processed_photos} photos processed")
            session.close()
            return True
        except Exception as e:
            print(f"Error saving checkpoint for job {job_id}: {e}")
            return False
    
    async def complete_job(self, job_id: str, success: bool = True, error_message: str = None) -> bool:
        """Mark job as completed or failed.
        
        Args:
            job_id: Job identifier
            success: True if job completed successfully, False if failed
            error_message: Error message if job failed
        
        Returns:
            True if job status updated successfully, False otherwise
        """
        try:
            session = self.SessionLocal()
            job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
            if job:
                job.status = "completed" if success else "failed"
                job.completed_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                if error_message:
                    job.error_message = error_message
                session.commit()
                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]
            session.close()
            return True
        except Exception as e:
            print(f"Error completing job {job_id}: {e}")
            return False
    
    async def recover_from_checkpoint(self) -> Optional[str]:
        """Recover incomplete job from last checkpoint on application restart.
        
        Returns:
            Job ID of recovered job, or None if no incomplete job found
        """
        try:
            session = self.SessionLocal()
            # Find most recent incomplete job
            incomplete_job = session.query(JobQueue).filter(
                JobQueue.status.in_(["pending", "processing"])
            ).order_by(JobQueue.created_at.desc()).first()
            
            if incomplete_job:
                print(f"Recovering job {incomplete_job.job_id}: ",
                      f"{incomplete_job.processed_photos}/{incomplete_job.total_photos} photos processed")
                # Restore job state to in-memory tracking
                self.active_jobs[incomplete_job.job_id] = {
                    "status": "processing",
                    "processed_photos": incomplete_job.processed_photos,
                    "checkpoint_count": incomplete_job.checkpoint_count
                }
                # Update job status to processing
                incomplete_job.status = "processing"
                incomplete_job.started_at = datetime.utcnow()
                incomplete_job.updated_at = datetime.utcnow()
                session.commit()
                session.close()
                return incomplete_job.job_id
            session.close()
            return None
        except Exception as e:
            print(f"Error recovering from checkpoint: {e}")
            return None
    
    async def get_status(self) -> Dict:
        """Get current status of all jobs and queue statistics.
        
        Returns:
            Dictionary with queue status information
        """
        try:
            session = self.SessionLocal()
            total_jobs = session.query(JobQueue).count()
            pending_jobs = session.query(JobQueue).filter(JobQueue.status == "pending").count()
            processing_jobs = session.query(JobQueue).filter(JobQueue.status == "processing").count()
            completed_jobs = session.query(JobQueue).filter(JobQueue.status == "completed").count()
            failed_jobs = session.query(JobQueue).filter(JobQueue.status == "failed").count()
            
            session.close()
            return {
                "total_jobs": total_jobs,
                "pending_jobs": pending_jobs,
                "processing_jobs": processing_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
                "active_jobs": list(self.active_jobs.keys()),
                "checkpoint_interval": self.CHECKPOINT_INTERVAL
            }
        except Exception as e:
            print(f"Error getting queue status: {e}")
            return {"error": str(e)}
