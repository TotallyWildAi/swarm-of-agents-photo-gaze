"""Orchestrator for coordinating folder scanning, photo queuing, and processing."""
import asyncio
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.job_queue import JobQueueManager
from app.folder_scanner import FolderScanner
from app.models import JobQueue, ProcessingState


class Orchestrator:
    """Orchestrates folder scanning, photo queuing, and async processing with checkpoints."""
    
    CHECKPOINT_INTERVAL = 5  # Save checkpoint after every 5 photos processed
    
    def __init__(self, job_queue_manager: JobQueueManager):
        """Initialize orchestrator with job queue manager.
        
        Args:
            job_queue_manager: JobQueueManager instance for managing async jobs
        """
        self.job_queue = job_queue_manager
        self.folder_scanner = FolderScanner()
    
    async def scan_and_queue_folder(
        self,
        folder_path: str,
        job_id: Optional[str] = None
    ) -> str:
        """Scan folder, queue photos, and start async processing.
        
        Args:
            folder_path: Path to folder to scan
            job_id: Optional job ID (generated if not provided)
        
        Returns:
            Job ID for tracking the processing job
        """
        # Generate job ID if not provided
        if not job_id:
            job_id = f"job_{uuid.uuid4().hex[:12]}"
        
        try:
            # Scan folder and get photo IDs
            session = self.job_queue.SessionLocal()
            photo_ids, total_count = self.folder_scanner.scan_folder(
                folder_path,
                session
            )
            session.close()
            
            if total_count == 0:
                raise ValueError(f"No photos found in folder: {folder_path}")
            
            # Create job in queue
            self.job_queue.create_job(job_id, total_count)
            
            # Start async processing task
            asyncio.create_task(
                self._process_photos_async(job_id, photo_ids)
            )
            
            print(f"Job {job_id} created: {total_count} photos queued for processing")
            return job_id
        except Exception as e:
            print(f"Error scanning folder {folder_path}: {e}")
            raise
    
    async def _process_photos_async(self, job_id: str, photo_ids: list) -> None:
        """Process photos asynchronously with checkpoint management.
        
        Args:
            job_id: Job identifier
            photo_ids: List of photo IDs to process
        """
        try:
            # Update job status to processing
            session = self.job_queue.SessionLocal()
            job = session.query(JobQueue).filter(JobQueue.job_id == job_id).first()
            if job:
                job.status = "processing"
                job.started_at = datetime.utcnow()
                session.commit()
            session.close()
            
            # Process each photo with checkpoint management
            processed_count = 0
            for idx, photo_id in enumerate(photo_ids, 1):
                success = await self.job_queue.process_photo(job_id, photo_id)
                if success:
                    processed_count += 1
                    # Update ProcessingState to completed
                    session = self.job_queue.SessionLocal()
                    state = session.query(ProcessingState).filter(
                        ProcessingState.photo_id == photo_id
                    ).first()
                    if state:
                        state.status = "completed"
                        state.extraction_status = "completed"
                        state.embedding_status = "completed"
                        state.completed_at = datetime.utcnow()
                        session.commit()
                    session.close()
                    
                    # Save checkpoint after every 5 photos
                    if processed_count % self.CHECKPOINT_INTERVAL == 0:
                        session = self.job_queue.SessionLocal()
                        job = session.query(JobQueue).filter(
                            JobQueue.job_id == job_id
                        ).first()
                        if job:
                            job.processed_photos = processed_count
                            job.checkpoint_count = processed_count // self.CHECKPOINT_INTERVAL
                            job.last_checkpoint_at = datetime.utcnow()
                            session.commit()
                        session.close()
                else:
                    print(f"Failed to process photo {photo_id}")
            
            # Mark job as completed
            await self.job_queue.complete_job(job_id, success=True)
            print(f"Job {job_id} completed successfully")
        except Exception as e:
            print(f"Error processing photos for job {job_id}: {e}")
            await self.job_queue.complete_job(
                job_id,
                success=False,
                error_message=str(e)
            )

