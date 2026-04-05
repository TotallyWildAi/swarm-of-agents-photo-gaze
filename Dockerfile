# Multi-stage build for optimized backend image
# Builder stage: compile dependencies and run tests
FROM python:3.11-slim AS builder
WORKDIR /app

# Install build dependencies needed for compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install runtime dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy source code
COPY . .

# Runtime stage: minimal image with only runtime dependencies
FROM python:3.11-slim
WORKDIR /app

# Copy only the installed Python packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY . .

# Set PATH to use local pip installations
ENV PATH=/root/.local/bin:$PATH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
