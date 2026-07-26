FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/workspace/apps/api:/workspace

WORKDIR /workspace

RUN groupadd --system sio && useradd --system --gid sio --create-home sio

COPY apps/api /workspace/apps/api
COPY apps/worker /workspace/apps/worker
COPY apps/__init__.py /workspace/apps/__init__.py

RUN pip install --no-cache-dir "/workspace/apps/api[dev]" \
    && chown -R sio:sio /workspace

USER sio

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
