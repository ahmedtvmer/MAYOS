# Myos: Production Deployment, Containerization & Operational Runbook

This document details production deployment procedures, container orchestration, host hardware tuning, database provisioning, and disaster recovery protocols for the Myos training engine (`docs/DEPLOYMENT.md`).

---

## 1. Host Hardware & Runtime Prerequisites

Myos runs entirely in-process on CPU hardware without external model daemons or network API requirements. The host environment must satisfy the following baseline specifications:

* **CPU Architecture**: x86_64 with mandatory **AVX2** (Advanced Vector Extensions 2) and **FMA** instruction sets.
* **Core Count & Threading**: Minimum 4 physical CPU cores (6+ physical cores recommended). Hyperthreading should be mapped to physical execution units via OpenMP pinning.
* **System Memory (RAM)**:
  * Minimum: 8 GB RAM.
  * Recommended: 16 GB RAM (allocates ~2.2 GB for the Qwen 2.5 3B Q4_K_M weights, ~500 MB for `bge-small-en-v1.5` embeddings, with the remainder dedicated to OS page cache and SQLite WAL buffers).
* **Host System Dependencies (Non-Docker Native Runs)**:
  ```bash
  sudo apt-get update && sudo apt-get install -y \
      build-essential \
      libgomp1 \
      sqlite3 \
      curl
  ```
 

---

## 2. Docker Architecture & Container Topology

The application is deployed as a unified, isolated container running Python 3.12, pre-linked against AVX2 CPU wheels for `llama-cpp-python` and the embedded `sqlite-vec` shared object.

```
+-------------------------------------------------------------------------+
|                              HOST SYSTEM                                |
|                                                                         |
|   Persistent Volumes:                                                   |
|   ├── ./models/  --------> Mounts: /app/models (GGUF Model Weights)     |
|   ├── ./db/      --------> Mounts: /app/db (catalog.db + WAL User Ledgers)|
|   └── ./logs/    --------> Mounts: /app/logs (Structured Telemetry Logs)|
|                                                                         |
|   +-----------------------------------------------------------------+   |
|   |                  Docker Container: myos_engine                  |   |
|   |                                                                 |   |
|   |   Streamlit Web Server (:8501)                                  |   |
|   |         │                                                       |   |
|   |         ▼                                                       |   |
|   |   LangGraph Runtime Engine                                      |   |
|   |         │                                                       |   |
|   |         ├── SafeChatLlamaCpp (libllama.so with OpenMP)          |   |
|   |         └── DatabaseManager (Thread-Local SQLite Connections)   |   |
|   |                                                                 |   |
|   +-----------------------------------------------------------------+   |
+-------------------------------------------------------------------------+
```


### Dockerfile Specification

```dockerfile
FROM python:3.12-slim-bookworm

# 1. Install OS build and runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Configure Python environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=6 \
    MODEL_PATH="/app/models/qwen2.5-3b-instruct-q4_k_m.gguf" \
    EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"

# 3. Install precompiled CPU AVX2 wheels for llama-cpp-python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        --extra-index-url [https://abetlen.github.io/llama-cpp-python/whl/cpu](https://abetlen.github.io/llama-cpp-python/whl/cpu) \
        llama-cpp-python

# 4. Install project requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy application source
COPY . .

# 6. Expose default Streamlit port
EXPOSE 8501

# 7. Health check verifies HTTP listener on port 8501
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 8. Start Streamlit web engine
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```


---

## 3. Production `docker-compose.yaml`

```yaml
services:
  myos-engine:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: myos_engine
    restart: unless-stopped
    ports:
      - "8501:8501"
    volumes:
      - ./models:/app/models
      - ./db:/app/db
      - ./logs:/app/logs
    environment:
      - MODEL_PATH=/app/models/qwen2.5-3b-instruct-q4_k_m.gguf
      - MODEL_DIR=/app/models
      - EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
      - OMP_NUM_THREADS=6
    deploy:
      resources:
        limits:
          cpus: '6.0'
          memory: 8G
        reservations:
          cpus: '4.0'
          memory: 4G
```


---

## 4. Cold-Start Database Provisioning Sequence

Before launching the web container, execute the two-phase database preparation sequence:

```bash
# Step 1: Initialize schema and populate relational exercise data from CSV
docker compose run --rm myos-engine python scripts/intialize_db.py

# Step 2: Compute 384-dimensional normalized vector embeddings and build vec_exercises index
docker compose run --rm myos-engine python scripts/seed_vectors.py
```


### Verification
Ensure `catalog.db` was seeded and generated successfully:
```bash
docker compose run --rm myos-engine sqlite3 /app/db/catalog.db \
  "SELECT COUNT(*) FROM exercises; SELECT COUNT(*) FROM exercise_secondary_muscles;"
```
Expected output: Non-zero record counts matching the processed dataset.

---

## 5. CPU Performance Tuning & Thread Pinning

Running local GGUF token inference efficiently on CPU requires matching thread pools to physical CPU cores, avoiding hyperthreading penalties:

1. **`OMP_NUM_THREADS` Allocation**:
   Set `OMP_NUM_THREADS` equal to the number of **physical performance cores**, *not* logical hyperthreads:
   * 4-Core / 8-Thread CPU $\implies$ `OMP_NUM_THREADS=4`
   * 6-Core / 12-Thread CPU $\implies$ `OMP_NUM_THREADS=6`
   * 8-Core / 16-Thread CPU $\implies$ `OMP_NUM_THREADS=8`
   * Allocating threads beyond the physical core count causes CPU context switching overhead and degrades generation speed (TPS).

2. **Linux CPU Governor Configuration**:
   On Linux hosts, set the CPU frequency scaling governor to `performance`:
   ```bash
   echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
   ```
  

---

## 6. Offline / Air-Gapped Model Artifact Staging

In air-gapped environments where outbound HTTPS traffic to Hugging Face is blocked:

1. Download the quantized GGUF model manually:
   * **Source**: `Qwen/Qwen2.5-3B-Instruct-GGUF`
   * **Target File**: `qwen2.5-3b-instruct-q4_k_m.gguf`
2. Download the SentenceTransformer embedding weights:
   * **Source**: `BAAI/bge-small-en-v1.5`
3. Transfer the artifacts directly into the mounted project directories:
   ```bash
   mkdir -p ./models
   cp /path/to/qwen2.5-3b-instruct-q4_k_m.gguf ./models/
   ```
  
4. `SafeChatLlamaCpp` detects the pre-existing file in `./models/` and bypasses Hugging Face Hub download logic automatically.

---

## 7. Operational Observability & Health Monitoring

### Real-Time Telemetry Tracking
Turn latencies, Time-to-First-Token (TTFT), and generation throughput (TPS) stream out-of-band to `logs/myos.log`:

```bash
# Monitor all transaction telemetry in real-time
docker compose exec myos-engine tail -f /app/logs/myos.log | grep "\[TELEMETRY\]"

# Filter strictly for CPU thermal throttling or thread contention alerts
docker compose exec myos-engine grep "\[PERF DEGRADATION\]" /app/logs/myos.log
```


### On-Demand Performance Health Audit
Execute the automated health audit script inside the running container:

```bash
docker compose exec myos-engine python scripts/check_engine_health.py
```


Sample audit output:
```text
==================================================
⚡ MYOS INTERNAL ENGINE HEALTH REPORT
==================================================
Total Evaluated Turns:   42
Average TTFT:            248.6 ms
P95 TTFT:                312.4 ms
Average Throughput:      13.82 TPS
Min / Max Throughput:    11.45 / 15.10 TPS
==================================================
```


---

## 8. Backup, Disaster Recovery & WAL Checkpointing

Because Myos isolates user accounts into individual SQLite files (`db/users/<trainee_id>.db`) running in WAL mode, backups require consistent point-in-time snapshots:

### 1. Manual WAL Checkpoint Flush
Before creating a backup archive, flush WAL journal frames into the main database files:

```bash
# Checkpoint catalog
docker compose exec myos-engine sqlite3 /app/db/catalog.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Checkpoint all active user ledgers
for db_file in ./db/users/*.db; do
  sqlite3 "$db_file" "PRAGMA wal_checkpoint(TRUNCATE);"
done
```


### 2. Automated Backup Archive
Create a compressed archive of all ledgers and catalog states:
```bash
tar -czvf "myos_backup_$(date +%Y%m%d_%H%M%S).tar.gz" \
  ./db/catalog.db \
  ./db/users/*.db
```


### 3. Restoring User Ledgers
To restore a specific trainee ledger:
1. Stop the container: `docker compose down`
2. Extract the user database into `./db/users/<username>.db`
3. Delete any dangling shared-memory or WAL files:
   ```bash
   rm -f ./db/users/<username>.db-wal ./db/users/<username>.db-shm
   ```
  
4. Restart the engine: `docker compose up -d`