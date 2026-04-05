# DINOv2 Photo Similarity Search & Deduplication System

A self-hosted photo management platform that uses the DINOv2 vision transformer to find visually similar images and surface originals in a duplicate cluster. FastAPI backend, React/TypeScript frontend, PostgreSQL for metadata, Qdrant for vector search, Prometheus/Alertmanager for monitoring.

## Quick start

```bash
./start.sh            # builds images on first run, brings everything up
./start.sh --logs     # same + tail aggregated logs
./start.sh --rebuild  # force-rebuild fastapi/react images
./start.sh --down     # stop and remove containers (volumes are kept)
```

Then open http://localhost:3000, add a folder under the **Photo Folders** panel (any host path under your home dir, e.g. `/Users/you/Pictures/vacation`), and click **Scan**. Progress shows live in the **Processing Status** panel.

## Where the data lives

The stack runs as Docker containers with named volumes for persistence:

| What | Where | Notes |
|---|---|---|
| **Photo files (originals)** | Your filesystem, e.g. `/Users/you/Pictures/...` | Mounted **read-only** into the backend container at the same path via `docker-compose.yml`. The app never writes to your photos. |
| **Photo metadata, folders, processing state** | Postgres (`postgres_data` volume) | Tables: `photos`, `folder_paths`, `processing_state`, `job_queue`, `embeddings` (pointer rows), `user_preferences`. |
| **Embedding vectors (1024-dim floats)** | Qdrant (`qdrant_storage` volume) | Collection `embeddings`, cosine distance. Each vector has `{"photo_id": N}` payload; the UUID point_id matches `embeddings.qdrant_point_id` in Postgres. |
| **Thumbnails** | Filesystem inside the backend container at `/app/thumbnails/` | Regenerated on demand; safe to delete to reclaim space. |
| **Embedding model weights** | `torch_cache` volume (`/root/.cache/torch`) | DINOv2 weights (~90MB for ViT-S/14). Persisted so containers don't re-download on rebuild. |
| **Prometheus metrics** | `prometheus_data` volume | 15 days retention by default. |
| **Alertmanager state** | `alertmanager_data` volume | Notification silences, inhibitions. |

### Data flow

```
photo file on disk ──► /rescan scan ──► photos (postgres) + processing_state (postgres, pending)
                                              │
                                              ▼
                                      /process-pending queue
                                              │
                                              ▼
                              DINOv2 ViT-S/14 @ 224x224 (CPU)
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
             Qdrant collection "embeddings"              embeddings row in Postgres
             (1024-dim vector + photo_id payload)        (photo_id, model, qdrant_point_id)
                       │
                       ▼
              /similarity-groups queries Qdrant per-point with score_threshold ──► UI grid
```

### Inspecting the data directly

```bash
# List registered folders
curl -s http://localhost:8000/folders | jq

# Current counts
curl -s http://localhost:8000/stats | jq

# Postgres (metadata side)
docker exec -it postgres_db psql -U postgres -d app_db \
  -c "SELECT COUNT(*) photos, (SELECT COUNT(*) FROM embeddings) embeddings FROM photos;"

# Qdrant (vector side)
curl -s http://localhost:6333/collections/embeddings | jq .result   # config + count
curl -s -X POST http://localhost:6333/collections/embeddings/points/scroll \
  -H 'Content-Type: application/json' -d '{"limit":5,"with_payload":true,"with_vector":false}' | jq

# Qdrant dashboard UI
open http://localhost:6333/dashboard
```

### Deleting data

- **Remove a folder from the UI** — deletes the folder from `folder_paths`, every matching row in `photos` / `processing_state` / `embeddings`, AND the corresponding points in Qdrant. Your original photo files on disk are never touched.
- **`./start.sh --down`** — stops containers but keeps all volumes. Data survives.
- **`docker compose down -v`** — **destroys all volumes** (Postgres, Qdrant, thumbnails, model cache, Prometheus, Alertmanager). Original photos on disk are still untouched.

## How it was built

> **No human wrote any of this code.**
>
> An autonomous AI agent pipeline took an empty repo and 40 task descriptions, and produced a working multi-service application — **11,400 lines of code, 285 tests, 7 Docker services — for $6.31 in API costs**.

### Build stats

These metrics count only the **last successful completion of each task** — earlier aborted/reworked attempts are excluded.

| Metric | Value            |
|---|------------------|
| Tasks completed | 40 / 40 (100%)   |
| Tasks blocked | 0                |
| Rework cycles | 13               |
| LLM calls | 327              |
| Input tokens | 3,505,714        |
| Output tokens | 560,513          |
| **Total tokens** | **4,066,227**    |
| Sum of task durations | 72.3 minutes     |
| Model | claude-haiku-4-5 |
| **API cost** | **~$6.31 USD**   |

Cost math: 3.51M input × $1/MTok + 0.56M output × $5/MTok = **$6.31**

### Resulting code

- **55 Python files** (FastAPI backend, services, tests)
- **33 frontend files** (26 TypeScript/TSX + 7 JavaScript/JSX — React components, API client, hooks, configs)
- **~11,400 lines of code** (excluding generated/dependency files)
- **285 tests** across 29 test files
- **11 REST/WebSocket API endpoints**
- **7 Docker Compose services** (postgres, qdrant, fastapi, react, prometheus, alertmanager, node-exporter)

### How long would this take a human?

This isn't a comparison call — different people work differently. For context:

| Scenario | Estimate |
|---|---|
| Senior engineer, optimistic (knows Python, FastAPI, React, Qdrant, DINOv2, Docker Compose, Prometheus already — no learning, no distractions, crunch mode) | **2–3 weeks** |
| Senior engineer, realistic (normal workday, meetings, reviews, some learning on Qdrant/DINOv2 specifics) | **6–8 weeks** |
| Average team output (two engineers, typical planning/review overhead, some iteration on acceptance criteria) | **8–12 weeks** |

The agent pipeline did it in **~72 minutes of per-task active time** (summing the wall clock of each task's final successful run). End-to-end with orchestration overhead, git operations, build runs, and code review cycles, it took about 5–6 hours of real time on a single machine.

The point isn't that AI replaces engineers. The point is that repetitive scaffolding work — the kind every new project starts with — is becoming something you can run instead of write. A senior engineer's time is still needed, just shifted toward architecture, review, and judgment calls.

## How to run

One command starts everything:

```bash
docker compose up --build
```

That brings up:
- **Postgres** on `localhost:5432` (metadata storage)
- **Qdrant** on `localhost:6333` (vector similarity search)
- **FastAPI backend** on `localhost:8000` (REST + WebSocket)
- **React frontend** on `localhost:3000` (UI)
- **Prometheus** on `localhost:9090` (metrics)
- **Alertmanager** on `localhost:9093` (alert routing)
- **node-exporter** on `localhost:9100` (host metrics)

Health check:
```bash
curl http://localhost:8000/health
```

Open the UI:
```
http://localhost:3000
```

### Local dev (without Docker)

```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app_db \
QDRANT_URL=http://localhost:6333 \
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# Tests
pytest -v
cd frontend && npm test
```

## Architecture

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  React   │────▶│ FastAPI  │────▶│ Postgres │  (metadata, jobs, sessions)
│ Frontend │     │ Backend  │     └──────────┘
└──────────┘     │          │     ┌──────────┐
                 │          │────▶│  Qdrant  │  (1024-dim embeddings)
                 │          │     └──────────┘
                 │          │     ┌──────────┐
                 │          │────▶│ DINOv2   │  (embedding generation)
                 └──────────┘     └──────────┘
                       │
                       │ /metrics
                       ▼
                 ┌──────────┐     ┌──────────────┐
                 │Prometheus│────▶│ Alertmanager │
                 └──────────┘     └──────────────┘
```

## What it does

1. **Scan a folder** of photos (JPEG, PNG, WebP, RAW)
2. **Extract metadata** (dimensions, size, hash, timestamp)
3. **Generate embeddings** via DINOv2 ViT-L14 (1024-dim vectors)
4. **Store** metadata in Postgres, vectors in Qdrant
5. **Find similar images** via cosine similarity with configurable threshold
6. **Identify the original** in each similarity group by quality score + file metadata
7. **Display** results in a grid with thumbnails, quality indicators, and batch actions

## API endpoints

- `GET /similarity-groups` — list groups (pagination, sort by similarity/quality)
- `GET /similarity-groups/{group_id}` — group detail with member thumbnails
- `GET /thumbnails/{photo_id}` — cached thumbnail bytes
- `POST /rescan` — trigger folder re-scan with incremental processing
- `GET /job-queue/status` — current queue state
- `WebSocket /ws/progress/{job_id}` — real-time progress updates
- `POST /backup/manual` — trigger manual backup
- `GET /backup/status` — backup status
- `POST /backup/recover/{backup_id}` — restore from backup
- `GET /metrics` — Prometheus metrics
- `GET /health` — liveness probe

## Notes for reviewers

- All 40 tasks came from a structured handover plan (see `../../../src/test/resources/handover/dinov2-benchmark.json`)
- Each task went through: investigate → implement → build → code review → merge → post-merge verification
- Code review caught 13 issues across the 40 tasks, each resolved via rework (security, correctness, style)
- The benchmark harness that built this is in `../../../src/test/java/com/kislov/platform/service/AgentBenchmarkTest.java`
- Per-task LLM call logs, token counts, and debug artifacts are in `logs/`

---

Built by an AI agent pipeline. If you're curious about how the pipeline works or want to discuss applying it to your own codebases, reach out.
