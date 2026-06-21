# ──────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for the Product Catalog API
# Stage 1: Install dependencies in a clean layer
# Stage 2: Copy only what's needed for a slim runtime image
# ──────────────────────────────────────────────────────────────

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps for asyncpg (libpq) compilation
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install runtime libpq only (no compiler)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd --create-home appuser
USER appuser

# Expose port
EXPOSE 8000

# Gunicorn with Uvicorn workers for production
# Workers = 2 * CPU + 1 (default 4 for a 2-core Render instance)
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--access-logfile", "-"]
