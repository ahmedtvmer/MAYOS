FROM python:3.12-slim

WORKDIR /app

# Prevent interactive prompts during apt package installation
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# curl: container healthcheck. sqlite3: operator inspection. libgomp1 supports CPU PyTorch.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install UV binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV MODEL_DEVICE=cpu

COPY requirements.txt .

# Install CPU PyTorch for the embedding model, then service dependencies.
RUN uv pip install --system --index-url https://download.pytorch.org/whl/cpu "torch>=2.0" \
    && uv pip install --system -r requirements.txt

COPY . .

EXPOSE 8000

# The Flutter app connects to this FastAPI service.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=60s \
  CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "svc.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
