# Myos: Production Deployment, Containerization & Operational Runbook

This document details production deployment procedures, container orchestration, host hardware tuning, database provisioning, and disaster recovery protocols for the Myos training engine.

---

## 1. Host Hardware & Runtime Prerequisites

Myos runs entirely in-process without external model daemons or network API requirements. The reference deployment target is a single host with one modest CUDA GPU:

| Resource | Minimum | Recommended | Notes |
| :--- | :--- | :--- | :--- |
| CPU | 4 physical cores, x86_64 with **AVX2 + FMA** | 6+ physical cores | OpenMP pinning matters more than core count |
| RAM | 8 GB | 16 GB | ~2.7 GB for the 4B weights (when GPU-offloaded, this is VRAM), ~0.5 GB embeddings, remainder for OS/SQLite |
| GPU (optional) | — | 4 GB VRAM CUDA card (e.g. Quadro T2000) | 4B Q4_K_M fully offloads into 4 GB; the 9B judge partially offloads (see §4) |
| Disk | 10 GB free | 20 GB+ | GGUF weights (2.7 GB + optional 5.7 GB judge) and per-user ledgers |

CPU-only hosts are fully supported: set `N_GPU_LAYERS=0` (see §4) and expect roughly 5–15 TPS generation versus 30+ TPS with GPU offload.

**Host system dependencies (non-Docker native runs):**

```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential \
    libgomp1 \
    sqlite3 \
    curl
```

---

## 2. Docker Architecture & Container Topology

The deployment is **two application services sharing one image** plus an optional tunnel:

```
+-----------------------------------------------------------------------------------+
|                                   HOST SYSTEM                                     |
|                                                                                   |
|   Persistent Volumes:                                                             |
|   ├── ./models/  ------> /app/models  (GGUF weights; auto-download on first boot) |
|   ├── ./db/      ------> /app/db      (catalog.db + users/ + backups/)            |
|   └── ./logs/    ------> /app/logs    (structured telemetry log)                  |
|                                                                                   |
|   +----------------------------------+   +-------------------------------------+  |
|   |  Container: myos_api             |   |  Container: myos_engine             |  |
|   |  uvicorn svc.app:app  (:8000)    |<--|  Streamlit UI          (:8501)      |  |
|   |  JWT auth, rate limits, SSE      |   |  Thin HTTP client only              |  |
|   |  LangGraph + SafeChatLlamaCpp    |   +-------------------------------------+  |
|   |  DatabaseManager (thread-local)  |                     ^                      |
|   +----------------------------------+                     |                      |
|                                                            |                      |
|                                              +-----------------------------+       |
|                                              | cloudflared tunnel (optional)|       |
|                                              +-----------------------------+       |
+-----------------------------------------------------------------------------------+
```

Only `myos-api` holds the model, the databases, and the assistant graph. `myos-engine` is a pure presentation client that talks to `API_BASE_URL`. The shared image is built from the actual `Dockerfile` *(abridged — see the file itself for verbatim comments)*:

```dockerfile
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Python 3.12 (deadsnakes), build tools, sqlite3, libgomp
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common curl sqlite3 libgomp1 build-essential tzdata \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-dev python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# NVIDIA runtime flags; compose overrides per host
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    N_GPU_LAYERS=-1 \
    EMBEDDING_DEVICE=cuda

COPY requirements.txt .

# CUDA 12.4 prebuilt wheel for llama-cpp-python
RUN uv pip install --system \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 \
    llama-cpp-python

RUN uv pip install --system -r requirements.txt

COPY . .

EXPOSE 8000 8501

# Default CMD serves the Streamlit UI; compose overrides per service.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
```

> **CPU-only hosts:** swap the base image for `python:3.12-slim-bookworm`, install the CPU wheel (`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`), and set `N_GPU_LAYERS=0`. No NVIDIA runtime is required.

---

## 3. Configuration & Secrets

Copy [`.env.example`](../.env.example) and fill it in. The compose file **requires** `JWT_SECRET` to be exported in the host environment — `docker compose up` fails fast without it (`${JWT_SECRET:?set JWT_SECRET in environment}`).

```bash
# Generate a signing secret (64 hex chars)
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `JWT_SECRET` | **required** | HS256 token signing/verification; the service refuses to operate without it |
| `JWT_EXPIRY_HOURS` | `2` | Access-token lifetime |
| `UI_BASE_URL` | `http://localhost:8501` | CORS origin **and** password-reset link base |
| `API_BASE_URL` | `http://localhost:8000` | Streamlit → API base (compose sets `http://myos-api:8000`) |
| `RESET_TOKEN_TTL_MINUTES` | `30` | Reset-link lifetime (clamped 5–120) |
| `SMTP_HOST` | unset | **Unset ⇒ console-dev backend** (reset links logged, not sent). Configure for real deployments |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | `587` / `true` / — / — / `no-reply@myos.local` | SMTP transport |
| `RATE_LIMIT_LOGIN` / `_REGISTER` / `_PASSWORD` / `_RESET` / `_CHAT` / `_ONBOARDING` | `5/min` / `5/min` / `10/min` / `3/hour` / `30/min` / `30/min` | Per-route limits |
| `MODEL_PATH` / `JUDGE_MODEL_PATH` | registry defaults | Explicit GGUF paths (win over `MODEL_DIR` + registry filename) |
| `MODEL_DIR` | `models/` | Download target directory |
| `MODEL_REVISION` / `MODEL_SHA256` (and `JUDGE_*`) | unset | Optional pin + integrity check for reproducible deployments |
| `N_GPU_LAYERS` | `-1` (all layers) | Production model offload; `0` = CPU-only |
| `JUDGE_N_GPU_LAYERS` | `18` | Judge offload default; tune per VRAM (see §4) |
| `LLM_N_CTX` / `LLM_MAX_TOKENS` / `LLM_N_BATCH` / `LLM_THREADS` | `2048` / `200` / `512` / `OMP_NUM_THREADS` | Inference tuning |
| `OMP_NUM_THREADS` | — | Pin to physical cores (see §6) |
| `SKIP_LLM_LOAD` | unset | Skips **eager warmup only**; the real GGUF lazy-loads on first inference. **Not** a mock switch |
| `TESTING` | unset | Substitutes the in-repo mock model (CI/tests only; never in production) |
| `CI` | unset | Mock fallback only when the model file is absent |

---

## 4. GPU Memory Planning & the Two-Phase Evaluation Lifecycle

Myos runs **two different models** and a single modest GPU can serve both — sequentially, never concurrently:

| Model | Role | Quantized size | Offload strategy on a 4 GB card |
| :--- | :--- | :--- | :--- |
| Qwen3.5-4B | Production chat / onboarding / debriefs | ≈2.7 GB | **Full offload** (`N_GPU_LAYERS=-1`) — fits with context |
| Qwen3.5-9B | LLM-as-a-judge (offline evaluation only) | ≈5.7 GB | **Partial offload** — the engine loads it *after* the production model is unloaded |

The evaluation runner (`tests/eval/run_evaluation.py`) is explicitly two-phase:

1. **Generation batch** — the production LLM answers every case (`N_GPU_LAYERS`, default `-1`).
2. `unload_llm()` — the production model is explicitly released and VRAM reclaimed (CUDA cache emptied).
3. **Judgement batch** — the 9B judge loads into the freed VRAM (`--gpu-layers`, default 16) and scores every candidate.
4. `unload_judge_llm()` at the end.

**Tuning `--gpu-layers` for the judge:** on the reference 4 GB T2000 (Quadro), 16 layers is the maximum that reliably loads at `n_ctx=4096` (the 9B has 32 transformer blocks). Higher values fail context creation and — thanks to the loader's hardware-failure retry — silently fall back to CPU, making judgement ~10× slower. If VRAM is exhausted, the loader logs a warning and retries once on CPU rather than crashing:

```bash
# Reference invocation on a 4 GB GPU (generation full-offload, judge 16/32 layers)
export N_GPU_LAYERS=-1
python tests/eval/run_evaluation.py --target all --gpu-layers 16
python tests/eval/run_evaluation.py --generalize --gpu-layers 16
```

### Production `docker-compose.yaml` (actual — abridged formatting)

```yaml
services:
  myos-api:
    build: { context: ., dockerfile: Dockerfile }
    container_name: myos_api
    restart: unless-stopped
    stop_grace_period: 60s
    command: ["uvicorn", "svc.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
    ports: ["8000:8000"]
    volumes:
      - ./models:/app/models
      - ./db:/app/db
      - ./logs:/app/logs
    environment:
      - MODEL_PATH=/app/models/Qwen3.5-4B-Q4_K_M.gguf
      - JUDGE_MODEL_PATH=/app/models/Qwen3.5-9B-Q4_K_M.gguf
      - MODEL_DIR=/app/models
      - EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
      - N_GPU_LAYERS=16
      - MODEL_DEVICE=cuda
      - EMBEDDING_DEVICE=cuda
      - JWT_SECRET=${JWT_SECRET:?set JWT_SECRET in environment}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 120s
    deploy:
      resources:
        reservations:
          devices: [{ driver: nvidia, count: all, capabilities: [gpu] }]

  myos-engine:
    build: { context: ., dockerfile: Dockerfile }
    container_name: myos_engine
    restart: unless-stopped
    stop_grace_period: 60s
    ports: ["8501:8501"]
    volumes:
      - ./logs:/app/logs
    environment:
      - API_BASE_URL=http://myos-api:8000
    depends_on:
      myos-api: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501/_stcore/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: myos_tunnel
    restart: unless-stopped
    command: tunnel --no-autoupdate --url http://myos-engine:8501
    depends_on: [myos-engine]
```

### Cloudflare Tunnel Operations

```bash
docker compose up -d
docker compose logs cloudflared | grep -o 'https://.*\.trycloudflare\.com'   # public link
docker compose down
```

---

## 5. Cold-Start Database Provisioning Sequence

Before the first launch, initialize the catalog and compute the semantic index. Both scripts run inside the image; run them through the **API** service so the environment matches production:

```bash
# Step 1: schema + relational exercise data from CSV
docker compose run --rm myos-api python scripts/intialize_db.py

# Step 2: 384-d normalized embeddings + vec_exercises index
docker compose run --rm myos-api python scripts/seed_vectors.py
```

The account-recovery tables (`trainee_emails`, `password_reset_tokens`) and per-user schema are provisioned automatically on boot; no manual step is required.

### Verification

```bash
docker compose run --rm myos-api sqlite3 /app/db/catalog.db \
  "SELECT COUNT(*) FROM exercises; SELECT COUNT(*) FROM exercise_secondary_muscles;"
```

---

## 6. CPU Performance Tuning & Thread Pinning

1. **`OMP_NUM_THREADS`** — set equal to the number of **physical** cores, not logical hyperthreads:
   * 4C/8T → `OMP_NUM_THREADS=4` · 6C/12T → `6` · 8C/16T → `8`
   * Over-subscribing threads causes context-switch overhead and lowers TPS. `LLM_THREADS` overrides the tokenizer/llama thread count independently when needed.
2. **CPU governor** (Linux hosts):
   ```bash
   echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
   ```
3. **GPU offload beats thread tuning.** Full 4B offload on a 4 GB card raises sustained throughput from ~5–15 TPS (CPU) to 30+ TPS, with the first-token latency dominated by prompt evaluation.

---

## 7. Offline / Air-Gapped Model Artifact Staging

For hosts without outbound HTTPS to Hugging Face:

1. Download the production GGUF manually:
   * **Source**: `unsloth/Qwen3.5-4B-GGUF` → **File**: `Qwen3.5-4B-Q4_K_M.gguf`
2. Optionally download the judge for offline evaluation:
   * **Source**: `unsloth/Qwen3.5-9B-GGUF` → **File**: `Qwen3.5-9B-Q4_K_M.gguf`
3. Download the embedding weights: `BAAI/bge-small-en-v1.5` (into the container's HF cache volume).
4. Stage the files into the mounted directories:
   ```bash
   mkdir -p ./models
   cp /path/to/Qwen3.5-4B-Q4_K_M.gguf ./models/
   ```
5. `get_or_download_model_path()` detects pre-existing files and bypasses the Hugging Face download entirely. For reproducible deployments, pin `MODEL_SHA256` / `MODEL_REVISION` so a corrupted transfer is rejected at load time.

---

## 8. Operational Observability, Auth Ops & Health Monitoring

### Telemetry

Turn latencies, Time-to-First-Token (TTFT), token counts, and generation throughput (TPS) stream out-of-band to `logs/myos.log`:

```bash
# Real-time transaction telemetry
docker compose exec myos-api tail -f /app/logs/myos.log | grep "\[TELEMETRY\]"

# CPU thermal throttling / thread-contention alerts (fires below 8 TPS)
docker compose exec myos-api grep "\[PERF DEGRADATION\]" /app/logs/myos.log

# On-demand latency & throughput audit
docker compose exec myos-api python scripts/check_engine_health.py
```

### Password & Account Recovery Operations

```bash
# Operator reset (revokes ALL sessions for that ledger; no email required)
docker compose exec myos-api python scripts/reset_password.py <trainee_id>

# Custom storage locations (native runs)
python scripts/reset_password.py <trainee_id> \
  --catalog db/catalog.db --users-dir db/users --backups-dir db/backups
```

Reset emails are sent via SMTP when configured; with `SMTP_HOST` unset, links are logged to `logs/myos.log` (console-dev mode — never leave this unset on a shared host). The full auth specification is in [`AUTHENTICATION.md`](AUTHENTICATION.md).

### Health Endpoints

| Endpoint | Meaning |
| :--- | :--- |
| `GET /healthz` | Liveness; `draining` once shutdown begins. **`model: false` only means eager warmup was skipped — the model still lazy-loads on first inference** |
| `GET /readyz` | Readiness; `503` until model warmup and catalog init complete |

---

## 9. Backup, Disaster Recovery & WAL Checkpointing

User accounts are isolated SQLite files (`db/users/<trainee_id>.db`) in WAL mode; the shared catalog (`db/catalog.db`) additionally holds account-recovery identity. Backups require consistent point-in-time snapshots:

### 1. Manual WAL Checkpoint Flush

```bash
docker compose exec myos-api sqlite3 /app/db/catalog.db "PRAGMA wal_checkpoint(TRUNCATE);"
for db_file in ./db/users/*.db; do
  sqlite3 "$db_file" "PRAGMA wal_checkpoint(TRUNCATE);"
done
```

### 2. Automated Backup Archive

```bash
tar -czvf "myos_backup_$(date +%Y%m%d_%H%M%S).tar.gz" \
  ./db/catalog.db ./db/users/*.db
```

### 3. Migration Snapshots (ADR 005)

Lazy schema migrations already produce **atomic online snapshots** via `sqlite3.Connection.backup()` into `db/backups/<user>/`, with a 3+1 retention policy (three rolling session snapshots + one immutable pre-migration snapshot). Include `./db/backups/` in archives for belt-and-braces recovery.

### 4. Restoring a Ledger

1. Stop the stack: `docker compose down`
2. Extract into `./db/users/<username>.db` (and restore `catalog.db` if account recovery data is needed).
3. Remove dangling WAL/SHM files:
   ```bash
   rm -f ./db/users/<username>.db-wal ./db/users/<username>.db-shm
   ```
4. Restart: `docker compose up -d`. A ledger newer than the engine's target schema is refused with a clear upgrade message; an older one migrates automatically with a snapshot taken first.
