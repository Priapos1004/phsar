# syntax=docker/dockerfile:1

# ---------- Builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first (huge wheel) via the pytorch CPU index
# so sentence-transformers doesn't pull the GPU variant (~2 GB saved).
# Pinned for layer-cache stability.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.11.0+cpu

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Bake the sentence-transformers model into the image so production
# cold starts don't stall on a ~500 MB download. The model rarely
# changes; when it does, a deliberate image rebuild picks up the new one.
ENV SENTENCE_TRANSFORMERS_HOME=/opt/st-cache
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime

ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTENCE_TRANSFORMERS_HOME=/opt/st-cache \
    APP_VERSION=${APP_VERSION}

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 phsar \
    && useradd --system --uid 1000 --gid phsar --home /app phsar \
    && mkdir -p /backups \
    && chown phsar:phsar /backups

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder --chown=phsar:phsar /opt/st-cache /opt/st-cache

COPY --chown=phsar:phsar app ./app
COPY --chown=phsar:phsar alembic ./alembic
COPY --chown=phsar:phsar alembic.ini ./
COPY --chown=phsar:phsar docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER phsar
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else sys.exit(1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
