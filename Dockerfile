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

# Pin BLAS thread pools to 1. NumPy's bundled OpenBLAS is built with pthreads,
# not OpenMP. When PyTorch (which ships its own OpenMP runtime) calls into
# NumPy from inside a parallel region, OpenBLAS prints
#   "OpenBLAS warning: detect OpenMP loop and this application may hang.
#    Please rebuild the library with USE_OPENMP=1 option."
# and risks a nested-parallel deadlock. Forcing the BLAS pools to 1 thread
# avoids the hazard without rebuilding OpenBLAS. These must be set BEFORE
# numpy/torch are imported, so they live here at the image level.
ENV OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
