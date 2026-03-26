FROM python:3.11-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# App code
COPY . .

# Ensure dirs exist
RUN mkdir -p experiments logs data/cache

EXPOSE 8000

# Default: run the API server
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
