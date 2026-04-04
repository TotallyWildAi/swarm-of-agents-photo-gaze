import os
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from alembic.config import Config
from alembic.command import upgrade
from app.job_queue import JobQueueManager
from app.folder_scanner import FolderScanner
from app.thumbnail import ThumbnailService
from app.models import Photo
from sqlalchemy.orm import sessionmaker

app = FastAPI(title="App API")
job_queue_manager = None
thumbnail_service = ThumbnailService()


def run_migrations():
    """Run Alembic migrations on startup to ensure schema is up-to-date."""
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/app_db")
    if not database_url:
        return
    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"Warning: Migration failed: {e}")


@app.on_event("startup")
async def startup_event():
    """Run migrations and recover job queue state on application startup."""
    global job_queue_manager
    run_migrations()
    # Initialize job queue manager and recover from last checkpoint
    job_queue_manager = JobQueueManager()
    await job_queue_manager.recover_from_checkpoint()


@app.get("/health")
async def health_check():
    """Health check endpoint for service verification."""
    return JSONResponse(status_code=200, content={"status": "healthy"})


@app.get("/job-queue/status")
async def get_job_queue_status():
    """Get current job queue status and checkpoint information."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Job queue not initialized"})
    status = await job_queue_manager.get_status()
    return JSONResponse(status_code=200, content=status)


@app.post("/rescan")
async def rescan_folder(folder_path: str = None):
    """Trigger manual folder re-scan with change detection and incremental processing.
    
    Scans folder for new/modified/deleted photos, queues changes for processing.
    Returns job_id for tracking progress via WebSocket.
    """
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Job queue not initialized"})
    
    if not folder_path:
        folder_path = os.getenv("PHOTOS_FOLDER", "./photos")
    
    if not os.path.isdir(folder_path):
        return JSONResponse(status_code=400, content={"error": f"Folder not found: {folder_path}"})
    
    try:
        # Initialize scanner and database session
        scanner = FolderScanner()
        session = job_queue_manager.SessionLocal()
        
        # Scan folder for changes (new, modified, deleted photos)
        photo_ids, change_count = scanner.scan_folder(folder_path, session)
        session.close()
        
        if change_count == 0:
            return JSONResponse(status_code=200, content={
                "message": "No changes detected",
                "changes_found": 0
            })
        
        # Create job for processing changed photos
        job_id = str(uuid.uuid4())
        job_created = job_queue_manager.create_job(job_id, change_count)
        
        if not job_created:
            return JSONResponse(status_code=500, content={"error": "Failed to create processing job"})
        
        # Queue photos for processing
        for photo_id in photo_ids:
            asyncio.create_task(job_queue_manager.process_photo(job_id, photo_id))
        
        return JSONResponse(status_code=202, content={
            "job_id": job_id,
            "message": "Rescan initiated",
            "changes_found": change_count,
            "photos_queued": len(photo_ids)
        })
    except Exception as e:
        print(f"Error during rescan: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/thumbnails/{photo_id}")
async def get_thumbnail(photo_id: int, size: int = 200):
    """Return a cached thumbnail for the given photo, generating it if needed."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})

    session = job_queue_manager.SessionLocal()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            return JSONResponse(status_code=404, content={"error": "Photo not found"})

        if not os.path.isfile(photo.file_path):
            return JSONResponse(status_code=404, content={"error": "Photo file not found on disk"})

        thumb_path = thumbnail_service.get_thumbnail(
            photo.file_path, photo.file_hash, size=(size, size)
        )
        return FileResponse(thumb_path, media_type="image/jpeg")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        session.close()


@app.websocket("/ws/progress/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time progress updates during photo processing.
    
    Broadcasts progress updates including percentage completion and estimated time remaining.
    """
    await websocket.accept()
    try:
        if job_queue_manager is None:
            await websocket.send_json({"error": "Job queue not initialized"})
            await websocket.close()
            return
        
        # Send progress updates every 100ms while job is active
        while True:
            if job_id in job_queue_manager.active_jobs:
                progress_data = await job_queue_manager.get_progress(job_id)
                await websocket.send_json(progress_data)
            else:
                # Job not found or completed
                await websocket.send_json({"status": "not_found"})
                break
            
            await asyncio.sleep(0.1)  # Update every 100ms
    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        print(f"WebSocket error for job {job_id}: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass
