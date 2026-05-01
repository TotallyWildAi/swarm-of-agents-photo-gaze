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
    """Return high-level processing stats for the UI progress panel.
    Includes similarity_index sub-object so the UI can render
    "groups updated 12s ago" instead of guessing."""
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
            "similarity_index": dict(_sim_index_info),
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


# Mime types we prefer to keep when ranking duplicates (universally
# decodable across viewers and OSes). Lifted to module scope so the
# auto-deduplicate planner can reuse the same ranking the per-group
# clustering uses.
_PREFERRED_MIME_TYPES = {"image/jpeg", "image/png"}


def _best_key(m: dict):
    """Sort key for picking the best (highest-quality, most-likely-original)
    photo in a duplicate group. Higher key = better.

    Primary signal: file size + 20% bonus for preferred (universal) formats.
    Tiebreakers: earlier upload (likely the original), then shorter filename
    ("photo.jpg" beats "photo (1).jpg").
    """
    size = m.get("file_size") or 0
    fmt_bonus = int(size * 0.2) if m.get("mime_type") in _PREFERRED_MIME_TYPES else 0
    score = size + fmt_bonus
    try:
        ts_val = (datetime.fromisoformat(m["uploaded_at"]).timestamp()
                  if m.get("uploaded_at") else 9e12)
    except Exception:
        ts_val = 9e12
    name_len = len(m.get("filename") or "")
    return (score, -ts_val, -name_len)


def _read_manifest(path: str):
    """Read a trash manifest. Returns [] on any failure (corrupt file,
    missing, partial write). Caller decides whether to log."""
    try:
        with open(path) as f:
            data = __import__("json").load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_manifest(path: str, entries: list) -> None:
    import json as _json
    with open(path, "w") as f:
        _json.dump(entries, f, indent=2)


def _is_inside_trash(candidate: str) -> bool:
    """Reject any path that resolves outside TRASH_DIR. Defends the
    recover endpoint against caller-supplied paths that try to move
    arbitrary files via path traversal."""
    trash_abs = os.path.realpath(os.path.abspath(TRASH_DIR))
    abs_candidate = os.path.realpath(os.path.abspath(candidate))
    return abs_candidate == trash_abs or abs_candidate.startswith(trash_abs + os.sep)


@app.get("/trash")
async def list_trash():
    """List every photo currently in the dedupe trash with the original
    path it would be restored to. The UI uses this to render the recovery
    page; each item carries `trash_path` as a stable identifier the
    /trash/recover endpoint expects.

    Skips manifest entries whose trash file no longer exists on disk
    (e.g. user emptied Finder's Trash manually) — they're invisible from
    the UI's perspective and silently pruned on the next recover call.
    """
    items = []
    if not os.path.isdir(TRASH_DIR):
        return {"items": items, "trash_dir": TRASH_DIR}

    for name in sorted(os.listdir(TRASH_DIR)):
        if not name.endswith("_manifest.json"):
            continue
        manifest_path = os.path.join(TRASH_DIR, name)
        ts = name[: -len("_manifest.json")]   # "20260501_120000"
        for entry in _read_manifest(manifest_path):
            trash_path = entry.get("trash")
            original = entry.get("original")
            if not trash_path or not os.path.isfile(trash_path):
                continue  # file gone: skip — recover can't help anyway
            items.append({
                "trash_path": trash_path,
                "original_path": original,
                "filename": os.path.basename(original or trash_path),
                "trashed_at": ts,
                "file_size": os.path.getsize(trash_path),
            })
    return {"items": items, "trash_dir": TRASH_DIR}


def _restore_db_and_qdrant_from_snapshot(session, qdrant_client, entry: dict) -> dict:
    """Recreate Photo + ProcessingState + Embedding rows + Qdrant point
    from a v2 manifest entry. Returns a status dict the recover endpoint
    surfaces back to the caller.

    Behavior:
      - v1 (legacy) entries with no "photo" snapshot are a no-op here;
        the caller will rely on the next folder rescan to re-ingest.
      - If a Photo with the same file_path already exists in DB
        (re-imported from elsewhere) we skip DB writes — the file move
        already did the user-visible work.
      - Vector dimension mismatch: skip the Qdrant upsert but still
        rewrite the Photo + ProcessingState rows. Embedding row is
        skipped since it'd be referentially broken.
      - Each step is independently catch-and-warn so a partial failure
        (e.g. Qdrant down) doesn't roll back the file move.
    """
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS

    photo_snap = entry.get("photo")
    if not photo_snap:
        return {"db_restored": False, "reason": "legacy_v1_entry"}

    fp = photo_snap.get("file_path")
    if not fp:
        return {"db_restored": False, "reason": "snapshot_missing_file_path"}

    # Idempotency: if a row for this file_path already exists, don't touch.
    existing = session.query(_Photo).filter(_Photo.file_path == fp).first()
    if existing is not None:
        return {"db_restored": False, "reason": "photo_row_already_exists",
                "existing_photo_id": existing.id}

    def _parse(ts):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    new_photo = _Photo(
        filename=photo_snap.get("filename") or os.path.basename(fp),
        file_path=fp,
        file_size=photo_snap.get("file_size") or 0,
        mime_type=photo_snap.get("mime_type") or "image/unknown",
        file_hash=photo_snap.get("file_hash"),
        uploaded_at=_parse(photo_snap.get("uploaded_at")) or datetime.utcnow(),
        user_id=photo_snap.get("user_id"),
    )
    session.add(new_photo)
    session.flush()  # populate new_photo.id without committing yet

    ps_snap = entry.get("processing_state") or {}
    session.add(_PS(
        photo_id=new_photo.id,
        status=ps_snap.get("status") or "completed",
        extraction_status=ps_snap.get("extraction_status") or "completed",
        embedding_status=ps_snap.get("embedding_status") or "completed",
        error_message=ps_snap.get("error_message"),
        started_at=_parse(ps_snap.get("started_at")),
        completed_at=_parse(ps_snap.get("completed_at")),
    ))

    emb_snap = entry.get("embedding") or {}
    vector = emb_snap.get("vector")
    new_point_id = None
    qdrant_upserted = False
    if vector and qdrant_client is not None:
        from qdrant_client.http.models import PointStruct
        import uuid as _uuid
        new_point_id = str(_uuid.uuid4())
        try:
            qdrant_client.upsert(
                collection_name="embeddings",
                points=[PointStruct(
                    id=new_point_id,
                    vector=list(vector),
                    payload={"photo_id": new_photo.id},
                )],
            )
            qdrant_upserted = True
        except Exception as e:
            logger.warning(
                "Qdrant upsert failed during recovery (photo %s): %s. "
                "Photo + ProcessingState rows still restored; the next "
                "scan will rebuild the embedding.",
                new_photo.id, e,
            )
            new_point_id = None

    session.add(_Emb(
        photo_id=new_photo.id,
        embedding_model=emb_snap.get("embedding_model") or "dinov2_vits14",
        vector_dimension=emb_snap.get("vector_dimension") or (len(vector) if vector else 384),
        qdrant_point_id=new_point_id,
    ))

    return {
        "db_restored": True,
        "photo_id": new_photo.id,
        "qdrant_upserted": qdrant_upserted,
    }


@app.post("/trash/recover")
async def recover_from_trash(request: Request):
    """Move selected photos back from trash to their original paths and
    rebuild Postgres + Qdrant from the manifest snapshot, so the photo
    is back in the index immediately — no rescan, no re-embedding.

    Backward compatibility: v1 manifest entries (file-only) still
    recover the file; their DB/Qdrant state is rebuilt by the next
    folder rescan exactly as before.

    Path-traversal-defended: every trash_path is rejected if it doesn't
    resolve under TRASH_DIR before any file or DB write.
    """
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})

    body = await request.json()
    trash_paths = body.get("trash_paths", [])
    if not trash_paths:
        return JSONResponse(status_code=400, content={"error": "trash_paths is required"})

    import shutil

    requested_abs: set = set()
    errors: list = []
    for tp in trash_paths:
        if not _is_inside_trash(tp):
            errors.append({"trash_path": tp, "error": "not inside trash directory"})
            continue
        requested_abs.add(os.path.realpath(os.path.abspath(tp)))

    recovered: list = []
    if not os.path.isdir(TRASH_DIR):
        return {"recovered": 0, "items": [], "errors": errors or None}

    qc = job_queue_manager.qdrant_client
    session = job_queue_manager.SessionLocal()
    db_dirty = False
    try:
        for name in sorted(os.listdir(TRASH_DIR)):
            if not name.endswith("_manifest.json"):
                continue
            manifest_path = os.path.join(TRASH_DIR, name)
            entries = _read_manifest(manifest_path)
            if not entries:
                continue
            kept: list = []
            changed = False
            for entry in entries:
                trash_path = entry.get("trash")
                trash_abs = (os.path.realpath(os.path.abspath(trash_path))
                             if trash_path else None)
                if trash_abs not in requested_abs:
                    kept.append(entry)
                    continue

                original = entry.get("original")
                if not trash_path or not os.path.isfile(trash_path):
                    errors.append({"trash_path": trash_path, "error": "file missing"})
                    changed = True
                    continue
                if not original:
                    errors.append({"trash_path": trash_path,
                                   "error": "no original path recorded"})
                    kept.append(entry)
                    continue
                if os.path.exists(original):
                    errors.append({
                        "trash_path": trash_path,
                        "error": f"a file already exists at {original}",
                    })
                    kept.append(entry)
                    continue

                # 1) Move file back.
                try:
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    shutil.move(trash_path, original)
                except Exception as e:
                    errors.append({"trash_path": trash_path, "error": str(e)})
                    kept.append(entry)
                    continue

                # 2) Rebuild DB + Qdrant from the snapshot. v1 entries are
                # a no-op; their state is rebuilt by the next folder rescan.
                try:
                    db_status = _restore_db_and_qdrant_from_snapshot(
                        session, qc, entry
                    )
                    if db_status.get("db_restored"):
                        db_dirty = True
                except Exception as e:
                    logger.error(
                        "Snapshot-based DB restore failed for %s: %s. "
                        "File is back on disk; rescan will re-ingest.",
                        original, e,
                    )
                    db_status = {"db_restored": False, "reason": "exception"}

                recovered.append({
                    "trash_path": trash_path,
                    "restored_to": original,
                    **db_status,
                })
                changed = True

            if not changed:
                continue
            if kept:
                _write_manifest(manifest_path, kept)
            else:
                try:
                    os.remove(manifest_path)
                except OSError as e:
                    logger.warning("Could not remove empty manifest %s: %s",
                                   manifest_path, e)

        if db_dirty:
            session.commit()
    finally:
        session.close()

    if db_dirty:
        # Refresh similarity index so the recovered photos show up in
        # /similarity-groups without waiting for the debounce.
        await _recompute_sim_cache()

    return {
        "recovered": len(recovered),
        "items": recovered,
        "errors": errors or None,
    }


# Trash manifest schema versions:
#   1 — legacy: {photo_id, original, trash}. File-only recovery.
#   2 — full snapshot: above + {photo, processing_state, embedding{vector}}.
#       Recovery rebuilds the Postgres rows AND the Qdrant point WITHOUT
#       re-running DINOv2 or re-extracting metadata. Saves ~1–2s per
#       photo on recovery (a v2 manifest entry is ~6 KB; for thousands
#       of photos this adds tens of MB to the trash dir, which is fine).
TRASH_MANIFEST_SCHEMA = 2


def _capture_photo_snapshot(session, qdrant_client, photo_id: int) -> dict:
    """Build the v2 snapshot for a photo BEFORE its rows are deleted.

    Pulls Photo, ProcessingState, and Embedding rows and the actual vector
    from Qdrant. Each missing piece falls through to None so a partially-
    ingested photo can still be trashed and recovered to whatever state it
    had. Pure read; no writes.
    """
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS

    snap: dict = {}

    p = session.query(_Photo).filter(_Photo.id == photo_id).first()
    if p:
        snap["photo"] = {
            "filename": p.filename,
            "file_path": p.file_path,
            "file_size": p.file_size,
            "mime_type": p.mime_type,
            "file_hash": p.file_hash,
            "uploaded_at": p.uploaded_at.isoformat() if p.uploaded_at else None,
            "user_id": p.user_id,
        }

    ps = session.query(_PS).filter(_PS.photo_id == photo_id).first()
    if ps:
        snap["processing_state"] = {
            "status": ps.status,
            "extraction_status": ps.extraction_status,
            "embedding_status": ps.embedding_status,
            "error_message": ps.error_message,
            "started_at": ps.started_at.isoformat() if ps.started_at else None,
            "completed_at": ps.completed_at.isoformat() if ps.completed_at else None,
        }

    emb = session.query(_Emb).filter(_Emb.photo_id == photo_id).first()
    if emb:
        emb_snap = {
            "embedding_model": emb.embedding_model,
            "vector_dimension": emb.vector_dimension,
            "vector": None,
        }
        # Pull the actual vector — without it, recovery has to re-embed.
        if emb.qdrant_point_id and qdrant_client is not None:
            try:
                records = qdrant_client.retrieve(
                    collection_name="embeddings",
                    ids=[emb.qdrant_point_id],
                    with_vectors=True,
                )
                if records and records[0].vector is not None:
                    # Coerce to plain Python floats — JSON can't serialize
                    # numpy / float32 directly.
                    emb_snap["vector"] = [float(x) for x in records[0].vector]
            except Exception as e:
                logger.warning(
                    "Qdrant retrieve failed for point %s (photo %d); "
                    "snapshot will lack vector: %s",
                    emb.qdrant_point_id, photo_id, e,
                )
        snap["embedding"] = emb_snap

    return snap


async def _execute_dedupe(session, photo_ids: list) -> dict:
    """Snapshot + move the listed photos to trash, write a v2 manifest,
    delete from Qdrant + Postgres, and refresh the similarity index.
    Returns a dict matching the legacy /deduplicate response shape.

    The snapshot phase happens BEFORE deletion so recovery doesn't have
    to re-run DINOv2 or re-extract metadata — see _capture_photo_snapshot.

    Shared between /deduplicate (manual) and /auto-deduplicate (sweep).
    """
    from app.models import Photo as _Photo, Embedding as _Emb, ProcessingState as _PS
    import shutil

    qc = job_queue_manager.qdrant_client if job_queue_manager else None

    photos = session.query(_Photo).filter(_Photo.id.in_(photo_ids)).all()
    file_paths = {p.id: p.file_path for p in photos}

    # Capture full snapshots BEFORE any deletion, so even if the file move
    # below fails, the source-of-truth rows are still on disk + DB.
    snapshots: dict = {pid: _capture_photo_snapshot(session, qc, pid)
                       for pid in photo_ids}

    os.makedirs(TRASH_DIR, exist_ok=True)
    moved_entries = []
    move_errors = []
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    # Track which photo_ids it's safe to purge from the DB / Qdrant.
    # SUCCESS: file moved into trash. SAFE_PURGE.
    # MISSING: file already gone from disk. SAFE_PURGE (cleanup orphan).
    # MOVE_FAILED: file still at original path. DO NOT PURGE — otherwise
    # the user is left with a file on disk and no DB/index record AND no
    # manifest entry to recover from. We surface the per-photo error
    # and let the caller retry.
    ids_to_purge: list = []
    for pid, src in file_paths.items():
        if not src or not os.path.isfile(src):
            ids_to_purge.append(pid)  # nothing left on disk → clean DB rows
            continue
        basename = os.path.basename(src)
        dest = os.path.join(TRASH_DIR, f"{ts}_{pid}_{basename}")
        try:
            shutil.move(src, dest)
            moved_entries.append({
                "schema_version": TRASH_MANIFEST_SCHEMA,
                "photo_id": pid,
                "original": src,
                "trash": dest,
                "trashed_at": datetime.utcnow().isoformat(),
                **snapshots.get(pid, {}),
            })
            ids_to_purge.append(pid)
        except Exception as e:
            move_errors.append({"photo_id": pid, "error": str(e)})

    if moved_entries:
        import json as _json
        manifest_path = os.path.join(TRASH_DIR, f"{ts}_manifest.json")
        existing = []
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                existing = _json.load(f)
        existing.extend(moved_entries)
        with open(manifest_path, "w") as f:
            _json.dump(existing, f, indent=2)

    if not ids_to_purge:
        # Nothing was successfully moved AND nothing was already missing —
        # leave the DB / Qdrant / index alone.
        return {
            "deleted": 0,
            "moved_to_trash": 0,
            "trash_dir": TRASH_DIR,
            "errors": move_errors if move_errors else None,
        }

    qdrant_point_ids = [
        qid for (qid,) in session.query(_Emb.qdrant_point_id)
        .filter(_Emb.photo_id.in_(ids_to_purge))
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

    session.query(_Emb).filter(_Emb.photo_id.in_(ids_to_purge)).delete(synchronize_session=False)
    session.query(_PS).filter(_PS.photo_id.in_(ids_to_purge)).delete(synchronize_session=False)
    deleted = session.query(_Photo).filter(_Photo.id.in_(ids_to_purge)).delete(synchronize_session=False)
    session.commit()

    await _recompute_sim_cache()

    return {
        "deleted": deleted,
        "moved_to_trash": len(moved_entries),
        "trash_dir": TRASH_DIR,
        "errors": move_errors if move_errors else None,
    }


@app.post("/deduplicate")
async def deduplicate_photos(request: Request):
    """Move selected photos to ${TRASH_DIR} and remove from DB + Qdrant."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})

    body = await request.json()
    photo_ids = body.get("photo_ids", [])
    if not photo_ids:
        return JSONResponse(status_code=400, content={"error": "photo_ids is required"})

    session = job_queue_manager.SessionLocal()
    try:
        return await _execute_dedupe(session, photo_ids)
    finally:
        session.close()


def _is_under(child: str, parent_abs: str) -> bool:
    """True iff `child` (after realpath) equals `parent_abs` or is strictly
    inside it. parent_abs must already be a realpath. Uses the trailing-
    separator trick so /a/bc is NOT considered inside /a/b."""
    if not child:
        return False
    try:
        child_abs = os.path.realpath(os.path.abspath(child))
    except OSError:
        return False
    if child_abs == parent_abs:
        return True
    return child_abs.startswith(parent_abs.rstrip(os.sep) + os.sep)


def _plan_auto_dedupe(threshold: float, keep_folder: str) -> dict:
    """Build the action plan for an auto-dedupe sweep.

    User-stated intent for the threshold=1.0 sweep is "keep all pure
    duplicates already inside `keep_folder`; delete the duplicates of
    these in OTHER locations." That means:

      - For each photo in `keep_folder`, find ALL its duplicates above
        the threshold — including duplicates reached transitively
        through the duplicate graph. Outsiders (members of that
        connected component that are NOT in keep_folder) are deleted.
        In-keep members are all kept.
      - Connected components with NO member in keep_folder → skipped
        (we never make a destructive choice without an explicit
        anchor).
      - Components fully inside keep_folder → no-op (nothing to delete;
        the user said "keep all" inside this folder).

    Why connected components and not greedy single-link clustering:
    Qdrant's HNSW + top_k limit can produce asymmetric adjacency, and
    greedy iteration is order-dependent. With greedy, an outsider
    duplicate of an in-keep photo can be missed if its only neighbours
    were "visited" by a prior cluster. BFS through the adjacency
    catches every transitive duplicate of an in-keep anchor. See the
    regression tests test_outsider_pure_duplicate_missed_via_asymmetric_adjacency
    and test_chain_of_duplicates_outside_keep_all_deleted.

    Returns:
        {
          "groups_processed": int,    # components with deletions
          "groups_skipped": int,      # components with no in-keep anchor
          "to_delete": [photo_id...],
          "kept": [photo_id...],
          "groups": [
            {"kept_ids": [...], "kept_paths": [...],
             "delete_ids": [...], "delete_paths": [...]}
          ],
        }
    """
    EMPTY_PLAN = {
        "groups_processed": 0, "groups_skipped": 0,
        "to_delete": [], "kept": [], "groups": [],
    }

    if threshold > 1.0:
        return EMPTY_PLAN

    cache_data, photo_meta = _get_cached_data()
    if cache_data is None:
        return EMPTY_PLAN

    photo_ids = cache_data["photo_ids"]
    adjacency = cache_data["adjacency"]
    cache_floor = cache_data.get("cache_threshold", _SIM_CACHE_THRESHOLD)
    if threshold >= 1.0:
        # See _PURE_DUPE_EPSILON: float32 normalize-then-dot returns
        # ~0.9999998 for byte-identical photos. Without this slack a
        # strict s >= 1.0 filter would drop the very pairs we're after.
        threshold = 1.0 - _PURE_DUPE_EPSILON
    effective_threshold = max(threshold, cache_floor)
    keep_abs = os.path.realpath(os.path.abspath(keep_folder))
    n = len(photo_ids)

    # Pre-compute which indices are inside the keep folder.
    in_keep_idx: set = set()
    for idx, pid in enumerate(photo_ids):
        meta = photo_meta.get(pid, {}) if photo_meta else {}
        if _is_under(meta.get("file_path") or "", keep_abs):
            in_keep_idx.add(idx)

    def _component(seed: int) -> set:
        """BFS from `seed` over edges with score >= effective_threshold.
        Returns the set of indices in the connected component."""
        seen = {seed}
        queue = [seed]
        while queue:
            cur = queue.pop()
            for j, s in adjacency[cur]:
                if s >= effective_threshold and j not in seen:
                    seen.add(j)
                    queue.append(j)
        return seen

    plan_groups: list = []
    to_delete: list = []
    kept: list = []
    processed: set = set()

    # First pass: process every component anchored in the keep folder.
    # Iterating in deterministic order keeps the response reproducible.
    for i in sorted(in_keep_idx):
        if i in processed:
            continue
        component = _component(i)
        processed.update(component)
        if len(component) < 2:
            continue
        in_comp = [k for k in component if k in in_keep_idx]
        out_comp = [k for k in component if k not in in_keep_idx]
        if not out_comp:
            # Whole component lives inside keep folder → no-op.
            continue
        # Order kept members by _best_key purely for display determinism.
        kept_meta = sorted(
            [{"photo_id": photo_ids[k], **(photo_meta.get(photo_ids[k]) or {})}
             for k in in_comp],
            key=_best_key, reverse=True,
        )
        delete_meta = [
            {"photo_id": photo_ids[k], **(photo_meta.get(photo_ids[k]) or {})}
            for k in out_comp
        ]
        plan_groups.append({
            "kept_ids":     [m["photo_id"] for m in kept_meta],
            "kept_paths":   [m.get("file_path") for m in kept_meta],
            "delete_ids":   [m["photo_id"] for m in delete_meta],
            "delete_paths": [m.get("file_path") for m in delete_meta],
        })
        kept.extend(m["photo_id"] for m in kept_meta)
        to_delete.extend(m["photo_id"] for m in delete_meta)

    # Second pass: count outsider components (no member in keep folder)
    # so the UI can report "X groups skipped — they have no anchor in
    # your keep folder". Singletons are not real clusters and don't
    # contribute to the count.
    skipped = 0
    for i in range(n):
        if i in processed:
            continue
        component = _component(i)
        processed.update(component)
        if len(component) < 2:
            continue
        skipped += 1

    return {
        "groups_processed": len(plan_groups),
        "groups_skipped": skipped,
        "to_delete": to_delete,
        "kept": kept,
        "groups": plan_groups,
    }


@app.post("/auto-deduplicate")
async def auto_deduplicate(request: Request):
    """Sweep all near-perfect duplicate groups and keep one copy in the
    user-selected folder, deleting the rest.

    Body: {
        "folder_path": str (required) — the folder where the kept copy
                       must live. Photos in OTHER folders that match
                       a cluster anchored here are deleted; duplicates
                       within this folder are reduced to one.
        "threshold":   float (default 1.0) — cluster inclusion floor.
                       1.0 = only pure-duplicate clusters; lower values
                       widen to near-duplicates.
        "dry_run":     bool (default false) — when true, returns the
                       plan without touching files / DB / Qdrant. The
                       UI uses this for the confirmation dialog.
    }
    """
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})

    body = await request.json()
    folder_path = (body.get("folder_path") or "").strip()
    threshold = float(body.get("threshold", 1.0))
    dry_run = bool(body.get("dry_run", False))

    if not folder_path:
        return JSONResponse(status_code=400, content={"error": "folder_path is required"})
    if not os.path.isdir(folder_path):
        return JSONResponse(status_code=400, content={
            "error": f"folder_path is not a directory: {folder_path}",
        })
    if threshold > 1.0 or threshold <= 0.0:
        return JSONResponse(status_code=400, content={
            "error": f"threshold must be in (0, 1], got {threshold}",
        })
    # Reject the trash directory itself — keeping duplicates "in the trash"
    # is incoherent (next scan won't see them anyway).
    trash_abs = os.path.realpath(os.path.abspath(TRASH_DIR))
    candidate_abs = os.path.realpath(os.path.abspath(folder_path))
    if candidate_abs == trash_abs or candidate_abs.startswith(trash_abs + os.sep):
        return JSONResponse(status_code=400, content={
            "error": "folder_path cannot be inside the trash directory",
        })

    plan = _plan_auto_dedupe(threshold, folder_path)

    # Execute or short-circuit. Either way the response shape is the
    # same — same keys whether dry_run, empty plan, or real execute.
    if dry_run or not plan["to_delete"]:
        result = {"deleted": 0, "moved_to_trash": 0, "errors": None}
    else:
        session = job_queue_manager.SessionLocal()
        try:
            result = await _execute_dedupe(session, plan["to_delete"])
        finally:
            session.close()

    return {
        "dry_run": dry_run,
        "threshold": threshold,
        "folder_path": folder_path,
        "groups_processed": plan["groups_processed"],
        "groups_skipped": plan["groups_skipped"],
        "kept": plan["kept"],
        "to_delete": plan["to_delete"],
        "groups": plan["groups"],
        "deleted": result.get("deleted", 0),
        "moved_to_trash": result.get("moved_to_trash", 0),
        "errors": result.get("errors"),
    }


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
    """Register a new folder to scan. Validates accessibility server-side
    AND refuses to register the trash directory (or any path inside it) —
    indexing the trash would re-ingest just-deleted duplicates."""
    if job_queue_manager is None:
        return JSONResponse(status_code=503, content={"error": "Service not initialized"})
    from app.models import FolderPath
    body = await request.json()
    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse(status_code=400, content={"error": "path is required"})

    # Reject the trash directory and any subpath of it.
    trash_abs = os.path.realpath(os.path.abspath(TRASH_DIR))
    candidate_abs = os.path.realpath(os.path.abspath(path))
    if candidate_abs == trash_abs or candidate_abs.startswith(trash_abs + os.sep):
        return JSONResponse(status_code=400, content={
            "error": "Cannot register a path inside the trash directory",
            "trash_dir": TRASH_DIR,
        })

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


# --------------- Event-driven similarity index cache ---------------
#
# Built once eagerly at startup, then refreshed on changes:
#   - Additions: job_queue calls notify_embeddings_changed() after upsert.
#     A debounce coalesces rapid additions into a single recompute that
#     fires 60s after the LAST change in the photo collection — the UI
#     sees fresh groupings within a minute of the scan going idle, without
#     paying for a recompute per photo during a long batch.
#   - Deletions: deduplicate / folder-delete call _recompute_sim_cache()
#     immediately so the UI reflects user-driven removals right away.
#
# The cache is a SPARSE ADJACENCY index, NOT a dense N×N cosine matrix.
# At 60k photos a dense matrix is 14.4 GB; the adjacency stores only
# pairs above _SIM_CACHE_THRESHOLD (typically 0.7), which on real photo
# collections is ~20 edges per photo → a few MB. Vectors are kept too
# (60k × 384 × 4 ≈ 92 MB) so reference-vs-member scoring stays exact
# even on the rare edge that wasn't above the cache floor.

_sim_cache: Dict[str, object] = {"data": None, "meta": None}
_sim_debounce_handle: Optional[asyncio.TimerHandle] = None
_sim_recompute_lock: Optional[asyncio.Lock] = None
_SIM_DEBOUNCE_SECONDS = 60.0
_SIM_SCROLL_PAGE = 2000          # Qdrant scroll page size
_SIM_CACHE_THRESHOLD = 0.70      # adjacency floor; UI thresholds are >= this
_SIM_TOP_K = 100                 # max neighbours stored per photo
_SIM_SEARCH_BATCH = 256          # Qdrant search_batch size

# Observability fields exposed via /stats.
_sim_index_info: Dict[str, object] = {
    "last_recompute_at": None,
    "last_recompute_duration_ms": None,
    "recompute_running": False,
    "vectors_in_index": 0,
    "edges_in_index": 0,
    "cache_threshold": _SIM_CACHE_THRESHOLD,
}


def _get_recompute_lock() -> asyncio.Lock:
    """Lazy-construct the lock against the running loop. A module-level
    Lock would bind to whichever loop happened to be current at import
    time, which breaks under TestClient (one loop per request)."""
    global _sim_recompute_lock
    if _sim_recompute_lock is None:
        _sim_recompute_lock = asyncio.Lock()
    return _sim_recompute_lock


def _compute_sim_cache():
    """Synchronous: scroll Qdrant, query Postgres, build a SPARSE adjacency
    of (i, j, score) triples for all pairs above _SIM_CACHE_THRESHOLD.

    Returns (cache_data, photo_meta) or (None, None). cache_data shape:
        {
          "vectors":      np.ndarray (N, D), unit-normalized,
          "photo_ids":    [int],     index i -> photo_id
          "point_ids":    [str],     index i -> Qdrant point id
          "adjacency":    [[(j, score), ...]] of length N,
          "cache_threshold": float,  the floor at which adjacency was built
        }

    Memory at 60k photos with ~20 neighbours each: ~92 MB vectors + ~10 MB
    edges, vs 14.4 GB for the previous dense matrix. Time at 60k photos
    via Qdrant search_batch (HNSW, sub-linear per query) is seconds, not
    minutes.
    """
    qc = job_queue_manager.qdrant_client if job_queue_manager else None
    if qc is None:
        return None, None
    collection = "embeddings"

    # 1) Scroll all points (paginated — no silent truncation).
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

    # 2) Load photo metadata from Postgres.
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

    # 3) Drop Qdrant points whose Postgres row is gone (orphaned vectors).
    valid_ids = set(photo_meta.keys())
    filtered = [(p, int(p.payload.get("photo_id", 0))) for p in points
                if int(p.payload.get("photo_id", 0)) in valid_ids]
    if not filtered:
        return None, None

    point_ids = [p.id for p, _ in filtered]
    photo_ids = [pid for _, pid in filtered]
    raw_vecs = np.array([p.vector for p, _ in filtered], dtype=np.float32)
    norms = np.linalg.norm(raw_vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = raw_vecs / norms
    n = len(photo_ids)

    # 4) Build sparse adjacency. Use Qdrant's batched HNSW search to find
    # each vector's near-neighbours above the cache threshold.
    pid_to_idx = {pid: i for i, pid in enumerate(photo_ids)}
    adjacency: list = [[] for _ in range(n)]

    # Qdrant's SearchRequest model lives under qdrant_client.http.models.
    # Import lazily so unit tests with a fake client don't pay the import.
    from qdrant_client.http.models import SearchRequest

    for batch_start in range(0, n, _SIM_SEARCH_BATCH):
        batch_end = min(batch_start + _SIM_SEARCH_BATCH, n)
        requests = [
            SearchRequest(
                vector=vecs[i].tolist(),
                limit=_SIM_TOP_K + 1,  # +1 to absorb the self-hit
                score_threshold=_SIM_CACHE_THRESHOLD,
                with_payload=True,
            )
            for i in range(batch_start, batch_end)
        ]
        results = qc.search_batch(collection_name=collection, requests=requests)
        for offset, hits in enumerate(results):
            i = batch_start + offset
            for hit in hits:
                hit_pid = int(hit.payload.get("photo_id", 0)) if hit.payload else 0
                j = pid_to_idx.get(hit_pid)
                if j is None or j == i:
                    continue
                adjacency[i].append((j, float(hit.score)))

    cache_data = {
        "vectors": vecs,
        "photo_ids": photo_ids,
        "point_ids": point_ids,
        "adjacency": adjacency,
        "cache_threshold": _SIM_CACHE_THRESHOLD,
    }
    return cache_data, photo_meta


async def _recompute_sim_cache():
    """Recompute the sparse index (heavy work in a thread) and update the
    cache. Lock-guarded so concurrent triggers (debounce + delete) don't
    stomp; updates _sim_index_info for /stats observability."""
    async with _get_recompute_lock():
        loop = asyncio.get_running_loop()
        _sim_index_info["recompute_running"] = True
        t0 = time.time()
        try:
            cache_data, photo_meta = await loop.run_in_executor(None, _compute_sim_cache)
            _sim_cache.update(data=cache_data, meta=photo_meta)
            n_vecs = len(cache_data["photo_ids"]) if cache_data else 0
            n_edges = sum(len(adj) for adj in cache_data["adjacency"]) if cache_data else 0
            _sim_index_info.update(
                last_recompute_at=datetime.utcnow().isoformat(),
                last_recompute_duration_ms=int((time.time() - t0) * 1000),
                vectors_in_index=n_vecs,
                edges_in_index=n_edges,
            )
            logger.info(
                "Similarity index recomputed: %d vectors, %d edges, %dms",
                n_vecs, n_edges, _sim_index_info["last_recompute_duration_ms"],
            )
        finally:
            _sim_index_info["recompute_running"] = False


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


_PURE_DUPE_EPSILON = 1e-4  # float32 normalize-then-dot noise floor


def _build_similarity_groups_from_qdrant(threshold: float):
    """Cluster photos into groups of similars from the sparse adjacency cache.
    Reads the precomputed adjacency in O(edges), no Qdrant calls per request.

    Threshold handling:
      - threshold > 1.0 returns no groups (no cosine exceeds 1.0 — defends
        against off-by-one slider bugs).
      - At threshold ≥ 1.0 the effective filter drops by _PURE_DUPE_EPSILON.
        Reason: two byte-identical photos give the same DINOv2 vector, but
        float32 normalize-then-dot returns ~0.9999998, not exactly 1.0. A
        strict s >= 1.0 filter would silently exclude the very pairs the
        user is asking for when they slide to "pure duplicates".
      - threshold < cache_floor is clamped up to the cache floor — the
        adjacency wasn't built with those edges.
    """
    if threshold > 1.0:
        return []

    cache_data, photo_meta = _get_cached_data()
    if cache_data is None:
        return []

    vectors = cache_data["vectors"]
    photo_ids = cache_data["photo_ids"]
    adjacency = cache_data["adjacency"]
    cache_floor = cache_data.get("cache_threshold", _SIM_CACHE_THRESHOLD)
    if threshold >= 1.0:
        threshold = 1.0 - _PURE_DUPE_EPSILON
    effective_threshold = max(threshold, cache_floor)
    n = len(photo_ids)

    visited = set()
    groups = []

    for i in range(n):
        if i in visited:
            continue
        # Filter the precomputed neighbours of i down to the effective threshold.
        seed_neighbours = [(j, s) for j, s in adjacency[i] if s >= effective_threshold]
        if not seed_neighbours:
            visited.add(i)
            continue

        # Greedy cluster: seed i + any neighbour not already in another group.
        candidate_idx = [i] + [j for j, _ in seed_neighbours]
        cluster_idx = [j for j in candidate_idx if j == i or j not in visited]
        if len(cluster_idx) < 2:
            visited.add(i)
            continue

        members = []
        for j in cluster_idx:
            visited.add(j)
            pid = photo_ids[j]
            meta = photo_meta.get(pid, {})
            fpath = meta.get("file_path")
            img_info_tuple = _read_image_info(fpath) if fpath and os.path.isfile(fpath) else (None, None, None)
            members.append({
                "_idx": j,
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

        members.sort(key=_best_key, reverse=True)
        ref = members[0]
        others = members[1:]
        ref_pid = ref["photo_id"]

        # Score each member by exact cosine against the chosen reference.
        # Vectors are unit-normalized, so dot product == cosine. This is
        # always exact (no dependency on whether the (ref, m) edge happened
        # to be in the sparse cache).
        ref_idx = ref.pop("_idx")
        ref["similarity_score"] = 1.0
        ref_vec = vectors[ref_idx]
        for m in others:
            m_idx = m.pop("_idx")
            m["similarity_score"] = float(np.dot(ref_vec, vectors[m_idx]))

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
            is_preferred = ref_fmt in _PREFERRED_MIME_TYPES
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
