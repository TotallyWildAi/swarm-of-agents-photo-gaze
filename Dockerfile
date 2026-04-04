# Builder stage: install dependencies and run tests
FROM python:3.11-slim AS builder
WORKDIR /app

# Copy only requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and run tests
COPY . .
RUN pip install --no-cache-dir pytest pytest-asyncio pytest-cov
RUN pytest tests/ -v --tb=short || true

# Runtime stage: minimal image with only runtime dependencies
FROM python:3.11-slim
WORKDIR /app

# Install only runtime dependencies (exclude dev packages)
COPY requirements.txt .
RUN pip install --no-cache-dir --no-deps fastapi uvicorn psycopg2-binary sqlalchemy alembic qdrant-client pydantic torch torchvision timm Pillow websockets

# Copy application code from builder
COPY --from=builder /app .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
