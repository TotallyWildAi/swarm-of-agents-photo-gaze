# API Documentation

## Overview

The Photo Similarity Finder API is built with FastAPI and provides RESTful endpoints for photo management, similarity search, and user preferences. Real-time progress updates are available via WebSocket.



**Base URL**: `http://localhost:8000`

**API Docs (Swagger UI)**: `http://localhost:8000/docs`

**ReDoc**: `http://localhost:8000/redoc`



## Authentication

Currently, the API does not require authentication. In production, implement JWT or OAuth2 as needed.



## Response Format

All responses are JSON. Errors follow a consistent structure:



```json

{

  "error": "Error message",

  "detail": "Optional detailed explanation",

  "path": "/endpoint/path"

}

```



## Endpoints



### Health Check



#### `GET /health`

Check if the API is running and all dependencies are available.



**Response** (200 OK):

```json

{

  "status": "healthy",

  "database": "connected",

  "qdrant": "connected"

}

```



**Example**:

```bash

curl http://localhost:8000/health

```



---



### Folder Scanning & Job Management



#### `POST /rescan`

Initiate a photo scanning and processing job for a specified folder.



**Request Body**:

```json

{

  "folder_path": "/path/to/photos"

}

```



**Response** (202 Accepted):

```json

{

  "job_id": "550e8400-e29b-41d4-a716-446655440000",

  "status": "queued",

  "folder_path": "/path/to/photos"

}

```



**Errors**:

- `400 Bad Request`: Folder path is invalid or not a directory

- `422 Unprocessable Entity`: Missing or malformed request body



**Example**:

```bash

curl -X POST http://localhost:8000/rescan \

  -H "Content-Type: application/json" \

  -d '{"folder_path": "/home/user/Pictures"}'

```



---



#### `GET /job/{job_id}`

Get the current status of a processing job.



**Response** (200 OK):

```json

{

  "job_id": "550e8400-e29b-41d4-a716-446655440000",

  "status": "processing",

  "percentage": 45,

  "processed_photos": 450,

  "total_photos": 1000,

  "eta_seconds": 120

}

```



**Example**:

```bash

curl http://localhost:8000/job/550e8400-e29b-41d4-a716-446655440000

```



---



### Similarity Search



#### `POST /search`

Search for similar photos based on a threshold.



**Request Body**:

```json

{

  "threshold": 0.75

}

```



**Response** (200 OK):

```json

{

  "groups": [

    {

      "group_id": "group-001",

      "similarity_score": 0.92,

      "quality_score": 0.85,

      "members": [

        {

          "photo_id": "photo-001",

          "file_path": "/path/to/photo1.jpg",

          "file_hash": "abc123...",

          "filename": "photo1.jpg"

        },

        {

          "photo_id": "photo-002",

          "file_path": "/path/to/photo2.jpg",

          "file_hash": "def456...",

          "filename": "photo2.jpg"

        }

      ]

    }

  ],

  "total_groups": 1,

  "threshold_used": 0.75

}

```



**Parameters**:

- `threshold` (float, 0-1): Minimum similarity score to group photos. Lower values = more groups.



**Example**:

```bash

curl -X POST http://localhost:8000/search \

  -H "Content-Type: application/json" \

  -d '{"threshold": 0.75}'

```



---



#### `GET /threshold-examples`

Get example threshold values and their effects on grouping.



**Response** (200 OK):

```json

{

  "examples": [

    {

      "threshold": 0.5,

      "description": "Very loose grouping - many false positives",

      "expected_groups": 50

    },

    {

      "threshold": 0.75,

      "description": "Balanced - recommended for most use cases",

      "expected_groups": 150

    },

    {

      "threshold": 0.95,

      "description": "Strict grouping - only near-duplicates",

      "expected_groups": 300

    }

  ]

}

```



**Example**:

```bash

curl http://localhost:8000/threshold-examples

```



---



### User Preferences



#### `GET /preferences/{username}`

Retrieve user preferences.



**Response** (200 OK):

```json

{

  "id": 1,

  "username": "john_doe",

  "email": "john@example.com",

  "preferred_embedding_model": "dinov2_vitb14",

  "enable_auto_processing": true,

  "threshold_setting": 0.75

}

```



**Example**:

```bash

curl http://localhost:8000/preferences/john_doe

```



---



#### `POST /preferences`

Save or update user preferences.



**Request Body**:

```json

{

  "username": "john_doe",

  "email": "john@example.com",

  "preferred_embedding_model": "dinov2_vitb14",

  "enable_auto_processing": true,

  "threshold_setting": 0.75

}

```



**Response** (200 OK): Same as GET response



**Example**:

```bash

curl -X POST http://localhost:8000/preferences \

  -H "Content-Type: application/json" \

  -d '{

    "username": "john_doe",

    "email": "john@example.com",

    "preferred_embedding_model": "dinov2_vitb14",

    "enable_auto_processing": true,

    "threshold_setting": 0.75

  }'

```



---



#### `GET /threshold/{username}`

Get the current threshold setting for a user.



**Response** (200 OK):

```json

{

  "threshold_setting": 0.75

}

```



**Example**:

```bash

curl http://localhost:8000/threshold/john_doe

```



---



#### `POST /threshold/{username}`

Update the threshold setting for a user.



**Request Body**:

```json

{

  "threshold_setting": 0.80

}

```



**Response** (200 OK): Same as GET response



**Example**:

```bash

curl -X POST http://localhost:8000/threshold/john_doe \

  -H "Content-Type: application/json" \

  -d '{"threshold_setting": 0.80}'

```



---



### Backup & Recovery



#### `POST /backup/manual`

Trigger an immediate backup of PostgreSQL and Qdrant data.



**Response** (202 Accepted):

```json

{

  "backup_id": "backup-20240405-120000",

  "message": "Backup initiated",

  "status": "in_progress"

}

```



**Example**:

```bash

curl -X POST http://localhost:8000/backup/manual

```



---



#### `GET /backup/status`

Get status of recent backups and recovery options.



**Response** (200 OK):

```json

{

  "backups": [

    {

      "backup_id": "backup-20240405-120000",

      "timestamp": "2024-04-05T12:00:00Z",

      "status": "completed",

      "size_bytes": 1073741824

    }

  ],

  "last_backup": "2024-04-05T12:00:00Z"

}

```



**Example**:

```bash

curl http://localhost:8000/backup/status

```



---



#### `POST /backup/recover/{backup_id}`

Recover PostgreSQL and Qdrant data from a specific backup.



**Response** (200 OK):

```json

{

  "backup_id": "backup-20240405-120000",

  "message": "Recovery completed successfully",

  "status": "recovered"

}

```



**Example**:

```bash

curl -X POST http://localhost:8000/backup/recover/backup-20240405-120000

```



---



### Metrics



#### `GET /metrics`

Prometheus metrics for monitoring and alerting.



**Response** (200 OK): Prometheus text format

```

# HELP fastapi_requests_total Total HTTP requests

# TYPE fastapi_requests_total counter

fastapi_requests_total{endpoint="/search",method="POST",status="200"} 42.0

...

```



**Example**:

```bash

curl http://localhost:8000/metrics

```



---



## WebSocket



### Real-time Progress Updates



#### `WebSocket /ws/progress/{job_id}`

Connect to receive real-time progress updates for a processing job.



**Message Format** (sent by server):

```json

{

  "job_id": "550e8400-e29b-41d4-a716-446655440000",

  "status": "processing",

  "percentage": 45,

  "processed_photos": 450,

  "total_photos": 1000,

  "eta_seconds": 120

}

```



**Example (JavaScript)**:

```javascript

const ws = new WebSocket('ws://localhost:8000/ws/progress/550e8400-e29b-41d4-a716-446655440000');



ws.onmessage = (event) => {

  const update = JSON.parse(event.data);

  console.log(`Progress: ${update.percentage}% (${update.processed_photos}/${update.total_photos})`);

};



ws.onerror = (error) => {

  console.error('WebSocket error:', error);

};

```



---



## Error Handling



All errors return appropriate HTTP status codes and structured JSON:



| Status | Meaning | Example |

|--------|---------|----------|

| 200 | Success | Photo search completed |

| 202 | Accepted | Job queued for processing |

| 400 | Bad Request | Invalid folder path |

| 404 | Not Found | Job ID does not exist |

| 422 | Unprocessable Entity | Missing required field |

| 500 | Internal Server Error | Unexpected server error |

| 503 | Service Unavailable | Database or Qdrant offline |



---



## Rate Limiting



Currently, no rate limiting is enforced. For production, implement rate limiting based on IP or user ID.



---



## Pagination



The `/search` endpoint returns all groups. For large result sets, implement pagination:



```json

{

  "groups": [...],

  "total_groups": 500,

  "page": 1,

  "page_size": 50,

  "total_pages": 10

}

```

