FROM python:3.12-slim

WORKDIR /app

# Prevent interactive prompts during apt package installation
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 \
    MODEL_DEVICE=cpu

# curl: container healthcheck. sqlite3: operator inspection.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install UV binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY requirements.txt .

RUN uv pip install --system -r requirements.txt

# Bake the ONNX graph, tokenizer and Sentence Transformers configs.
COPY core/embeddings.py /app/core/embeddings.py
RUN python -c "from core.embeddings import download_model_files; download_model_files()"
ENV HF_HUB_OFFLINE=1

COPY . .

EXPOSE 8000

# The Flutter app connects to this FastAPI service.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "svc.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
