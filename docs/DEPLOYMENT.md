# Myos: Production Deployment, Containerization & Operational Runbook

This document details production deployment procedures, container orchestration, host hardware tuning, database provisioning, and disaster recovery protocols for the Myos training engine.

> **Android closed trial (Fly.io, FastAPI only):** the §10 runbook targets the
> API service alone on one always-on Machine with a durable volume. See
> [§10 Fly.io Closed-Trial API Deployment](#10-flyio-closed-trial-api-deployment-fastapi-only).
> The GPU/`docker-compose` topology below remains the local-development and
> engine-evaluation reference; it is not the trial topology.

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
| `GOOGLE_WEB_CLIENT_ID` | unset (⇒ `/auth/google*` returns 503) | **Secret-ish config**: the OAuth web client ID Google ID tokens are verified against (issue #113). Use the *Web* client ID from the Google Cloud console; Android requests its ID token with this value as `serverClientId`, so it is the only audience the API needs. Unset disables Google sign-in only — password auth is unaffected |
| `UI_BASE_URL` | `http://localhost:8501` | CORS origins: one, or several comma-separated (web app host + local dev). Not used for reset links |
| `RESET_LINK_BASE_URL` | `http://localhost:8000` | Reset-link / App Link base; must match the App Link host |
| `ANDROID_APP_PACKAGE` | `com.mayos.mayos_mobile` | App Link `assetlinks.json` package |
| `ANDROID_APP_SHA256_CERT_FINGERPRINTS` | unset (⇒ 404) | App Link signing-cert SHA-256 fingerprints (case/colons optional; normalised) |
| `API_BASE_URL` | `http://localhost:8000` | Streamlit → API base (compose sets `http://myos-api:8000`) |
| `RESET_TOKEN_TTL_MINUTES` | `30` | Reset-link lifetime (clamped 5–120) |
| `SMTP_HOST` | unset | **Unset ⇒ console-dev backend** (reset links logged, not sent). Configure for real deployments |
| `SMTP_PORT` / `SMTP_USE_TLS` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | `587` / `true` / — / — / `no-reply@myos.local` | SMTP transport |
| `RATE_LIMIT_LOGIN` / `_REGISTER` / `_PASSWORD` / `_RESET` / `_CHAT` / `_ONBOARDING` | `5/min` / `5/min` / `10/min` / `3/hour` / `30/min` / `30/min` | Per-route limits |
| `RATE_LIMIT_USERNAME_CHECK` | `30/min` | `GET /auth/username-available`, the as-you-type username picker (#113) |
| `MODEL_RATE_LIMIT_REQUESTS` | `20` | Per-immutable-account model requests/minute; one turn counts once. `0` disables |
| `MODEL_DAILY_TOKEN_LIMIT` | `200000` | Per-account input+output tokens/UTC day; `0` disables |
| `MODEL_PRICING_JSON` | built-in defaults | `{model: {"input": usd, "output": usd}}` per 1M tokens; unknown model ⇒ cost 0 + warning |
| `MODEL_SPEND_ALERT_USD` | `50` | Owner alert when projected month spend reaches this (evaluated on the hourly sweep) |
| `COACH_AI_ENABLED` | `false` | Enables the optional coach AI assistant (#45); refused unless `COACH_AI_EVAL_REPORT` records a passing **live** report for the current prompt version *and* the configured coach model/backend |
| `COACH_AI_EVAL_REPORT` | unset | Path to the recorded coach privacy + evaluation report JSON (see §4, "Enabling the optional coach AI assistant") |
| `RATE_LIMIT_COACH_ASSISTANT` | `30/minute` | Per-client limit on `POST /coach/assignments/{id}/assistant`; the per-account model limits (`MODEL_*`) still apply |
| `PRIVACY_CONTACT_EMAIL` | unset (⇒ placeholder + warning) | Owner contact rendered on the public privacy policy at `GET /privacy`; unset still serves the page |
| `OWNER_ALERT_EMAIL` | unset | Alert recipient (set via `fly secrets set` on Fly); unset logs the warning only and retries delivery each sweep |
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

**Rate-limit keying on Fly.** Every route limit (`RATE_LIMIT_*`) is keyed by
client address — plus a bearer-token suffix for authenticated calls — in
`svc/rate_limit.py::_key`. Behind Fly's proxy the socket address is the proxy
for *every* request, so when `FLY_APP_NAME` is set (Fly injects it into each
Machine; no configuration needed) the key uses the proxy-set `Fly-Client-IP`
header instead. Without it all callers would share one bucket, and a single
visitor could spend the whole `PASSWORD_LIMIT` budget that protects sign-in,
password change, and the public `GET|POST /account/delete-request` form.
Outside Fly the socket address is used and that header — which any client could
forge — is ignored.

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

### Enabling the optional coach AI assistant (issue #45)

`POST /coach/assignments/{assignment_id}/assistant` is **off by default**
(`COACH_AI_ENABLED=false`): with the flag off the route answers `404` and no
model is built or called. Enabling it requires **both** gates to be recorded
for the current prompt version (ADR 049):

1. **Privacy suite** — hermetic, mock model, no network:

   ```bash
   .venv/bin/python -m pytest tests/test_coach_ai_privacy.py tests/test_coach_ai.py -q
   ```

2. **Coach evaluation** — fixture cases scored by the deterministic rubric
   (`tests/eval/coach_rubric.py`) against the *production* prompt. Run it
   against the hosted coach model and write the enablement report in one step;
   the runner also runs the privacy suite and records its verdict:

   ```bash
   # Plumbing run first (in-repo mock model; never passes the gate, exit 0):
   .venv/bin/python tests/eval/run_coach_evaluation.py --mock --no-privacy

   # Real run: hosted model + privacy suite, records both gates:
   .venv/bin/python tests/eval/run_coach_evaluation.py --write-report reports/coach_ai_eval.json
   ```

3. **Enable** — point the service at the recorded report. The service
   re-validates it (`service.coach_ai.validate_report`, the same validator
   `--check-report` uses): expected `report_version`, `mode: "live"` (a
   `mode: "mock"` plumbing report is refused), `pass=true`, `prompt_hash` for
   the current prompt version, the currently configured coach `model` and
   `backend`, both gate results — and it re-derives the evaluation verdict from
   the recorded runs, so a hand-edited `pass` flag cannot disagree with them.
   If anything is missing it logs
   `Coach AI requested but refused; the feature stays off: …` and the feature
   stays off (the flag alone is never enough). The parsed verdict is cached on
   report path + mtime + size + model + backend, so requests do not re-parse
   the file; re-recording the report applies on the next request, without a
   restart:

   ```bash
   export COACH_AI_ENABLED=true
   export COACH_AI_EVAL_REPORT=reports/coach_ai_eval.json   # committed or owner-produced
   ```

Re-check a report without loading any model (CI-friendly, exit 1 when stale,
mock, recorded for another model, or failing):

```bash
.venv/bin/python tests/eval/run_coach_evaluation.py --check-report reports/coach_ai_eval.json
```

Changing the system prompt, the context rendering, or the field selection
changes `service.coach_ai.prompt_version_hash()` (it hashes the rendered
canonical fixture, not just the prompt text), and changing `COACH_MODEL` /
`LLM_BACKEND` changes the model identity the report is bound to — either
invalidates an existing report: re-run step 2 before enabling again. The report is a JSON file, safe
to commit — it contains fixture questions/answers, never production data.

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

User accounts are isolated SQLite files (`db/users/<trainee_id>.db`) in WAL mode; the shared catalog (`db/catalog.db`) additionally holds account-recovery identity. Backups require consistent point-in-time snapshots, so the daily job snapshots every database with the SQLite backup API (`sqlite3.Connection.backup()`) rather than copying files: a file copy of a WAL database can capture a torn state or miss committed pages still in the `-wal` file.

### 1. Daily online backups (issue #41)

One job backs up the catalog and **every ledger of a live account** into a per-day directory:

```
db/backups/daily/<YYYYMMDD>/catalog.db        # whole catalog + account/recovery identity
db/backups/daily/<YYYYMMDD>/ledgers/<id>.db   # one consistent copy per live-account ledger
```

Ledger copies live under the snapshot's `ledgers/` subdirectory so a ledger id
of `catalog` can never collide with the catalog copy, and a restore never writes
a ledger over the live catalog.

* **Online and consistent.** Each file is written with `Connection.backup()` while the service keeps serving; no checkpoint-and-copy step is needed.
* **Runs in the API Machine.** The job is scheduled in-process in the always-on FastAPI writer, once at startup and every `MAYOS_DAILY_BACKUP_INTERVAL_SECONDS` (default `3600`; `0` disables). It never runs on a detached scheduled Machine, which cannot mount `/data` (see [§10](#10-flyio-closed-trial-api-deployment-fastapi-only)). Force a pass with `scripts/backup_now.py`.
* **Retriable and idempotent.** A run stages into a hidden temp directory and atomically renames it into place; a failure publishes nothing, and the same day can be retried. A valid snapshot for the current UTC day is left alone, so the hourly default just retries a failed day sooner rather than making extra copies. A deletion landing mid-run is detected under the catalog lock before the rename, so its staged ledger copy is dropped rather than republished.
* **Bounded retention.** Local snapshots, and R2 snapshots when configured, older than `MAYOS_BACKUP_RETENTION_DAYS` (default `30`, clamped to `1..30`) are pruned. The 30-day ceiling exists because ADR 015 discloses that a **restricted whole-catalog recovery backup may retain deleted rows for up to 30 days** — a longer window would exceed what users were told.
* **`deletions.db` is never inside a snapshot.** It is the durable record (ADR 015/039) that keeps a restored catalog from resurrecting a deleted account. The daily job deliberately does not copy it; keep it backed up append-only and separately (below).

### 1a. Off-site copy in Cloudflare R2 (issue #164)

The in-process daily job also copies each completed local snapshot to a private
Cloudflare R2 bucket through its S3-compatible API. In the Cloudflare dashboard,
create the bucket and leave public access disabled, then create an R2 API token
with **Object Read & Write** permission scoped to that bucket only. Use the S3
endpoint shown by Cloudflare for the account (or the jurisdiction-specific
endpoint for a jurisdictional bucket). MAYOS configures the S3 client with
region `auto`.

Set these four Fly secrets; the API key and secret are the R2 token's Access Key
ID and Secret Access Key:

```bash
fly secrets set \
  R2_ENDPOINT="https://ACCOUNT_ID.r2.cloudflarestorage.com" \
  R2_BUCKET="YOUR_BUCKET_NAME" \
  R2_ACCESS_KEY_ID="YOUR_ACCESS_KEY_ID" \
  R2_SECRET_ACCESS_KEY="YOUR_SECRET_ACCESS_KEY"
```

Replace the example values with the bucket name, endpoint, and token credentials
from Cloudflare before running the command.

The remote layout is `daily/<YYYYMMDD>/catalog.db` plus
`daily/<YYYYMMDD>/ledgers/<id>.db`. `_COMPLETE.json` is written last; a date
without it is incomplete and is ignored by restore. Failed remote uploads are
logged without credentials, do not affect the local snapshot or API, and are
retried by the next daily-job pass. If any of the four secrets is unset, startup
logs once that R2 backups are disabled; local daily backups continue normally.

To verify a pass, run `python scripts/backup_now.py` on the API Machine, check
the completion result in `fly logs`, then open the bucket in the Cloudflare
dashboard and confirm today's `daily/<YYYYMMDD>/` contains `_COMPLETE.json`,
`catalog.db`, and the `ledgers/` directory. An existing marker means the date
is already complete; retrying the command safely finishes a partial date.

To restore a selected R2 date on Fly, download it into `/data/backups` and
schedule the existing boot-time restore flow:

```bash
fly ssh console -C "python scripts/restore_backup.py --r2 20260929 --on-next-boot"
fly machine restart YOUR_MACHINE_ID
```

Then follow the pending-restore and readiness checks in [§10.7](#107-daily-backups-and-restore-issue-41).
`--r2 YYYYMMDD` without `--on-next-boot` downloads and restores immediately
while the API is stopped; the operator needs R2 access for the download. Both
paths keep the current `deletions.db`, replay its records, and quarantine
restored ledgers without a live account. The R2 copy of
each deleted account's ledger is removed from every date; replay retries that
cleanup. Restricted whole-catalog copies can still contain deleted catalog rows
for up to the disclosed 30-day recovery window, and the durable deletion record
must remain separately protected and append-only.

> **Disclosure text (ADR 015).** Restricted whole-catalog recovery backups may
> retain deleted rows (for example, an account's former catalog row) for up to
> **30 days** after deletion, as disclosed to users. User-specific copies are
> removed with the account: the live ledger, its `db/backups/<ledger>/`
> migration snapshots, **and its copy inside every local and R2 daily snapshot** are deleted.
> The catalog rows inside whole-catalog snapshots are the documented exception.

### 2. Durable deletion record (outside every snapshot)

Back the deletion record up on its own, append-only; never roll it back:

```bash
# Append-only copy, kept apart from the catalog archive.
cp ./db/deletions.db "/backups/deletions/deletions_$(date +%Y%m%d_%H%M%S).db"
```

> **Why `deletions.db` must outlive the catalog snapshot (ADR 015/039).** The
> durable deletion record is what stops a restored catalog from resurrecting an
> account its owner deleted. It deliberately lives beside the catalog but outside
> every snapshot. Restoring it alongside the catalog (or restoring an older copy
> over the live one) can undo deletions. The restore procedure below therefore
> keeps the **current** `deletions.db` and replays it.

### 3. Migration Snapshots (ADR 005)

Lazy schema migrations already produce **atomic online snapshots** via `sqlite3.Connection.backup()` into `db/backups/<user>/`, with a 3+1 retention policy (three rolling session snapshots + one immutable pre-migration snapshot). These are per-ledger and are removed with the account.

### 4. Restoring from a daily snapshot

**Immediate (local/offline) restore.** When the API is stopped and holds no
catalog, restore the snapshot directly; `restore_daily_backup` already reapplies
the current deletion record:

```bash
docker compose down

# Restore the chosen snapshot into the live data dir and replay deletions.
python scripts/restore_backup.py --latest \
  --catalog db/catalog.db --users-dir db/users --backups-dir db/backups

docker compose up -d
```

An explicit `python scripts/reapply_deletions.py --catalog db/catalog.db
--users-dir db/users --backups-dir db/backups` pass afterwards is optional — it
is a belt-and-braces confirmation only, because `restore_backup.py` already ran
the full replay.

**Boot-time (Fly) restore.** On Fly the single API Machine is the only writer
that can mount `/data` and cannot be scaled to zero for an offline restore, and
restoring while it serves is unsafe. Schedule the restore instead; the Machine
applies it at the next boot, before it serves (see
[§10.7](#107-daily-backups-and-restore-issue-41)):

```bash
python scripts/restore_backup.py --latest --on-next-boot
# then restart the API Machine (Fly) — see §10.7.
```

`scripts/restore_backup.py` restores `catalog.db` in place and writes the
snapshot's ledgers into `db/users/`, then calls the full deletion replay
(`reapply_deletions()`). A ledger newer than the engine's target schema is
refused with a clear upgrade message; an older one migrates automatically with a
snapshot taken first.

**Orphaned ledgers.** An account created *after* the snapshot has no row in the
restored catalog, so its `db/users/<id>.db` would strand its username (registration
refuses a username whose ledger exists, and there is no account to log in to or
delete). After the replay, the restore moves every live ledger file (and its
`-wal`/`-shm`) not owned by a live account in the restored catalog into
`db/backups/restore-orphans/<timestamp>/` — **moved, not deleted**, so the owner
can recover it, and pruned by the same bounded retention as daily snapshots. The
moved ids are reported in the restore summary, and the username can then be
registered again.

**The replay force-deletes every recorded account.** If the restored catalog
reintroduced a deleted account, its row is forced back to `status='deleted'`
(epoch bumped, relationships ended/cleared) and its ledger and
`db/backups/<ledger_id>/` are removed again. This is automatic at service
startup too (an incremental replay), but the explicit full replay after a
restore is the guaranteed path because a restored catalog may postdate the
records' `applied_at` markers. If a deleted username now points at a new
account, the replay keys on the immutable `account_id`, so the new account is
untouched. See ADR 039.

### 5. Dry-checking a snapshot

`db/backups/daily/<date>/` is an ordinary SQLite tree; inspect it without
touching the live data:

```bash
sqlite3 db/backups/daily/20260928/catalog.db "SELECT COUNT(*) FROM exercises;"
sqlite3 db/backups/daily/20260928/ledgers/<ledger_id>.db "PRAGMA user_version;"
```

---

## 10. Fly.io Closed-Trial API Deployment (FastAPI only)

> **Status:** configuration and runbook only. This repository has not deployed or
> verified a live Fly.io account. Treat the steps below as the procedure to
> execute and the checks that prove it worked; do not describe the trial as live
> until they pass.

The closed Android trial is designed to run **one always-on FastAPI writer** in
Frankfurt (`fra`) on a `shared-cpu-1x` Machine with a **10 GB volume** mounted at
`/data`. Streamlit is legacy and is not deployed as a product service
(retirement: #46); the image is FastAPI only.

### 10.1 Topology

| Piece | Setting | Why |
| :--- | :--- | :--- |
| Image | `Dockerfile.fly` + `requirements-fly.txt` | `python:3.12-slim`, CPU-only PyTorch, no `llama-cpp-python`/CUDA/Streamlit |
| Inference | `LLM_BACKEND=openai` | hosted OpenAI-compatible endpoint (ADR 012); no GGUF in the image |
| Process | `uvicorn svc.app:app --workers 1` | SQLite is a single writer and the Machine owns the volume |
| Region/VM | `primary_region = "fra"`, `shared-cpu-1x`, 2 GB | within the locked trial size (ANDROID-PLAN §1); 2 GB is chosen to leave headroom for the CPU BGE embedding model, which measured near 1 GB RSS in local development — confirm headroom on the deployed Machine |
| Volume | `[[mounts]]` `mayos_data` → `/data`, `initial_size = "10gb"` | catalog, ledgers, and the migration/backup work area |
| Snapshots | `scheduled_snapshots = false` | ADR 015: Fly snapshots disabled; backups are owned by #41 |
| Availability | `auto_stop_machines = "off"`, `auto_start_machines = false`, `[[restart]] policy = "always"` | idle periods must not stop the always-on writer |
| Probes | `[[http_service.checks]]` on `/healthz` and `/readyz`, `force_https = true` | Fly TLS plus liveness/readiness |
| No release Machine | no `[deploy] release_command` | the release Machine cannot mount the volume |

### 10.2 Persistent data root

`MAYOS_DATA_DIR=/data` is set in `fly.toml`. Every storage default in
`database/database_manager.py` derives from it, so boot, seeding, the reset CLI,
and normal requests all use the volume:

```
/data/catalog.db      # shared catalog + account/recovery identity
/data/deletions.db    # durable account-deletion records (outside catalog snapshots)
/data/users/<id>.db   # per-account ledgers (WAL)
/data/backups/<id>/   # migration/rolling snapshots
/data/backups/daily/<YYYYMMDD>/  # daily catalog + live-account ledger snapshots (#41)
/data/backups/restore-orphans/<ts>/  # ledgers stranded by an older-snapshot restore (#41)
```

The deletion-record path is overridable with `MAYOS_DELETIONS_DB` (or the
`deletions_path` constructor argument); it defaults to `deletions.db` beside the
catalog, so it lives on the same durable volume and is removed/restored with it.
Account deletion removes the account's ledger plus `backups/<id>/` and writes to
this file; every startup replays it (ADR 039).

`MAYOS_REQUIRE_PERSISTENT_DATA=true` makes `validate_data_root()` fail closed when
`/data` is missing, not a directory, not writable, or not a real mount, and
`DatabaseManager.__init__` runs the same check before any `mkdir` or SQLite open.
Because several `agent/*` modules construct `DatabaseManager` at import time,
there are two possible failure modes when the volume is not ready:

- **Import/startup failure:** the process may fail while importing `svc.app`,
  before the FastAPI lifespan runs. The Machine then crash-loops and never serves
  `/readyz` at all.
- **Running but not ready:** if the process does reach the lifespan, storage
  validation marks it not-ready; `/readyz` returns 503 and any request that
  lazily builds the manager fails instead of creating the catalog or ledgers.

Either way, no catalog or ledger is written to the container's ephemeral
filesystem. Unset in local development, so the repo `./db` layout is unchanged.

### 10.3 One-time setup

```bash
# Run this block from the repository root (the directory containing fly.toml
# and data/).
# Set this to the globally unique app name declared in fly.toml; the commands
# below reuse it.
APP=mayos-api

# The production catalog CSV is operator-provided and is not tracked in this
# repo (its licensing/provenance is unknown and this runbook invents none).
# Dockerfile.fly copies it explicitly, so a build without it fails. Stop before
# launching/deploying if it is absent:
test -f data/processed_exercises.csv \
  || { echo "seed CSV MISSING: provide data/processed_exercises.csv before fly deploy" >&2; exit 1; }

fly launch --no-deploy --copy-config
fly volumes create mayos_data -r fra -s 10 --scheduled-snapshots=false

# Generate the JWT secret locally, set it, and drop the shell variable.
JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
fly secrets set JWT_SECRET="$JWT_SECRET"
unset JWT_SECRET

# Hosted-provider and SMTP secrets. Quote every value so the shell cannot treat
# it as a redirection; prefer `fly secrets import` from a private file when
# shell history matters. Never commit these values.
fly secrets set LLM_API_KEY="<hosted-provider-key>"
fly secrets set SMTP_HOST="<smtp-host>" SMTP_USER="<smtp-user>" \
  SMTP_PASSWORD="<smtp-password>" SMTP_FROM="<from-address>"

# Google sign-in audience (issue #113). Unset leaves Google sign-in off (the
# /auth/google* endpoints answer 503) while password auth keeps working.
fly secrets set GOOGLE_WEB_CLIENT_ID="<web-client-id>.apps.googleusercontent.com"

# Deploy a single Machine (no HA pair) so only one writer mounts the volume.
fly deploy --ha=false
```

The operator must place the real processed exercise catalog at
`data/processed_exercises.csv` in the working tree before building; run the
setup block from the repository root. This repository does not track the file
and provides no download step; `Dockerfile.fly` copies it explicitly so the
build fails when it is absent. `SEED_CSV_PATH` is a deliberate initializer
override, not a build input.

`JWT_SECRET` and `LLM_API_KEY` are mandatory: without the JWT secret the service
refuses to mint tokens, and without the hosted key readiness fails loudly
(ADR 012) instead of 401ing every request.

### 10.4 One-time catalog init + vector seed (inside the API Machine)

The volume is mounted only on the running API Machine, so seed through it — not
via a release command or a separate scheduled Machine:

```bash
fly ssh console -C "python scripts/intialize_db.py --seed-only"
fly ssh console -C "python scripts/seed_vectors.py"
```

`--seed-only` honors `MAYOS_DATA_DIR` and skips the script's local self-test
rows (no `test_user` ledger or throwaway session/set/vector). The initializer
defaults to `data/processed_exercises.csv` and exits with an error before any
database work when that file is missing; it never falls back to the
`tests/fixtures` catalog. `SEED_CSV_PATH` is the only override and exists for
deliberate input. Constructing `DatabaseManager` still provisions the engine's
empty `default` ledger, exactly as a normal boot does; that is expected.
`seed_vectors.py` uses the BGE model baked into the image. Re-running the
initializer is safe: a populated catalog is skipped.

`/readyz` checks the running process, model, and writable volume; it does not
check exercise or vector row counts. Finish both seed commands and verify the
catalog before giving the Fly hostname to trial users.

### 10.5 Verification (run these before calling it live)

1. **Machine + checks:** `fly status` shows one Machine in `fra`, and
   `fly checks list` shows both `/healthz` and `/readyz` passing.
2. **Volume mounted:** `fly ssh console -C df` shows the 10 GB volume on `/data`.
3. **HTTPS health:** `curl -fsS "https://${APP}.fly.dev/healthz"` and
   `curl -fsS "https://${APP}.fly.dev/readyz"` return 200; `/readyz` details
   report `storage: true`. (`APP` is set in §10.3.)
4. **Catalog seeded:** `fly ssh console -C "sqlite3 /data/catalog.db 'SELECT COUNT(*) FROM exercises;'"` is non-zero.
5. **Catalog media:** `curl -fsSI "https://${APP}.fly.dev/media/images/<image_path>"`
   and `curl -fsSI "https://${APP}.fly.dev/media/videos/<gif_path>"` return 200
   (take the paths from
   `sqlite3 /data/catalog.db "SELECT image_path, gif_path FROM exercises LIMIT 1;"`);
   an image built before issues #161/#53 answers 404 and needs the redeploy in
   §10.8. The route is public: no `Authorization` header.
6. **App round-trip over HTTPS:** register → login → chat SSE against the Fly
   hostname from the Android client.
7. **Restart persistence:** record the counts below, restart the app, and
   confirm they are unchanged.

```bash
# APP is set in §10.3 and must match `app` in fly.toml.
fly ssh console -C "sqlite3 /data/catalog.db 'SELECT COUNT(*) FROM exercises;'"
fly ssh console -C "ls -la /data/users"
fly apps restart "$APP"
fly ssh console -C "sqlite3 /data/catalog.db 'SELECT COUNT(*) FROM exercises;'"
fly ssh console -C "ls -la /data/users"
```

If `/readyz` returns 503, or the Machine never becomes healthy, inspect
`fly logs` for the actual cause, including storage validation failures and LLM
warmup failures.

### 10.6 Operator password reset

```bash
fly ssh console -C "python scripts/reset_password.py <trainee_id>"
```

The CLI inherits `MAYOS_DATA_DIR` from the Machine and writes to `/data`, so the
reset lands on the same catalog/ledger the API uses.

### 10.7 Daily backups and restore (issue #41)

The daily backup job runs **in-process in this API Machine** (once at startup,
then every `MAYOS_DAILY_BACKUP_INTERVAL_SECONDS`, default `3600`; `0` disables),
writing consistent SQLite snapshots to `/data/backups/daily/<YYYYMMDD>/` and,
when R2 is configured, uploading a completed copy to the bucket described in
[§9.1a](#1a-off-site-copy-in-cloudflare-r2-issue-164). It must
not move to a detached scheduled Machine, which cannot mount `/data`. It creates
at most one snapshot per UTC day, so the hourly default only retries a failed day
sooner. Retention for local and configured R2 snapshots is
`MAYOS_BACKUP_RETENTION_DAYS` (default `30`, clamped to `1..30`); the 30-day
ceiling matches ADR 015's disclosed restricted whole-catalog recovery window.
`/data/deletions.db` is never copied into a snapshot.

```bash
# Force one now (safe if today's snapshot already exists).
fly ssh console -C "python scripts/backup_now.py"
fly ssh console -C "ls -la /data/backups/daily"

# Schedule a restore of the newest snapshot; it applies on the next boot.
fly ssh console -C "python scripts/restore_backup.py --latest --on-next-boot"
fly machine restart <machine-id>        # or: fly apps restart mayos-api
```

`--on-next-boot` only validates the snapshot and atomically writes
`/data/backups/restore-pending.json`. The Machine's next boot applies it
**before it serves** (before readiness goes green): it restores `catalog.db` and
the snapshot's ledgers in place, runs the full deletion replay against the
current `/data/deletions.db`, quarantines any ledger stranded by the older
snapshot, then removes the marker. If the restore fails, the Machine **stays
not-ready with the marker still in place** and the failure logged loudly, so a
half-restored catalog is never served. The operator fixes the cause and restarts
the Machine; the boot retries and clears the marker on success. Verify after the
restart:

```bash
fly status
fly checks list                          # /healthz and /readyz must pass
fly ssh console -C "ls /data/backups/restore-pending.json"   # must be absent
```

Why not scale to zero and restore offline? The single API Machine is the only
writer that can mount `/data`; with zero Machines there is nothing to `ssh` into
and no volume to restore onto. The boot-time marker is the executable equivalent:
restore happens on the Machine that owns the volume, while nothing is serving.

`scripts/restore_backup.py` (without `--on-next-boot`) still restores
immediately for local/offline use, keeping the current `/data/deletions.db`. See
[§9](#9-backup-disaster-recovery--wal-checkpointing) for the full procedure and
the deletion-replay guarantees.

### 10.8 Exercise catalog pictures and GIFs served by `/media` (issues #161, #53)

The app's exercise cards show the catalog picture and the exercise-detail
screen shows the catalog GIF through the API's public
`GET /media/<image_path>` route (`svc/routers/media.py`), which resolves the
relative ExerciseDB paths (`images/0001-2gPfomN.jpg`, `videos/0001-2gPfomN.gif`)
under `BASE_DIR/data` — `/app/data/images/…` and `/app/data/videos/…` inside
the container. The route needs no auth and sends no per-player data.

- **The media ships in the image.** `.dockerignore` re-includes `data/images/`
  (~12 MB, 1,324 JPEGs) and `data/videos/` (~126 MB, 1,324 GIFs) — both
  gitignored like the CSV, so both must exist in the tree you deploy from —
  and `Dockerfile.fly` copies them to `/app/data/images` and `/app/data/videos`
  alongside the seed CSV. No volume is involved: the media are read-only build
  inputs, the volume stays the mutable data root.
- **Credit is required.** Gym visual's terms apply to this media: every use
  carries "© Gym visual — https://gymvisual.com/" and the media is never shown
  larger than its native 180×180 (the exercise-detail hero caps its box at
  180 dp; Settings → About → Credits holds the full notice). The provenance
  record and the 2026-09-29 decision to display it pending MAYOS's own licence
  are in `docs/design-review/53/MEDIA-PROVENANCE.md`. The app's kill switch is
  `--dart-define=MAYOS_EXERCISE_MEDIA=false`.
- **Everything else under `data/` stays out of the build context**, including
  `data/exercises.json`, `data/exercises.csv` and the databases.
- **Redeploy required.** A Machine running an image built before this change
  has no media: `/media/images/…` and `/media/videos/…` answer 404. From the
  repository root (with `data/images/` and `data/videos/` present), run:

  ```bash
  fly deploy --ha=false
  ```

  The build fails fast if either directory is missing, the same way it already
  fails without `data/processed_exercises.csv`.

### 10.9 Password reset: App Link and hosted fallback (issue #38, ADR 037)

The reset email links to `<RESET_LINK_BASE_URL>/reset-password?token=…`. When the
app is installed, Android opens that https URL as an **App Link** directly in the
app; otherwise the API's hosted page at the same path completes the reset in a
browser.

**One host, three places.** In production the hostname must be identical in:

1. `RESET_LINK_BASE_URL` (the link the API emails),
2. the Android App Link intent-filter host (`-PappLinkHost`, default
   `mayos-api.fly.dev`), and
3. the host serving `/.well-known/assetlinks.json` (the same API).

A mismatch (for example an `app` redirect, www, or a different region hostname)
breaks verification or the link.

**Required configuration/secrets on the API Machine** (`${APP}` is the app name
from `fly.toml`; the first two are configuration and may live in `[env]`):

| Name | Value | Notes |
| :--- | :--- | :--- |
| `RESET_LINK_BASE_URL` | `https://${APP}.fly.dev` | Reset-link / App Link base. No `UI_BASE_URL` fallback; unset ⇒ localhost dev base |
| `ANDROID_APP_PACKAGE` | `com.mayos.mayos_mobile` | Defaults if unset |
| `ANDROID_APP_SHA256_CERT_FINGERPRINTS` | comma-separated SHA-256 | Upload key **and** Play App Signing cert; case/colons optional, normalised; none ⇒ 404 |
| `SMTP_HOST` | SMTP relay host | **Unset ⇒ console-dev** (reset links only logged; unsafe on a shared host) |
| `SMTP_PORT` | `587` | |
| `SMTP_USE_TLS` | `true` | `false` uses implicit TLS |
| `SMTP_USER` / `SMTP_PASSWORD` | relay credentials | Optional for an unauthenticated relay |
| `SMTP_FROM` | from address | Defaults to `no-reply@mayos.local` |

```bash
# Reset-link base (must equal the -PappLinkHost used for the Android build).
fly secrets set RESET_LINK_BASE_URL="https://${APP}.fly.dev"

# App Link association (no fingerprint => assetlinks.json returns 404).
fly secrets set ANDROID_APP_SHA256_CERT_FINGERPRINTS="AA:BB:CC:…,DD:EE:FF:…"

# Outbound email (required for the reset mail to actually send).
fly secrets set SMTP_HOST="<smtp-host>" SMTP_USER="<smtp-user>" \
  SMTP_PASSWORD="<smtp-password>" SMTP_FROM="<from-address>"
# Optional: SMTP_PORT, SMTP_USE_TLS.
```

**Get the signing-cert SHA-256 fingerprint(s):**

```bash
# Debug/local upload key:
keytool -list -v -keystore ~/.android/debug.keystore \
  -alias androiddebugkey -storepass android -keypass android | grep SHA256

# Release/upload keystore:
keytool -list -v -keystore <upload-keystore.jks> -alias <alias> | grep SHA256

# Play App Signing (the cert Play re-signs with for installs):
# Play Console -> your app -> Release -> Setup -> App signing -> SHA-256
```

Include **both** the upload key and the Play App Signing certificate when
distributing through Play, so debug/CI installs and Play installs both verify.

**Android build:** the App Link host is injected at build time (default
`mayos-api.fly.dev`, matching `fly.toml`). Build with the same host:

```bash
cd mobile
flutter build appbundle --release -PappLinkHost=mayos-api.fly.dev
# or: flutter build apk --debug -PappLinkHost=mayos-api.fly.dev
```

**Verify the association** (after the app is installed on a device/emulator):

```bash
# The API must serve the statement with the configured fingerprints:
curl -fsS "https://${APP}.fly.dev/.well-known/assetlinks.json"

# Android must list and have verified the domain:
adb shell pm get-app-links com.mayos.mayos_mobile
adb shell pm verify-app-links --re-verify com.mayos.mayos_mobile
# To clear a cached failure after fixing fingerprints:
adb shell pm set-app-links --package com.mayos.mayos_mobile 0 all
```

**Manual round-trip checklist (deployed configuration — not yet run).** Run it
once for a **player account** and once for a **coach account** (an account with
both player and coach capabilities; the same app/login serves both):

1. From the app, choose **Forgot password?**, enter the account's recovery email,
   and submit. The same confirmation appears for any address (anti-enumeration).
2. Confirm the email arrives. The body must say the link opens the MAYOS app if
   installed, otherwise a secure web page, is single-use, and expires in the
   configured `RESET_TOKEN_TTL_MINUTES`; the link is
   `https://${APP}.fly.dev/reset-password?token=…`.
3. Sign in to the account on a device first (tick **Keep me signed in** to cover
   the remember-me session) so there is a live session to revoke.
4. With the app installed, open the link: it opens **Reset password** with the
   code prefilled. Uninstall the app and open the same link to check the hosted
   page instead (the URL bar must drop the `token` query immediately, and the
   page must never log/show the token).
5. Set a new password. The old password is rejected; the pre-reset sessions are
   rejected `401` — both the normal bearer token **and** the remember-me token
   (ADR 010); login with the new password succeeds and the account keeps its
   capabilities (a coach still shows the coach console).
6. Re-open the same link (or reuse the token via `POST /auth/reset-password`):
   it fails with the single generic error and changes nothing.
7. Confirm no access-log line contains the token
   (`fly logs | grep reset-password` shows `token=[REDACTED]`), and the hosted
   response carries `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

### 10.10 Opt-in import of a consenting person's training ledger (issue #42, ADR 019)

The owner imports **one** consenting person's legacy ledger at a time. There is
no bulk mode and no override for a source that looks like development/test data:
the local data root mixes real histories with dev/test ledgers, so importing it
wholesale would create unwanted and insecure cloud accounts. The script takes a
consistent SQLite snapshot, migrates it, creates a new immutable account,
rewrites the ledger's embedded identity to the new ledger id, verifies per-table
record counts against the raw source, clears any source password (the person must
claim), and prints a single-use, expiring claim code exactly once.

**Snapshot locally first.** The source is usually a WAL database. Copying only
its `.db` file loses every committed row still in the `-wal` file, so take a
consistent single-file snapshot before uploading anything:

```bash
# 0a. Locally, snapshot the WAL database into one self-contained file.
sqlite3 source.db ".backup source-snapshot.db"
# or: python -c "import sqlite3; \
#   s=sqlite3.connect('source.db'); d=sqlite3.connect('source-snapshot.db'); s.backup(d); d.close()"

# 0b. Upload the snapshot (out of band; never commit it) to a path OUTSIDE
#     /data/users, which is the live ledger directory and is refused as a source.
fly ssh console -a "$APP" -C "mkdir -p /tmp/import"
fly sftp shell -a "$APP"
#   put /local/path/source-snapshot.db /tmp/import/source-snapshot.db

# 1. Import. The opt-in reference records how and when the person consented.
fly ssh console -a "$APP" -C \
  "python scripts/import_player.py /tmp/import/source-snapshot.db \
     --username <new-username> \
     --opt-in-reference '<how/when the person consented>' \
     --ttl-hours 72"

# 2. Hand the printed claim code to the person out of band. They redeem it in the
#    app's "Claim imported account" screen with their chosen password.
```

Notes:

- The script refuses a source named like a fixture (`test*`, `demo*`, `eval*`,
  `bughunt*`, `seed*`, `fixture*`, `ci_test*`; `default`/`bootstrap`/`alice`/
  `bob`/`bp` exactly or with a trailing `_`; any `*_default`), a source inside
  the repo's `tests/` or `data/` directories or inside the live `/data/users`
  directory, and a source whose snapshot fingerprint was already imported. This
  is only an accidental-import guard: renaming a file bypasses it, and one
  explicit file per run is the real guard. It may refuse a real name like
  `bob.db`; in that case rename the copied snapshot.
- The script also refuses a new username whose destination ledger file already
  exists, so it never overwrites an unenrolled `users/<id>.db`.
- A rolled-back import is a normal durable deletion and leaves an
  `account_deletions` record plus a deleted `accounts` row (ADR 015/039); the
  audit row is removed with the account. Re-importing the **same** source after
  its account was deleted is a genuinely new account.
- If any per-table record count differs between the raw source snapshot and the
  imported ledger, the import rolls the new account back through the normal
  durable deletion path and exits non-zero, so a failed import never leaves a
  half-imported live account and never deletes or modifies the source.
- The audit row stores no training data and no contact details. Remove the copied
  snapshot from `/tmp` after the import.

### 10.11 Android release for the Play closed trial (issue #43)

The Android half of the closed trial ships from Play Console as a free,
invite-only closed track. The owner checklist — upload keystore and
`mobile/android/key.properties`, the signed `flutter build appbundle --release`,
Play App Signing plus both certificate fingerprints in
`ANDROID_APP_SHA256_CERT_FINGERPRINTS`, the privacy-policy and account-deletion
URLs, the Data safety answers, content rating, and target audience — lives in
**[docs/PLAY_RELEASE.md](PLAY_RELEASE.md)**; this runbook only owns the API side
(`PRIVACY_CONTACT_EMAIL`, `GET /privacy`, `GET /account/delete-request`).

Two URLs must be live before the listing can be completed:

```bash
curl -sI https://<api-host>/privacy                     # 200, cacheable
curl -sI https://<api-host>/account/delete-request      # 200, no-store
```

The release build fails with a clear message (not a debug signature) when
`mobile/android/key.properties` is missing; debug builds and `flutter test` are
unaffected.

## 11. Web App on Cloudflare Pages (issues #129, #130; ADR 048)

The web client is the Flutter app built for the browser and hosted on Cloudflare
Pages (`<project>.pages.dev`), separate from the Fly API. One-time account,
token, project and origin setup: [CLOUDFLARE_PAGES_SETUP.md](CLOUDFLARE_PAGES_SETUP.md).

**Deploy** (from a machine with Flutter and Node; token and account ID from your
own environment, never the repo):

```bash
source ~/.config/mayos/cloudflare.env
GOOGLE_WEB_CLIENT_ID=<web client id> scripts/deploy_web.sh   # add --preview for a preview URL
```

The script runs `flutter build web --release --no-web-resources-cdn
--pwa-strategy=none` with `--dart-define=MAYOS_API_BASE_URL=https://mayos-api.fly.dev`
(and `GOOGLE_WEB_CLIENT_ID` when set), then `wrangler pages deploy build/web`.

| Input | Where | Purpose |
| :--- | :--- | :--- |
| `MAYOS_API_BASE_URL` dart-define | build | API origin; release builds require https |
| `GOOGLE_WEB_CLIENT_ID` dart-define | build | Google sign-in web client (#112, #115) |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | operator env | wrangler auth |
| `PAGES_PROJECT` | operator env | default `mayos` |
| `UI_BASE_URL` | Fly `[env]` | must list the Pages origin (CORS) |

**Routing and headers** live in `mobile/web/_redirects` and `mobile/web/_headers`
and are copied into the build:

* `_redirects`: `/* /index.html 200`, so any path serves the app and a reload works.
* `_headers`: a strict CSP (self-hosted CanvasKit and assets, `wasm-unsafe-eval`
  for CanvasKit, the API origin in `connect-src`/`img-src`, Google sign-in script
  and frames), `Cross-Origin-Opener-Policy: same-origin-allow-popups` (never
  `same-origin`, it breaks Google sign-in), HSTS, `nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`. Flutter's entry files are
  not content-hashed, so they are `no-cache`; `assets/` and `canvaskit/` cache for a day.
* If the API host changes, update both `MAYOS_API_BASE_URL` and the `_headers`
  CSP (the script refuses to build when they disagree).

**Rollback:** Cloudflare dashboard, Workers & Pages, the project,
**Deployments**, pick the previous good production deployment, then
**Rollback to this deployment**. (CLI alternative: check out the earlier commit
and rerun `scripts/deploy_web.sh`.)

**Verify:** open the Pages origin, confirm the login screen renders with no CSP
errors in the browser console, open a deep path such as `/anything` and reload
(must still load), and sign in against the Fly API. The last step needs #113 and
the Fly `UI_BASE_URL` change.
