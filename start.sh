#!/usr/bin/env bash
# Start the full photo-similarity stack: Postgres, Qdrant, FastAPI, React,
# Prometheus + Alertmanager + node_exporter.
#
# Usage:
#   ./start.sh            # build (if needed) and start everything in the
#                         # background, then wait until the fastapi backend
#                         # answers /health.
#   ./start.sh --logs     # same, but tail aggregated logs after services
#                         # come up. Ctrl-C detaches (containers keep running).
#   ./start.sh --rebuild  # force rebuild of the fastapi/react images.
#   ./start.sh --down     # stop and remove all containers (volumes kept).
#
# Prerequisites: Docker Desktop (or compatible Docker engine) must be
# running. Everything else is pulled/built automatically.

set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose)

case "${1:-}" in
  --down)
    echo "Stopping stack..."
    "${COMPOSE[@]}" down
    exit 0
    ;;
  --logs)
    FOLLOW_LOGS=1
    BUILD_FLAG="--build"
    ;;
  --rebuild)
    FOLLOW_LOGS=0
    BUILD_FLAG="--build"
    ;;
  "")
    FOLLOW_LOGS=0
    BUILD_FLAG="--build"
    ;;
  *)
    echo "Unknown arg: $1"
    echo "Usage: $0 [--logs|--rebuild|--down]"
    exit 1
    ;;
esac

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker Desktop and retry." >&2
  exit 1
fi

# Ensure .env exists and load HOST_HOME / TRASH_DIR. docker compose auto-reads
# .env from the project dir for substitution, but exporting them here also
# makes them visible to any helper command in this script.
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cat >&2 <<'EOF'
ERROR: No .env found. Copy .env.example to .env and set HOST_HOME (the host
directory to bind-mount into the backend, e.g. /Users/youruser):

    cp .env.example .env && $EDITOR .env
EOF
  else
    echo "ERROR: No .env and no .env.example to bootstrap from." >&2
  fi
  exit 1
fi
set -a; . ./.env; set +a

: "${HOST_HOME:?HOST_HOME is required in .env (host directory to bind-mount, e.g. /Users/youruser)}"
if [ ! -d "$HOST_HOME" ]; then
  echo "ERROR: HOST_HOME='$HOST_HOME' is not an existing directory." >&2
  exit 1
fi
echo "Using HOST_HOME=$HOST_HOME"

echo "Bringing the stack up (this pulls images and builds on first run)..."
"${COMPOSE[@]}" up -d $BUILD_FLAG

# Wait for fastapi /health to return 200. First startup downloads the
# DINOv2 model (~90MB for vits14) so give it some room.
echo -n "Waiting for fastapi to become healthy"
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://localhost:8000/health 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then
    echo
    echo "fastapi is healthy."
    break
  fi
  echo -n "."
  sleep 3
done
if [ "${code:-000}" != "200" ]; then
  echo
  echo "WARNING: fastapi did not become healthy within 3 minutes. Check: docker compose logs fastapi" >&2
fi

# Sanity-check react
react_code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://localhost:3000/ 2>/dev/null || echo 000)
echo "react HTTP code: $react_code"

cat <<EOF

Stack is up. URLs:
  - UI:           http://localhost:3000
  - Backend API:  http://localhost:8000 (try /health, /stats, /folders)
  - Qdrant UI:    http://localhost:6333/dashboard
  - Prometheus:   http://localhost:9090
  - Alertmanager: http://localhost:9093

Register a photo folder from the UI ("Photo Folders" panel), then hit
"Scan" to start embedding generation. Progress is visible in the
"Processing Status" panel right below it.

Run ./start.sh --logs to tail all service logs, or ./start.sh --down to stop.
EOF

if [ "${FOLLOW_LOGS:-0}" = "1" ]; then
  echo
  echo "Tailing logs (Ctrl-C detaches, containers keep running)..."
  "${COMPOSE[@]}" logs -f --tail=20
fi
