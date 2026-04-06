import os
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


@app.post("/deduplicate")
async def deduplicate_photos(request: Request):
    """Move selected photos to trash (delete from DB + Qdrant, keep files on disk)."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS
    body = await request.json()
    photo_ids = body.get("photo_ids", [])
    if not photo_ids:
        return JSONResponse(status_code=400, content={"error": "photo_ids is required"})

    session = job_queue_manager.SessionLocal()
    try:
        qdrant_point_ids = [
            pid for (pid,) in session.query(_Emb.qdrant_point_id)
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

        session.query(_Emb).filter(_Emb.photo_id.in_(photo_ids)).delete(synchronize_session=False)
        session.query(_PS).filter(_PS.photo_id.in_(photo_ids)).delete(synchronize_session=False)
        deleted = session.query(_Photo).filter(_Photo.id.in_(photo_ids)).delete(synchronize_session=False)
        session.commit()
        return {"deleted": deleted}
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
    supported = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"}
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


_BROWSER_NATIVE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


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


def _build_similarity_groups_from_qdrant(threshold: float):
    """Cluster Qdrant vectors into groups of similar photos using single-pass
    greedy grouping. For each unvisited point, ask Qdrant for neighbours above
    `threshold`; all of them form one group. O(N log N)-ish via Qdrant ANN.
    """
    from qdrant_client import QdrantClient
    qc = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    collection = "embeddings"

    # Pull all points (id + photo_id payload + vector)
    scroll_result, _ = qc.scroll(
        collection_name=collection, limit=10000, with_payload=True, with_vectors=True
    )
    points = list(scroll_result)
    if not points:
        return []

    # Map photo_id -> metadata for the response payload
    session = job_queue_manager.SessionLocal() if job_queue_manager else None
    filenames: Dict[int, str] = {}
    paths: Dict[int, str] = {}
    photo_meta: Dict[int, dict] = {}
    if session is not None:
        try:
            rows = session.query(
                Photo.id, Photo.filename, Photo.file_path,
                Photo.file_size, Photo.mime_type, Photo.uploaded_at
            ).all()
            for r in rows:
                filenames[r[0]] = r[1]
                paths[r[0]] = r[2]
                photo_meta[r[0]] = {
                    "file_size": r[3],
                    "file_path": r[2],
                    "mime_type": r[4],
                    "uploaded_at": r[5].isoformat() if r[5] else None,
                }
        finally:
            session.close()

    # Filter out stale vectors whose photo_id no longer exists in Postgres
    valid_photo_ids = set(filenames.keys())
    points = [p for p in points if int(p.payload.get("photo_id", 0)) in valid_photo_ids]

    visited = set()
    groups = []
    for p in points:
        if p.id in visited:
            continue
        # Find neighbours above threshold (Qdrant returns normalized cosine similarity)
        neighbours = qc.search(
            collection_name=collection,
            query_vector=p.vector,
            limit=50,
            score_threshold=threshold,
            with_payload=True,
        )
        members = []
        for n in neighbours:
            pid = int(n.payload.get("photo_id", 0))
            if pid not in valid_photo_ids:
                continue
            visited.add(n.id)
            meta = photo_meta.get(pid, {})
            members.append({
                "photo_id": pid,
                "filename": filenames.get(pid, str(pid)),
                "path": f"http://localhost:8000/thumbnails/{pid}",
                "similarity_score": float(n.score),
                "file_size": meta.get("file_size"),
                "file_path": meta.get("file_path"),
                "mime_type": meta.get("mime_type"),
                "uploaded_at": meta.get("uploaded_at"),
            })
        if len(members) < 2:
            continue  # lone point, not a group

        # Pick the best photo using a composite score:
        #   1. Format preference: JPEG/PNG (universal) > WebP/other
        #      A JPEG/PNG gets a bonus equivalent to 20% extra file size.
        #   2. File size (larger = more detail / less compression)
        #   3. Tie-break: earliest uploaded_at (likely the original)
        _preferred_types = {"image/jpeg", "image/png"}

        def _best_key(m):
            size = m.get("file_size") or 0
            fmt_bonus = int(size * 0.2) if m.get("mime_type") in _preferred_types else 0
            score = size + fmt_bonus
            # Tiebreakers (when score is identical):
            #   - earlier uploaded_at wins (likely the original file)
            #   - shorter filename wins ("file.jpg" beats "file (1).jpg")
            from datetime import datetime as _dt
            try:
                ts_val = _dt.fromisoformat(m["uploaded_at"]).timestamp() if m.get("uploaded_at") else 9e12
            except Exception:
                ts_val = 9e12
            name_len = len(m.get("filename") or "")
            return (score, -ts_val, -name_len)

        members.sort(key=_best_key, reverse=True)
        ref = members[0]
        others = members[1:]
        ref_pid = ref["photo_id"]
        avg_sim = sum(m["similarity_score"] for m in others) / max(1, len(others))

        # Build comparative reasoning
        def _fmt_size(b):
            if b >= 1_000_000:
                return f"{b / 1_000_000:.2f} MB"
            return f"{b / 1_000:.1f} KB"

        ref_size = ref.get("file_size") or 0
        reasons = []
        # Size comparison
        if ref_size > 0 and others:
            other_sizes = [(m.get("file_size") or 0) for m in others]
            biggest_other = max(other_sizes)
            if ref_size == biggest_other:
                reasons.append(f"Identical file size: {_fmt_size(ref_size)}")
                # Explain why this one won the tiebreak
                ref_name = ref.get("filename", "")
                other_names = [m.get("filename", "") for m in others]
                has_copy_suffix = any("(" in n or "copy" in n.lower() for n in other_names)
                if has_copy_suffix and "(" not in ref_name and "copy" not in ref_name.lower():
                    reasons.append(f"Filename \"{ref_name}\" appears to be the original (others have copy suffixes)")
            elif ref_size > biggest_other:
                pct = ((ref_size - biggest_other) / biggest_other * 100) if biggest_other > 0 else 0
                reasons.append(
                    f"Largest file: {_fmt_size(ref_size)} vs next {_fmt_size(biggest_other)} (+{pct:.0f}%)"
                )
            else:
                reasons.append(f"File size: {_fmt_size(ref_size)} (a larger file exists at {_fmt_size(biggest_other)} but its format is less universal)")
        # Format comparison
        if ref.get("mime_type"):
            ref_fmt = ref["mime_type"]
            other_fmts = sorted(set(m.get("mime_type", "?") for m in others))
            is_preferred = ref_fmt in _preferred_types
            fmt_note = "preferred (universal)" if is_preferred else "less universal"
            reasons.append(f"Format: {ref_fmt} ({fmt_note}) — others: {', '.join(other_fmts)}")
        # Date
        if ref.get("uploaded_at"):
            reasons.append(f"Scanned: {ref['uploaded_at'][:10]}")
        if not reasons:
            reasons.append("First in similarity ranking")

        groups.append({
            "group_id": f"grp-{ref_pid}",
            "similarity_score": avg_sim,
            "quality_score": 0.8,
            "reference_photo": ref,  # full metadata included
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
    # Compute groups live from Qdrant at the requested threshold
    threshold = min_similarity if min_similarity is not None else 0.85
    groups = _build_similarity_groups_from_qdrant(threshold)

    # Apply filters
    if min_similarity is not None:
        groups = [g for g in groups if g.get("similarity_score", 0) >= min_similarity]
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
