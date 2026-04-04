import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from alembic.config import Config
from alembic.command import upgrade
from app.job_queue import JobQueueManager

app = FastAPI(title="App API")
job_queue_manager = None


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
