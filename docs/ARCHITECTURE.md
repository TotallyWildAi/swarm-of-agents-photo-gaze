# Architecture Overview



## System Design



The Photo Similarity Finder is a distributed system with clear separation of concerns:



```

┌─────────────────────────────────────────────────────────────┐

│                     React Frontend (Port 3000)               │

│  ┌──────────────────────────────────────────────────────┐   │

│  │ FolderPathSelector │ ThresholdInput │ SimilarityGrid │   │

│  └──────────────────────────────────────────────────────┘   │

└─────────────────────────────────────────────────────────────┘

                    ↓ HTTP + WebSocket

┌─────────────────────────────────────────────────────────────┐

│                  FastAPI Backend (Port 8000)                │

│  ┌──────────────────────────────────────────────────────┐   │

│  │ REST Endpoints │ WebSocket Handler │ Error Handlers  │   │

│  └──────────────────────────────────────────────────────┘   │

│  ┌──────────────────────────────────────────────────────┐   │

│  │ Orchestrator │ Job Queue │ Similarity Search Service │   │

│  └──────────────────────────────────────────────────────┘   │

│  ┌──────────────────────────────────────────────────────┐   │

│  │ Folder Scanner │ Metadata Extractor │ Thumbnail Gen  │   │

│  └──────────────────────────────────────────────────────┘   │

└─────────────────────────────────────────────────────────────┘

         ↓ SQL              ↓ Vector Ops      ↓ Backup

    ┌─────────────┐    ┌──────────────┐   ┌──────────┐

    │ PostgreSQL  │    │ Qdrant       │   │ S3/Local │

    │ (Metadata)  │    │ (Embeddings) │   │ (Backup) │

    └─────────────┘    └──────────────┘   └──────────┘

```



## Component Architecture



### Frontend (React + TypeScript)



**Location**: `frontend/src/`



#### Key Components


1. **App.tsx** - Main application container

   - Manages global state (theme, user preferences)

   - Routes between folder selection and results view

   - Handles WebSocket connection lifecycle



2. **FolderPathSelector.tsx** - Folder selection UI

   - Text input for folder path

   - Validation feedback

   - Triggers `/rescan` endpoint



3. **ThresholdInput.tsx** - Similarity threshold control

   - Slider (0-1) for threshold adjustment

   - Real-time preview of expected group count

   - Triggers `/search` endpoint



4. **SimilarityGrid** - Results display

   - Grid layout of similarity groups

   - Thumbnail previews

   - Group metadata (similarity score, member count)



#### API Client (api.ts)



- Centralized HTTP client with error handling

- WebSocket connection manager for progress updates

- Type-safe interfaces for all API responses

- Automatic retry logic for transient failures



### Backend (FastAPI + Python)



**Location**: `app/`



#### Core Modules



1. **main.py** - Application entry point

   - FastAPI app initialization

   - HTTP endpoint definitions

   - WebSocket handler

   - Middleware for metrics and error handling

   - Startup/shutdown hooks



2. **folder_scanner.py** - File system traversal

   - Recursive directory scanning

   - Image format filtering (JPEG, PNG, WebP)

   - Returns list of photo paths



3. **metadata_extractor.py** - Image metadata extraction

   - EXIF data parsing (camera, date, GPS)

   - Image dimensions and format detection

   - SHA256 file hash for deduplication

   - Validates image format before processing



4. **orchestrator.py** - Workflow orchestration

   - Coordinates folder scanning → metadata extraction → embedding generation

   - Manages job state transitions

   - Handles error recovery and retries



5. **job_queue.py** - Async job processing

   - Queue-based job management

   - Checkpoint system for fault tolerance

   - Progress tracking and ETA calculation

   - Recovers incomplete jobs on startup



6. **similarity_search.py** - In-memory group management

   - Thread-safe storage of similarity groups

   - Group CRUD operations

   - Filtering by threshold



7. **thumbnail.py** - Thumbnail generation

   - Generates 200x200px thumbnails

   - Caches thumbnails on disk

   - Serves thumbnails via HTTP



8. **backup_manager.py** - Disaster recovery

   - Automated PostgreSQL backups

   - Qdrant vector database snapshots

   - Point-in-time recovery

   - Retention policy enforcement



9. **models.py** - SQLAlchemy ORM models

   - `Photo` - Photo metadata and embeddings

   - `User` - User preferences and settings

   - Relationships and constraints



### Data Flow



#### Photo Processing Pipeline



```
1. User selects folder via FolderPathSelector
   ↓
2. Frontend calls POST /rescan with folder_path
   ↓
3. Backend creates job, returns job_id (202 Accepted)
   ↓
4. Frontend connects to WebSocket /ws/progress/{job_id}
   ↓
5. Backend Orchestrator starts processing:
   a. FolderScanner finds all image files
   b. For each image:
      - MetadataExtractor reads EXIF, dimensions, hash
      - Store metadata in PostgreSQL
      - Generate DINOv2 embedding (GPU-accelerated)
      - Store embedding in Qdrant
      - Generate thumbnail
   c. Update job progress via WebSocket
   ↓
6. When complete, backend computes similarity groups:
   - Query Qdrant for similar embeddings
   - Group by similarity score
   - Store groups in SimilarityGroupService
   ↓
7. Frontend receives completion message
   ↓
8. User adjusts threshold via ThresholdInput
   ↓
9. Frontend calls POST /search with threshold
   ↓
10. Backend filters groups by threshold
    ↓
11. Frontend displays SimilarityGrid with results
```



#### Similarity Search Algorithm



1. **Embedding Generation**

   - DINOv2 ViT-B/14 model (768-dimensional vectors)

   - Processes images at 224x224 resolution

   - GPU-accelerated with CUDA (fallback to CPU)



2. **Vector Storage**

   - Qdrant vector database

   - Cosine similarity metric

   - Indexed for fast nearest-neighbor search



3. **Grouping**

   - For each photo, find k-nearest neighbors

   - Group by similarity threshold (0-1)

   - Compute group quality score (average similarity)



4. **Threshold Adjustment**

   - User adjusts threshold slider

   - Groups are filtered in-memory (no re-computation)

   - Results update instantly



### Database Schema



#### PostgreSQL Tables



```sql

-- Photos and metadata

CREATE TABLE photos (

  id SERIAL PRIMARY KEY,

  file_path VARCHAR UNIQUE NOT NULL,

  file_hash VARCHAR(64) UNIQUE NOT NULL,

  filename VARCHAR NOT NULL,

  width INTEGER,

  height INTEGER,

  format VARCHAR(10),

  file_size BIGINT,

  created_at TIMESTAMP DEFAULT NOW(),

  updated_at TIMESTAMP DEFAULT NOW()

);



-- User preferences

CREATE TABLE users (

  id SERIAL PRIMARY KEY,

  username VARCHAR UNIQUE NOT NULL,

  email VARCHAR,

  preferred_embedding_model VARCHAR DEFAULT 'dinov2_vitb14',

  enable_auto_processing BOOLEAN DEFAULT true,

  threshold_setting FLOAT DEFAULT 0.75,

  created_at TIMESTAMP DEFAULT NOW(),

  updated_at TIMESTAMP DEFAULT NOW()

);



-- Job tracking

CREATE TABLE jobs (

  id VARCHAR PRIMARY KEY,

  status VARCHAR(20),

  folder_path VARCHAR,

  total_photos INTEGER,

  processed_photos INTEGER,

  checkpoint_data JSONB,

  created_at TIMESTAMP DEFAULT NOW(),

  updated_at TIMESTAMP DEFAULT NOW()

);

```



#### Qdrant Collections



```json

{

  "name": "photo_embeddings",

  "vectors": {

    "size": 768,

    "distance": "Cosine"

  },

  "payload_schema": {

    "photo_id": "integer",

    "file_hash": "keyword",

    "filename": "text"

  }

}

```



### Fault Tolerance



#### Job Queue Checkpointing



- After processing each photo, job state is saved to PostgreSQL

- On startup, incomplete jobs are recovered from checkpoint

- Prevents re-processing of already-completed photos

- Supports pause/resume workflows



#### Backup & Recovery



- Automated daily backups of PostgreSQL and Qdrant

- Point-in-time recovery available

- Backup retention policy (default: 7 days)

- Manual backup trigger via `/backup/manual` endpoint



#### Error Handling



- Global exception handler returns structured JSON errors

- Transient failures (network, timeouts) trigger automatic retries

- Failed photos are logged and skipped (job continues)

- User receives summary of failed photos at job completion



### Performance Characteristics



| Operation | Throughput | Latency | Notes |

|-----------|-----------|---------|-------|

| Folder Scan | ~1000 photos/sec | - | Depends on filesystem |

| Metadata Extract | ~50 photos/sec | 20ms/photo | EXIF parsing |

| Embedding Gen | ~10 photos/sec | 100ms/photo | GPU-accelerated |

| Similarity Search | - | <100ms | For 10k photos |

| Threshold Filter | - | <10ms | In-memory operation |



### Monitoring & Observability



#### Prometheus Metrics



- `fastapi_requests_total` - Request count by endpoint and status

- `fastapi_request_duration_seconds` - Request latency histogram

- `fastapi_active_requests` - Current active request gauge

- `fastapi_errors_total` - Error count by type



#### Logging



- Structured JSON logging with context (job_id, photo_id)

- Log levels: DEBUG, INFO, WARNING, ERROR

- Logs include stack traces for exceptions



#### Health Checks



- `/health` endpoint checks database and Qdrant connectivity

- Returns 503 if any dependency is unavailable

- Used by Docker health checks and load balancers



### Deployment Architecture



#### Docker Compose (Development)



```yaml

services:

  postgres:      # PostgreSQL 14

  qdrant:        # Qdrant vector DB

  backend:       # FastAPI app

  frontend:      # React app

```



#### Kubernetes (Production)



- Backend: Deployment with 3+ replicas, HPA based on CPU/memory

- Frontend: Deployment with 2+ replicas, CDN for static assets

- PostgreSQL: StatefulSet with persistent volume, automated backups

- Qdrant: StatefulSet with persistent volume, replication

- Ingress: TLS termination, rate limiting, request routing



### Security Considerations



- **Authentication**: Currently none; add JWT/OAuth2 for production

- **Authorization**: Implement role-based access control (RBAC)

- **Input Validation**: All endpoints validate request data

- **SQL Injection**: SQLAlchemy ORM prevents SQL injection

- **CORS**: Configure allowed origins for frontend

- **HTTPS**: Use TLS in production

- **Secrets**: Store database credentials in environment variables



### Future Enhancements



1. **Distributed Processing**: Celery for horizontal scaling

2. **Advanced Filtering**: Filter by date, camera, location

3. **Batch Operations**: Delete/move multiple groups at once

4. **Custom Models**: Support for user-trained embedding models

5. **Real-time Collaboration**: Multi-user session support

6. **Mobile App**: Native iOS/Android clients

