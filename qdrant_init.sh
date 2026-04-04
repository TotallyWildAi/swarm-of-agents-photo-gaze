#!/bin/bash
# Qdrant collection initialization script
# This script runs when the Qdrant container starts to set up the embeddings collection

set -e

# Wait for Qdrant to be ready
sleep 2

# Create embeddings collection with 1024-dimensional vectors
curl -X PUT http://localhost:6333/collections/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 1024,
      "distance": "Cosine"
    }
  }' || true

echo 'Qdrant collection initialization complete'

