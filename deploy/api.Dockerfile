FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace/apps/api:/workspace \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers

# yt-dlp's YouTube extractor needs an external JS runtime. Copy only the
# Node executable into the Python image so API, worker and beat share the same
# runtime without adding npm packages or a second application image.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /workspace

RUN groupadd --system sio && useradd --system --gid sio --create-home sio

RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "120";\n' \
    > /etc/apt/apt.conf.d/80-sio-retries

RUN --mount=type=cache,id=sio-pip-cache,target=/root/.cache/pip \
    --mount=type=cache,id=sio-apt-cache,target=/var/cache/apt,sharing=locked \
    set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg; \
    rm -rf /var/lib/apt/lists/*; \
    pip install "playwright>=1.52,<2"; \
    attempt=1; until playwright install-deps chromium; do \
        if [ "$attempt" -ge 5 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
    done; \
    attempt=1; until playwright install chromium; do \
        if [ "$attempt" -ge 5 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
    done; \
    chown -R sio:sio /opt/browsers

COPY apps/api /workspace/apps/api
COPY apps/worker /workspace/apps/worker
COPY apps/__init__.py /workspace/apps/__init__.py
COPY scripts /workspace/scripts

RUN --mount=type=cache,id=sio-pip-cache,target=/root/.cache/pip \
    pip install "/workspace/apps/api[dev,subtitle]" \
    && chown -R sio:sio /workspace

USER sio

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
