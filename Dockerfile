# Housy production image (Cloud Run). Python 3.12 (3.9 was EOL).
FROM python:3.12-slim

# Stream logs immediately (no buffering) and don't write .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code only (data/, .env, tests excluded via .dockerignore).
COPY app ./app

# Run as a non-root user (security best practice).
RUN useradd --create-home --uid 1000 housy && chown -R housy /app
USER housy

# Cloud Run provides $PORT (default 8080). Bind uvicorn to it.
ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
