import os

# Pin BLAS thread pools to 1 BEFORE numpy/torch import — NumPy's bundled
# OpenBLAS (pthreads) otherwise warns and risks a nested-parallel deadlock
# when called from inside PyTorch's OpenMP region. The Dockerfile sets the
# same vars at the image level; this block protects non-Docker runs too.
# setdefault so an operator override still wins.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

import asyncio
import uuid
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from alembic.config import Config
from alembic.command import upgrade
from app.job_queue import JobQueueManager
from app.folder_scanner import FolderScanner
from app.thumbnail import ThumbnailService
from app.similarity_search import SimilarityGroupService
from app.models import Photo
from app.backup_manager import BackupManager
from sqlalchemy.orm import sessionmaker
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time

logger = logging.getLogger(__name__)

app = FastAPI(title="App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics for monitoring
request_count = Counter(
    'fastapi_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)
request_duration = Histogram(
    'fastapi_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint']
)
active_requests = Gauge(
    'fastapi_active_requests',
    'Number of active HTTP requests'
)
errors_total = Counter(
    'fastapi_errors_total',
    'Total errors',
    ['error_type']
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to track request metrics for Prometheus."""
    active_requests.inc()
    start_time = time.time()
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        request_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        request_count.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        return response
    except Exception as e:
        errors_total.labels(error_type=type(e).__name__).inc()
        raise
    finally:
        active_requests.dec()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler so unhandled errors return structured JSON instead of 500 HTML."""
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    errors_total.labels(error_type=type(exc).__name__).inc()
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return HTTPException errors in a consistent JSON envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "path": str(request.url.path),
        },
    )


job_queue_manager = None
backup_manager = None
thumbnail_service = ThumbnailService()
# Alias used by similarity endpoints and tests
thumbnail_generator = thumbnail_service
similarity_group_service = SimilarityGroupService()


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
    global job_queue_manager, backup_manager
    run_migrations()
    # Create any tables that aren't covered by Alembic migrations yet
    # (e.g. job_queue, which is defined in models.py but has no migration).
    from app.database import init_db, init_qdrant_collection
    init_db()
    init_qdrant_collection()
    # Initialize job queue manager and recover from last checkpoint
    job_queue_manager = JobQueueManager()
    await job_queue_manager.recover_from_checkpoint()
    # Initialize backup manager for disaster recovery
    backup_manager = BackupManager()
    await backup_manager.schedule_automated_backups()
    # Eagerly compute similarity matrix so first request is fast
    await _recompute_sim_cache()


@app.post("/backup/manual")
async def trigger_manual_backup():
    """Trigger an immediate backup of PostgreSQL and Qdrant data."""
    if backup_manager is None:
        return JSONResponse(status_code=503, content={"error": "Backup manager not initialized"})
    try:
        backup_id = await backup_manager.create_backup()
        return JSONResponse(status_code=202, content={
            "backup_id": backup_id,
            "message": "Backup initiated",
            "status": "in_progress"
        })
    except Exception as e:
        logger.error("Error creating backup: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "Failed to create backup",
            "detail": str(e)
        })


@app.get("/backup/status")
async def get_backup_status():
    """Get status of recent backups and recovery options."""
    if backup_manager is None:
        return JSONResponse(status_code=503, content={"error": "Backup manager not initialized"})
    try:
        status = await backup_manager.get_backup_status()
        return JSONResponse(status_code=200, content=status)
    except Exception as e:
        logger.error("Error getting backup status: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "Failed to get backup status",
            "detail": str(e)
        })


@app.post("/backup/recover/{backup_id}")
async def recover_from_backup(backup_id: str):
    """Recover PostgreSQL and Qdrant data from a specific backup."""
    if backup_manager is None:
        return JSONResponse(status_code=503, content={"error": "Backup manager not initialized"})
    try:
        success = await backup_manager.restore_backup(backup_id)
        if success:
            return JSONResponse(status_code=200, content={
                "backup_id": backup_id,
                "message": "Recovery completed successfully",
                "status": "recovered"
            })
        else:
            return JSONResponse(status_code=400, content={
                "error": "Backup not found or recovery failed",
                "backup_id": backup_id
            })
    except Exception as e:
        logger.error("Error recovering from backup %s: %s", backup_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "Failed to recover from backup",
            "detail": str(e)
        })


@app.post("/process-pending")
async def process_pending_photos():
    """Queue all photos with pending processing state for embedding generation."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Job queue not initialized"})
    from app.models import Photo as _Photo, ProcessingState as _PS
    session = job_queue_manager.SessionLocal()
    try:
        pending = (
            session.query(_Photo.id)
            .join(_PS, _PS.photo_id == _Photo.id)
            .filter(_PS.status == "pending")
            .all()
        )
        photo_ids = [row[0] for row in pending]
    finally:
        session.close()

    if not photo_ids:
        return JSONResponse(status_code=200, content={"message": "No pending photos", "queued": 0})

    job_id = str(uuid.uuid4())
    job_queue_manager.create_job(job_id, len(photo_ids))
    for pid in photo_ids:
        asyncio.create_task(job_queue_manager.process_photo(job_id, pid))
    return JSONResponse(status_code=202, content={
        "job_id": job_id,
        "message": "Processing started",
        "queued": len(photo_ids),
    })


@app.post("/stop-processing")
async def stop_processing():
    """Cancel all active processing jobs. Pending photos remain in pending state for later resume."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Job queue not initialized"})
    cancelled = await job_queue_manager.cancel_all_jobs()
    return JSONResponse(status_code=200, content={
        "message": "Processing stopped",
        "cancelled_jobs": cancelled,
    })


@app.get("/stats")
async def get_stats():
    """Return high-level processing stats for the UI progress panel."""
    from app.database import SessionLocal as _SL
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS
    session = _SL()
    try:
        total_photos = session.query(_Photo).count()
        total_embeddings = session.query(_Emb).count()
        completed = session.query(_PS).filter(_PS.status == "completed").count()
        pending = session.query(_PS).filter(_PS.status == "pending").count()
        failed = session.query(_PS).filter(_PS.status == "failed").count()
        return {
            "photos": total_photos,
            "embeddings": total_embeddings,
            "completed": completed,
            "pending": pending,
            "failed": failed,
        }
    finally:
        session.close()


@app.get("/health")
async def health_check():
    """Health check endpoint for service verification."""
    return JSONResponse(status_code=200, content={"status": "healthy"})


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint for monitoring."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/job-queue/status")
async def get_job_queue_status():
    """Get current job queue status and checkpoint information."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Job queue not initialized"})
    status = await job_queue_manager.get_status()
    return JSONResponse(status_code=200, content=status)


TRASH_DIR = os.getenv("TRASH_DIR", os.path.expanduser("~/.photo-gaze-trash"))


@app.post("/deduplicate")
async def deduplicate_photos(request: Request):
    """Move selected photos to ~/.photo-gaze-trash/ and remove from DB + Qdrant.

    Files are moved (not copied) into a flat trash directory with a
    timestamp prefix to avoid name collisions. The original directory
    structure is recorded in a .manifest.json so files can be restored.
    """
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS
    import shutil

    body = await request.json()
    photo_ids = body.get("photo_ids", [])
    if not photo_ids:
        return JSONResponse(status_code=400, content={"error": "photo_ids is required"})

    session = job_queue_manager.SessionLocal()
    try:
        # Look up file paths before deleting DB rows
        photos = session.query(_Photo).filter(_Photo.id.in_(photo_ids)).all()
        file_paths = {p.id: p.file_path for p in photos}

        # Move files to trash
        os.makedirs(TRASH_DIR, exist_ok=True)
        moved = []
        move_errors = []
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        for pid, src in file_paths.items():
            if not os.path.isfile(src):
                continue
            basename = os.path.basename(src)
            dest = os.path.join(TRASH_DIR, f"{ts}_{pid}_{basename}")
            try:
                shutil.move(src, dest)
                moved.append({"photo_id": pid, "original": src, "trash": dest})
            except Exception as e:
                move_errors.append({"photo_id": pid, "error": str(e)})

        # Write manifest so files can be restored later
        if moved:
            import json as _json
            manifest_path = os.path.join(TRASH_DIR, f"{ts}_manifest.json")
            existing = []
            if os.path.isfile(manifest_path):
                with open(manifest_path) as f:
                    existing = _json.load(f)
            existing.extend(moved)
            with open(manifest_path, "w") as f:
                _json.dump(existing, f, indent=2)

        # Remove from Qdrant
        qdrant_point_ids = [
            qid for (qid,) in session.query(_Emb.qdrant_point_id)
            .filter(_Emb.photo_id.in_(photo_ids))
            .filter(_Emb.qdrant_point_id.isnot(None))
            .all()
        ]
        if qdrant_point_ids:
            try:
                job_queue_manager.qdrant_client.delete(
                    collection_name="embeddings",
                    points_selector=qdrant_point_ids,
                )
            except Exception as e:
                logger.warning("Qdrant delete failed: %s", e)

        # Remove from Postgres
        session.query(_Emb).filter(_Emb.photo_id.in_(photo_ids)).delete(synchronize_session=False)
        session.query(_PS).filter(_PS.photo_id.in_(photo_ids)).delete(synchronize_session=False)
        deleted = session.query(_Photo).filter(_Photo.id.in_(photo_ids)).delete(synchronize_session=False)
        session.commit()

        # Immediately recompute similarity matrix after deletion
        await _recompute_sim_cache()

        return {
            "deleted": deleted,
            "moved_to_trash": len(moved),
            "trash_dir": TRASH_DIR,
            "errors": move_errors if move_errors else None,
        }
    finally:
        session.close()


@app.get("/browse")
async def browse_directory(path: str = "/"):
    """List subdirectories and image-file counts at a path for the folder picker."""
    path = path or "/"
    if not os.path.isdir(path):
        return JSONResponse(status_code=400, content={"error": f"Not a directory: {path}"})

    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"}
    entries = []
    image_count = 0
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if name.startswith("."):
                continue  # skip hidden
            if os.path.isdir(full):
                entries.append({"name": name, "type": "dir"})
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in image_exts:
                    image_count += 1
    except PermissionError:
        return JSONResponse(status_code=403, content={"error": f"Permission denied: {path}"})

    parent = os.path.dirname(path.rstrip("/")) or "/"
    return {
        "path": path,
        "parent": parent if parent != path else None,
        "dirs": entries,
        "image_count": image_count,
    }


def _count_supported_files(folder_path: str) -> list:
    """Return the set of supported image extensions found in a folder (non-recursive head probe)."""
    supported = {
        ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".webp",
        ".heic", ".heif", ".tiff", ".tif", ".avif", ".ico",
        ".dng", ".cr2", ".nef", ".arw", ".orf", ".rw2", ".pef",
    }
    found = set()
    try:
        for name in os.listdir(folder_path):
            ext = os.path.splitext(name)[1].lower()
            if ext in supported:
                found.add(ext)
    except Exception:
        pass
    return sorted(found)


@app.get("/folders")
async def list_folders():
    """Return registered photo folders."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import FolderPath
    session = job_queue_manager.SessionLocal()
    try:
        rows = session.query(FolderPath).order_by(FolderPath.id.asc()).all()
        return [
            {
                "id": f.id,
                "path": f.path,
                "is_accessible": f.is_accessible,
                "supported_formats_found": f.supported_formats_found or [],
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in rows
        ]
    finally:
        session.close()


@app.post("/folders")
async def add_folder(request: Request):
    """Register a new folder to scan. Validates accessibility server-side."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import FolderPath
    body = await request.json()
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse(status_code=400, content={"error": "path is required"})

    is_accessible = os.path.isdir(path) and os.access(path, os.R_OK)
    formats = _count_supported_files(path) if is_accessible else []

    session = job_queue_manager.SessionLocal()
    try:
        existing = session.query(FolderPath).filter(FolderPath.path == path).first()
        if existing:
            existing.is_accessible = is_accessible
            existing.supported_formats_found = formats
            existing.updated_at = datetime.utcnow()
            session.commit()
            folder = existing
        else:
            folder = FolderPath(path=path, is_accessible=is_accessible, supported_formats_found=formats)
            session.add(folder)
            session.commit()
            session.refresh(folder)
        return {
            "id": folder.id,
            "path": folder.path,
            "is_accessible": folder.is_accessible,
            "supported_formats_found": folder.supported_formats_found or [],
        }
    finally:
        session.close()


@app.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int):
    """Remove a folder from the registry AND purge every photo / embedding
    whose file_path lives under that folder. Qdrant points are deleted too.
    """
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import FolderPath, Photo, Embedding, ProcessingState

    session = job_queue_manager.SessionLocal()
    try:
        folder = session.query(FolderPath).filter(FolderPath.id == folder_id).first()
        if not folder:
            return JSONResponse(status_code=404, content={"error": "Folder not found"})

        # Match any photo whose path is inside the folder (prefix match with
        # trailing separator so /photos/a doesn't match /photos/abc).
        prefix = folder.path.rstrip("/") + "/"
        photo_ids = [
            pid for (pid,) in session.query(Photo.id)
            .filter(Photo.file_path.like(prefix + "%"))
            .all()
        ]

        qdrant_point_ids = []
        if photo_ids:
            qdrant_point_ids = [
                pid for (pid,) in session.query(Embedding.qdrant_point_id)
                .filter(Embedding.photo_id.in_(photo_ids))
                .filter(Embedding.qdrant_point_id.isnot(None))
                .all()
            ]

        # Remove from Qdrant first — if this fails we don't want the DB rows
        # gone already (otherwise orphaned vectors would linger).
        if qdrant_point_ids:
            try:
                job_queue_manager.qdrant_client.delete(
                    collection_name="embeddings",
                    points_selector=qdrant_point_ids,
                )
            except Exception as e:
                logger.warning("Failed to delete %d Qdrant points: %s", len(qdrant_point_ids), e)

        # Cascade deletes in child-first order to satisfy FKs.
        if photo_ids:
            session.query(Embedding).filter(Embedding.photo_id.in_(photo_ids)).delete(synchronize_session=False)
            session.query(ProcessingState).filter(ProcessingState.photo_id.in_(photo_ids)).delete(synchronize_session=False)
            session.query(Photo).filter(Photo.id.in_(photo_ids)).delete(synchronize_session=False)

        session.delete(folder)
        session.commit()

        # Immediately recompute similarity matrix after folder deletion
        if photo_ids:
            await _recompute_sim_cache()

        return {
            "deleted": folder_id,
            "photos_removed": len(photo_ids),
            "embeddings_removed": len(qdrant_point_ids),
        }
    finally:
        session.close()


@app.post("/folders/{folder_id}/scan")
async def scan_folder_by_id(folder_id: int):
    """Trigger a scan of a registered folder, reusing the /rescan logic."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import FolderPath
    session = job_queue_manager.SessionLocal()
    try:
        folder = session.query(FolderPath).filter(FolderPath.id == folder_id).first()
        folder_path = folder.path if folder else None
    finally:
        session.close()
    if not folder_path:
        return JSONResponse(status_code=404, content={"error": "Folder not found"})
    return await rescan_folder(folder_path=folder_path)


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
    
    if not os.path.exists(folder_path):
        return JSONResponse(status_code=400, content={
            "error": f"Path does not exist: {folder_path}",
            "detail": "Please provide a valid folder path that exists on the server.",
        })
    
    if not os.path.isdir(folder_path):
        return JSONResponse(status_code=400, content={
            "error": f"Path is not a directory: {folder_path}",
            "detail": "The provided path exists but is not a folder. Please provide a directory path.",
        })
    
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
        logger.error("Error during rescan of '%s': %s", folder_path, e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "Failed to rescan folder",
            "detail": str(e),
        })


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
        logger.error("Error generating thumbnail for photo %d: %s", photo_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "Failed to generate thumbnail",
            "detail": str(e),
        })
    finally:
        session.close()


_BROWSER_NATIVE_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"}


@app.get("/photos/{photo_id}/full")
async def get_full_photo(photo_id: int):
    """Serve the full-resolution photo. HEIC/HEIF and other browser-
    incompatible formats are transcoded to JPEG on the fly."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    session = job_queue_manager.SessionLocal()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            return JSONResponse(status_code=404, content={"error": "Photo not found"})
        if not os.path.isfile(photo.file_path):
            return JSONResponse(status_code=404, content={"error": "File not found on disk"})

        ext = os.path.splitext(photo.file_path)[1].lower()
        if ext in _BROWSER_NATIVE_EXTS:
            import mimetypes
            mt = mimetypes.guess_type(photo.file_path)[0] or "image/jpeg"
            return FileResponse(photo.file_path, media_type=mt)

        # Non-native format (HEIC, HEIF, TIFF, etc.) — decode with Pillow
        # and stream as high-quality JPEG.
        from PIL import Image as _PILImage
        import io as _io
        img = _PILImage.open(photo.file_path)
        img = img.convert("RGB")  # drop alpha / palette if present
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")
    except Exception as e:
        logger.error("Error serving full photo %d: %s", photo_id, e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to serve photo", "detail": str(e)})
    finally:
        session.close()


import functools
import numpy as np

@functools.lru_cache(maxsize=4096)
def _read_image_info(file_path: str) -> tuple:
    """Read dimensions + EXIF date from an image file. Returns a tuple
    (width, height, created_date_iso_or_None). Cached per file path."""
    width = height = None
    created_date = None
    try:
        from PIL import Image as _Img
        with _Img.open(file_path) as img:
            width = img.width
            height = img.height
            exif = img.getexif() if hasattr(img, "getexif") else {}
            for tag in (36867, 306):
                val = exif.get(tag)
                if val:
                    try:
                        created_date = datetime.strptime(str(val), "%Y:%m:%d %H:%M:%S").isoformat()
                    except Exception:
                        pass
                    break
            if not created_date:
                mtime = os.path.getmtime(file_path)
                created_date = datetime.fromtimestamp(mtime).isoformat()
    except Exception:
        pass
    return (width, height, created_date)


# --------------- Event-driven similarity matrix cache ---------------
#
# The matrix is recomputed when embeddings change:
#   - Additions: job_queue calls notify_embeddings_changed() after upsert;
#     a debounce task coalesces rapid additions into a single recompute that
#     fires 60s after the LAST change in the photo collection — UI sees
#     fresh groupings within a minute of being idle, without paying for a
#     recompute after every individual photo during a long batch scan.
#   - Deletions: deduplicate / folder-delete call _recompute_sim_cache()
#     immediately so the UI reflects user-driven removals right away.
# The endpoint reads from the precomputed cache with zero computation.

_sim_cache: Dict[str, object] = {"data": None, "meta": None}
_sim_debounce_handle: Optional[asyncio.TimerHandle] = None
_sim_recompute_lock: Optional[asyncio.Lock] = None
_SIM_DEBOUNCE_SECONDS = 60.0
_SIM_SCROLL_PAGE = 2000  # Qdrant scroll batch size


def _get_recompute_lock() -> asyncio.Lock:
    """Lazy-construct the lock against the running loop. A module-level
    Lock would bind to whichever loop happened to be current at import
    time, which breaks under TestClient (one loop per request)."""
    global _sim_recompute_lock
    if _sim_recompute_lock is None:
        _sim_recompute_lock = asyncio.Lock()
    return _sim_recompute_lock


def _compute_sim_cache():
    """Synchronous: scroll Qdrant, query Postgres, build similarity matrix.
    Returns (cache_data, photo_meta) or (None, None).

    Pages through Qdrant in batches of _SIM_SCROLL_PAGE rather than capping
    at a single 10k-vector page — collections larger than the page size
    would otherwise be silently truncated and missing from the matrix.
    """
    qc = job_queue_manager.qdrant_client if job_queue_manager else None
    if qc is None:
        return None, None
    collection = "embeddings"
    points: list = []
    next_offset = None
    while True:
        page, next_offset = qc.scroll(
            collection_name=collection,
            limit=_SIM_SCROLL_PAGE,
            offset=next_offset,
            with_payload=True,
            with_vectors=True,
        )
        if not page:
            break
        points.extend(page)
        if next_offset is None:
            break
    if not points:
        return None, None

    # Load photo metadata from Postgres
    session = job_queue_manager.SessionLocal()
    photo_meta: Dict[int, dict] = {}
    try:
        rows = session.query(
            Photo.id, Photo.filename, Photo.file_path,
            Photo.file_size, Photo.mime_type, Photo.uploaded_at
        ).all()
        for r in rows:
            photo_meta[r[0]] = {
                "filename": r[1], "file_path": r[2], "file_size": r[3],
                "mime_type": r[4],
                "uploaded_at": r[5].isoformat() if r[5] else None,
            }
    finally:
        session.close()

    valid_ids = set(photo_meta.keys())
    filtered = [(p, int(p.payload.get("photo_id", 0))) for p in points
                if int(p.payload.get("photo_id", 0)) in valid_ids]
    if not filtered:
        return None, None

    point_ids = [p.id for p, _ in filtered]
    photo_ids = [pid for _, pid in filtered]
    vecs = np.array([p.vector for p, _ in filtered], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms

    sim_matrix = vecs @ vecs.T

    cache_data = {"sim_matrix": sim_matrix, "photo_ids": photo_ids, "point_ids": point_ids}
    return cache_data, photo_meta


async def _recompute_sim_cache():
    """Recompute the matrix (runs heavy work in a thread) and update the cache.
    Lock-guarded so concurrent triggers (debounce + delete) don't stomp."""
    async with _get_recompute_lock():
        loop = asyncio.get_running_loop()
        cache_data, photo_meta = await loop.run_in_executor(None, _compute_sim_cache)
        _sim_cache.update(data=cache_data, meta=photo_meta)
        count = len(cache_data["photo_ids"]) if cache_data else 0
        logger.info("Similarity matrix recomputed: %d vectors", count)


def notify_embeddings_changed():
    """Call after an embedding is added/updated. Debounces: recomputes the
    matrix once after _SIM_DEBOUNCE_SECONDS of no further changes, so a long
    batch scan triggers a single recompute when it finishes idle, not one
    per photo."""
    global _sim_debounce_handle
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (e.g. called from a sync test) — skip debounce
        return
    # Cancel any pending debounce
    if _sim_debounce_handle is not None:
        _sim_debounce_handle.cancel()
    _sim_debounce_handle = loop.call_later(
        _SIM_DEBOUNCE_SECONDS,
        lambda: asyncio.ensure_future(_recompute_sim_cache()),
    )


def _get_cached_data():
    """Return (cache_data, photo_meta) from the precomputed cache.
    If cache is empty (first call before any event), compute synchronously.
    Startup eagerly precomputes, so this fallback is only hit when the
    server skipped startup (e.g. some tests) or before any embeddings exist."""
    if _sim_cache["data"] is not None:
        return _sim_cache["data"], _sim_cache["meta"]
    cache_data, photo_meta = _compute_sim_cache()
    _sim_cache.update(data=cache_data, meta=photo_meta)
    return cache_data, photo_meta


def _build_similarity_groups_from_qdrant(threshold: float):
    """Cluster vectors into groups of similar photos using a precomputed
    cosine similarity matrix. Scrolls Qdrant once (cached) and groups
    entirely in-memory."""
    cache_data, photo_meta = _get_cached_data()
    if cache_data is None:
        return []

    sim_matrix = cache_data["sim_matrix"]
    photo_ids = cache_data["photo_ids"]
    n = len(photo_ids)

    visited = set()
    groups = []

    for i in range(n):
        if i in visited:
            continue
        # Look up row i from precomputed matrix
        neighbour_indices = np.where(sim_matrix[i] >= threshold)[0]

        if len(neighbour_indices) < 2:
            visited.add(i)
            continue

        members = []
        for j in neighbour_indices.tolist():
            if j in visited and j != i:
                continue
            visited.add(j)
            pid = photo_ids[j]
            meta = photo_meta.get(pid, {})
            fpath = meta.get("file_path")
            img_info_tuple = _read_image_info(fpath) if fpath and os.path.isfile(fpath) else (None, None, None)
            members.append({
                "_idx": j,  # matrix index, stripped before response
                "photo_id": pid,
                "filename": meta.get("filename", str(pid)),
                "path": f"http://localhost:8000/thumbnails/{pid}",
                "similarity_score": 0.0,  # placeholder, recomputed below
                "file_size": meta.get("file_size"),
                "file_path": fpath,
                "mime_type": meta.get("mime_type"),
                "uploaded_at": meta.get("uploaded_at"),
                "width": img_info_tuple[0],
                "height": img_info_tuple[1],
                "created_date": img_info_tuple[2],
            })

        if len(members) < 2:
            continue

        # Pick best photo
        _preferred_types = {"image/jpeg", "image/png"}

        def _best_key(m):
            size = m.get("file_size") or 0
            fmt_bonus = int(size * 0.2) if m.get("mime_type") in _preferred_types else 0
            score = size + fmt_bonus
            try:
                ts_val = datetime.fromisoformat(m["uploaded_at"]).timestamp() if m.get("uploaded_at") else 9e12
            except Exception:
                ts_val = 9e12
            name_len = len(m.get("filename") or "")
            return (score, -ts_val, -name_len)

        members.sort(key=_best_key, reverse=True)
        ref = members[0]
        others = members[1:]
        ref_pid = ref["photo_id"]

        # Recompute similarity scores relative to the reference photo
        # (not the seed point), so scores reflect actual similarity to
        # the photo the user is keeping.
        ref_idx = ref.pop("_idx")
        ref["similarity_score"] = 1.0  # reference compared to itself
        for m in others:
            m_idx = m.pop("_idx")
            m["similarity_score"] = float(sim_matrix[ref_idx][m_idx])

        avg_sim = sum(m["similarity_score"] for m in others) / max(1, len(others))

        def _fmt_size(b):
            if b >= 1_000_000:
                return f"{b / 1_000_000:.2f} MB"
            return f"{b / 1_000:.1f} KB"

        ref_size = ref.get("file_size") or 0
        reasons = []
        if ref_size > 0 and others:
            other_sizes = [(m.get("file_size") or 0) for m in others]
            biggest_other = max(other_sizes)
            if ref_size == biggest_other:
                reasons.append(f"Identical file size: {_fmt_size(ref_size)}")
                ref_name = ref.get("filename", "")
                other_names = [m.get("filename", "") for m in others]
                has_copy_suffix = any("(" in n or "copy" in n.lower() for n in other_names)
                if has_copy_suffix and "(" not in ref_name and "copy" not in ref_name.lower():
                    reasons.append(f"Filename \"{ref_name}\" appears to be the original (others have copy suffixes)")
            elif ref_size > biggest_other:
                pct = ((ref_size - biggest_other) / biggest_other * 100) if biggest_other > 0 else 0
                reasons.append(f"Largest file: {_fmt_size(ref_size)} vs next {_fmt_size(biggest_other)} (+{pct:.0f}%)")
            else:
                reasons.append(f"File size: {_fmt_size(ref_size)} (a larger file exists at {_fmt_size(biggest_other)} but its format is less universal)")
        if ref.get("mime_type"):
            ref_fmt = ref["mime_type"]
            # Coerce None/missing to "?" — Photo.mime_type is nullable in
            # Postgres, and a mixed list of None and str crashes sorted().
            other_fmts = sorted({(m.get("mime_type") or "?") for m in others})
            is_preferred = ref_fmt in _preferred_types
            fmt_note = "preferred (universal)" if is_preferred else "less universal"
            reasons.append(f"Format: {ref_fmt} ({fmt_note}) — others: {', '.join(other_fmts)}")
        if ref.get("uploaded_at"):
            reasons.append(f"Scanned: {ref['uploaded_at'][:10]}")
        if not reasons:
            reasons.append("First in similarity ranking")

        groups.append({
            "group_id": f"grp-{ref_pid}",
            "similarity_score": avg_sim,
            "quality_score": 0.8,
            "reference_photo": ref,
            "similar_photos": others,
            "best_reasons": reasons,
        })
    return groups


@app.get("/similarity-groups")
async def list_similarity_groups(
    skip: int = 0,
    limit: int = 100,
    min_similarity: Optional[float] = None,
    min_quality: Optional[float] = None,
    sort_by: Optional[str] = None,
):
    """List similarity groups with pagination, filtering, and sorting."""
    # min_similarity is the clustering threshold: a pair appears together
    # iff cos(a,b) >= min_similarity. We do NOT additionally filter on the
    # group's avg-to-reference similarity afterwards — that would silently
    # drop legitimate clusters whose ref differs from the seed by ε.
    threshold = min_similarity if min_similarity is not None else 0.85
    groups = _build_similarity_groups_from_qdrant(threshold)

    if min_quality is not None:
        groups = [g for g in groups if g.get("quality_score", 0) >= min_quality]

    # Sort
    if sort_by is not None:
        if sort_by == "similarity":
            groups.sort(key=lambda g: g.get("similarity_score", 0), reverse=True)
        elif sort_by == "quality":
            groups.sort(key=lambda g: g.get("quality_score", 0), reverse=True)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}")

    total = len(groups)
    paged = groups[skip : skip + limit]
    return {"total": total, "skip": skip, "limit": limit, "groups": paged}


@app.get("/similarity-groups/{group_id}")
async def get_similarity_group_detail(group_id: str):
    """Get a similarity group by ID with thumbnail paths for each member."""
    group = similarity_group_service.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Group {group_id} not found")

    # Deep copy so we don't mutate the stored group
    import copy
    result = copy.deepcopy(group)

    for member in result.get("members", []):
        file_path = member.get("file_path")
        file_hash = member.get("file_hash")
        if file_path and file_hash:
            try:
                member["thumbnail"] = thumbnail_generator.get_thumbnail(file_path, file_hash)
            except Exception:
                member["thumbnail"] = None
        else:
            member["thumbnail"] = None

    return result


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
        except Exception:
            pass
