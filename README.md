<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-000000?style=for-the-badge&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.42+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![sqlite-vec](https://img.shields.io/badge/sqlite--vec-0.1.9-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://github.com/asg017/sqlite-vec)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)

</div>

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h1 align="center">⚡ MYOS</h1>
  <p align="center">
    <b>Local-First, CPU-Optimized Training Ledger & Biomechanics Engine</b>
    <br />
    <i>Deterministic auto-regulation, sub-millisecond triage routing, and fractional volume attribution powered by local GGUF inference.</i>
    <br />
    <br />
    <a href="#quickstart">Quickstart</a>
    ·
    <a href="#system-architecture">Architecture</a>
    ·
    <a href="#technical-documentation">Documentation Index</a>
  </p>
</div>

---

## Overview

**Myos** is an offline, privacy-first workout ledger and biomechanics engine engineered to eliminate cloud dependencies, privacy leaks, and computational bloat in personal fitness software.

Commercial fitness trackers rely on rigid linear progressions and binary volume attribution that inflate synergistic muscle tracking. Conversely, naive AI agents route every prompt through an LLM, incurring 3–6 second CPU inference bottlenecks just to classify basic user intents.

Myos bridges this gap:
* **Zero-Cloud Architecture**: Runs entirely offline on local CPU hardware using quantized GGUF inference (`Qwen 2.5 3B`).
* **Sub-Millisecond Regex Fast-Path**: Intercepts routine mutations and acute medical red flags in ~0.015 ms, bypassing the local LLM entirely.
* **Biomechanical Auto-Regulation**: Quantizes weights to 2.5 kg Olympic increments, calculates dynamic RPE-adjusted effective 1RMs, and tracks synergists fractionally (0.5 sets).
* **Zero Database Contention**: Employs isolated per-user SQLite ledgers in WAL mode and an in-process `sqlite-vec` semantic catalog.

---

## Technical Documentation

Detailed architectural specifications, benchmarks, and mathematical proofs are maintained in dedicated modules within [`docs/`](docs/):

| Document | Focus & Contents |
| :--- | :--- |
| [**Architecture Specification**](docs/ARCHITECTURE.md) | Mermaid state graphs, deterministic fast-path routing nodes, chunk sanitization, and connection topologies. |
| [**Empirical Benchmarks**](docs/ARCHITECTURAL_BENCHMARKS.md) | Latency comparison matrix (237,212x speedup), context clamping scaling curves, and WAL concurrency stress tests. |
| [**Progression & Biomechanics**](docs/PROGRESSION_RULES.md) | Mathematical formulations for effective 1RMs, Olympic plate quantization algorithms, warmup ramps, and deload rules. |
| [**Deployment Runbook**](docs/DEPLOYMENT.md) | Docker orchestration, host CPU OpenMP thread pinning, air-gapped staging, and disaster recovery checkpointing. |

---

## System Architecture

```
                    +-----------------------------------------+
                    |             Streamlit UI                |
                    |  (Dashboard | Logger | Chat Assistant)  |
                    +--------------------+--------------------+
                                         |
                                         v
                    +-----------------------------------------+
                    |         LangGraph Assistant Graph       |
                    |         (Deterministic Fast-Path)       |
                    +----+-------------------------------+----+
                         |                               |
        (Regex Match)    v                               v    (Pass-Through)
    +---------------------------------+        +---------------------------------+
    |  Deterministic Engine Nodes     |        |     SafeChatLlamaCpp Engine     |
    |  - Clinical Intercept (<0.02ms) |        |    - Qwen 2.5 3B GGUF (Q4_K_M)  |
    |  - Explicit Swap / Candidate    |        |    - Clamped 4-Message Window   |
    |  - Frequency Split Mutation     |        |    - Compact Telemetry Snapshot |
    +----------------+----------------+        +----------------+----------------+
                     |                                          |
                     +-------------------+----------------------+
                                         |
                                         v
                    +-----------------------------------------+
                    |      DatabaseManager (Thread-Local)     |
                    +--------------------+--------------------+
                                         |
               +-------------------------+-------------------------+
               |                                                   |
               v                                                   v
    +----------------------+                            +----------------------+
    |  Private User Ledger |                            | Shared Catalog DB    |
    |  - Mode: WAL         |                            | - Mode: Read-Only    |
    |  - Batch Set Commits |                            | - sqlite-vec Ext     |
    |  - Cascade Deletes   |                            | - Secondary Idx FKs  |
    +----------------------+                            +----------------------+
```


> For detailed sequence diagrams, state machines, and streaming chunk sanitizers, refer to [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart

### Prerequisites
* Docker Engine with Docker Compose v2 installed.
* x86_64 CPU with AVX2 instruction support.

### 1. Launch with Docker (Recommended)

```bash
# Clone the repository
git clone [https://github.com/ahmedtvmer/myos.git](https://github.com/ahmedtvmer/myos.git)
cd myos

# One-time database initialization & semantic vector seeding
docker compose run --rm myos-engine python scripts/intialize_db.py
docker compose run --rm myos-engine python scripts/seed_vectors.py

# Start the application
docker compose up -d
```

Open **`http://localhost:8501`** in your browser. The quantized model weights (`qwen2.5-3b-instruct-q4_k_m.gguf`) will download automatically on first launch if not present in `./models/`.

<details>
  <summary><b>Local Python Installation (Native)</b></summary>
  <br />

  ```bash
  uv venv
  source .venv/bin/activate
  uv pip install --extra-index-url [https://abetlen.github.io/llama-cpp-python/whl/cpu](https://abetlen.github.io/llama-cpp-python/whl/cpu) llama-cpp-python
  uv pip install -r requirements.txt

  uv run python scripts/intialize_db.py
  uv run python scripts/seed_vectors.py
  uv run streamlit run app.py
  ```
</details>

---

## Performance Highlights

* **~237,212x Latency Elimination**: Deterministic regex routing resolves common actions in 0.015 ms, bypassing a 3.6-second local CPU classification prompt.
* **Invariant ~7s Response Ceiling**: Enforcing a strict 4-message context tail (`TAIL_WINDOW_SIZE = 4`) and compact 5-line telemetry prevents quadratic context degradation as workout history scales.
* **Sub-25ms In-Process Vector Search**: `sqlite-vec` queries embedded C virtual tables directly, eliminating client-server vector database overhead.
* **Zero Write Contention**: Thread-isolated WAL ledgers sustained 10 concurrent threads committing 150 sets simultaneously with 0 lock errors.

> Review the full empirical benchmark tables and context scaling curves in [`docs/ARCHITECTURAL_BENCHMARKS.md`](docs/ARCHITECTURAL_BENCHMARKS.md).

---

## Biomechanical Engine Overview

Unlike generic trackers, Myos embeds exercise physiology rules into its transaction layer:

* **Dynamic RPE Scaling**: Computes effective 1RM using $w \cdot (1 + \text{effective\_reps}/30)$ to determine true velocity reserve without requiring failure sets.
* **RPE 10 Overshoot Protection**: Drops subsequent session loads by 2.5 kg if an athlete overshoots target intensity.
* **Olympic Disc Snapping**: Snaps all calculated loads to 2.5 kg symmetric increments and outputs per-side plate breakdowns (e.g., `Bar + [25, 10, 1.25] kg/side`).
* **Fractional Synergist Tracking**: Direct working sets score 1.0 sets; secondary muscle contributors identified in the relational catalog receive 0.5 sets.
* **Clinical Red-Flag Intercept**: Immediately halts movement recommendations within 0.015 ms upon detecting acute trauma tokens (*"sharp pop"*, *"shooting pain"*, *"tore"*).

> Detailed formulas, warmup ramp structures, and deload rules are documented in [`docs/PROGRESSION_RULES.md`](docs/PROGRESSION_RULES.md).

---

## Observability

Inference throughput and latency metrics are tracked silently to `logs/myos.log` without cluttering the user interface:

```bash
# Monitor real-time transaction telemetry
docker compose exec myos-engine tail -f /app/logs/myos.log | grep "\[TELEMETRY\]"

# Run an on-demand engine latency & throughput audit
docker compose exec myos-engine python scripts/check_engine_health.py
```

---

## Roadmap

- [x] Zero-regression architecture refactoring and multi-tenant WAL migration.
- [x] Sub-millisecond regex router and clinical safeguard interceptor.
- [x] `SafeChatLlamaCpp` streaming tool-call sanitization.
- [x] In-process `sqlite-vec` semantic exercise catalog search.
- [x] Fractional synergist volume attribution (1.0 direct / 0.5 synergist).
- [x] Atomic batch insertion for workout sets to prevent partial-write states.
- [ ] Export session logs to standardized CSV / JSON fitness exchange formats.
- [ ] Direct Apple HealthKit and Google Health Connect local synchronization.
- [ ] Optional Vulkan / CUDA GPU offload support in Docker runtime.

---

## License

Distributed under the MIT License. See `LICENSE` for details.

---

## Contact

**Ahmed Tamer** — [ahmedhegazy4me@gmail.com](mailto:ahmedhegazy4me@gmail.com)

Project Repository: [https://github.com/ahmedtvmer/myos](https://github.com/ahmedtvmer/myos)

<p align="right">(<a href="#readme-top">back to top</a>)</p>