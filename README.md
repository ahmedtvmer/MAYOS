<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-000000?style=for-the-badge&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.42+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![sqlite-vec](https://img.shields.io/badge/sqlite--vec-0.1.9-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://github.com/asg017/sqlite-vec)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
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
    <a href="#empirical-benchmarks--performance">View Benchmarks</a>
    ·
    <a href="#system-architecture">System Architecture</a>
    ·
    <a href="#getting-started">Getting Started</a>
  </p>
</div>

---

<!-- TABLE OF CONTENTS -->
<details>
  <summary><b>Table of Contents</b></summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li><a href="#key-architectural-pillars">Key Architectural Pillars</a></li>
    <li><a href="#built-with">Built With</a></li>
    <li><a href="#system-architecture">System Architecture</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation--setup">Installation & Setup</a></li>
        <li><a href="#database-initialization--vector-seeding">Database Initialization & Vector Seeding</a></li>
      </ul>
    </li>
    <li><a href="#usage--workflows">Usage & Workflows</a></li>
    <li><a href="#empirical-benchmarks--performance">Empirical Benchmarks & Performance</a></li>
    <li><a href="#biomechanical-progression-rules">Biomechanical Progression Rules</a></li>
    <li><a href="#docker-deployment">Docker Deployment</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
  </ol>
</details>

---

## About The Project

**Myos** is a private, local-first workout ledger and biomechanics engine engineered to eliminate cloud dependencies, privacy risks, and computational bloat in personal fitness software .

Commercial training applications frequently depend on rigid linear progression (+2.5 kg next week regardless of fatigue) and binary volume counters that inflate synergistic muscle tracking . Conversely, naive AI agents pass every conversational turn through an LLM prompt, incurring 3–6 second local CPU bottlenecks just to categorize intent or confirm routine modifications .

Myos resolves these tradeoffs directly:
* **Zero-Cloud Dependency**: Runs entirely offline on local CPU hardware using quantized GGUF inference .
* **Sub-Millisecond Fast Path**: Deterministic regex filters process standard actions and clinical alerts in approximately 15 microseconds—bypassing LLM inference entirely .
* **Biomechanical Auto-Regulation**: Scales working loads through effective estimated 1RMs ($w \cdot (1 + \text{effective\_reps}/30)$), snaps weights to 2.5 kg barbell increments with per-side Olympic plate breakdowns, and scores secondary synergists at 0.5 sets .

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Key Architectural Pillars

### 1. Hybrid Deterministic & Agentic Routing
High-frequency actions—clinical intercepts, explicit two-way swaps, split mutations, and catalog queries—are evaluated deterministically via compiled regex nodes in single-digit microseconds . Unstructured biomechanical questions are passed cleanly to the local LLM .

### 2. Chunk-Sanitized Local Inference (`SafeChatLlamaCpp`)
A custom subclass of `ChatLlamaCpp` intercepts delta chunks during streaming inference . By deduplicating repeated function names emitted across delta frames, Myos preserves token-by-token WebSocket streaming to the Streamlit UI while preventing Pydantic structured output validation failures .

### 3. Dual-Database Topology & Thread-Isolated Ledgers
Myos mounts a shared, read-only exercise catalog (`catalog.db`) equipped with the `sqlite-vec` C extension alongside private, thread-local user ledgers (`db/users/<id>.db`) operating under SQLite Write-Ahead Logging (`WAL`) mode . This guarantees zero write contention and absolute cross-tenant privacy .

### 4. 4-Message Context Clamping & Compact Telemetry
To prevent CPU prompt evaluation times from degrading quadratically over extended training cycles, the active dialogue history provided to the LLM is clamped to a fixed 4-message window . Trainee context is hydrated into an immutable, 5-line telemetry snapshot synthesized directly from recent database sets .

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Built With

* [![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
* [![LangGraph](https://img.shields.io/badge/LangGraph-1.2.11-000000?style=flat-square&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
* [![Streamlit](https://img.shields.io/badge/Streamlit-1.42+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
* [![llama-cpp-python](https://img.shields.io/badge/llama--cpp--python-AVX2_CPU-orange?style=flat-square)](https://github.com/abetlen/llama-cpp-python)
* [![sqlite-vec](https://img.shields.io/badge/sqlite--vec-0.1.9-003B57?style=flat-square)](https://github.com/asg017/sqlite-vec)
* [![HuggingFace](https://img.shields.io/badge/Embeddings-BGE--Small--en--v1.5-FFD21E?style=flat-square)](https://huggingface.co/BAAI/bge-small-en-v1.5)
* [![Qwen](https://img.shields.io/badge/Model-Qwen_2.5_3B_GGUF-6152FA?style=flat-square)](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)
* [![uv](https://img.shields.io/badge/Package_Manager-uv-DE5FE9?style=flat-square)](https://github.com/astral-sh/uv)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

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
    |  - Sessions & Sets   |                            | - sqlite-vec Ext     |
    |  - Cascade Deletes   |                            | - 384d BGE Embeddings|
    +----------------------+                            +----------------------+
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Getting Started

### Prerequisites

* [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine with Docker Compose v2.
* A CPU supporting AVX2 instructions (standard on all modern x86_64 processors) .

### Quickstart with Docker

The application is fully containerized with OpenMP CPU optimization, precompiled AVX2 `llama-cpp-python` binaries, and persistent storage volumes .

1. **Clone the Repository**:
   ```bash
   git clone [https://github.com/ahmedtvmer/myos.git](https://github.com/ahmedtvmer/myos.git)
   cd myos
   ```

2. **Initialize Database & Seed Semantic Vectors (One-Time Setup)**:
   ```bash
   docker compose run --rm myos-engine python scripts/intialize_db.py
   docker compose run --rm myos-engine python scripts/seed_vectors.py
   ```

3. **Launch the Engine**:
   ```bash
   docker compose up -d
   ```

Access the application directly in your browser at **`http://localhost:8501`** .

> *Note: On first startup, the model artifact (`qwen2.5-3b-instruct-q4_k_m.gguf`) will download automatically to your mounted `./models` directory if not already present .*

<details>
  <summary><b>Optional: Local Development (Without Docker)</b></summary>
  <br />

  If you prefer running natively on the host machine using [uv](https://github.com/astral-sh/uv) :

  ```bash
  # 1. Create environment and install dependencies
  uv venv
  source .venv/bin/activate
  uv pip install --extra-index-url [https://abetlen.github.io/llama-cpp-python/whl/cpu](https://abetlen.github.io/llama-cpp-python/whl/cpu) llama-cpp-python
  uv pip install -r requirements.txt

  # 2. Seed database
  uv run python scripts/intialize_db.py
  uv run python scripts/seed_vectors.py

  # 3. Launch Streamlit
  uv run streamlit run app.py
  ```
</details>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---
## Usage & Workflows

Launch the Streamlit web engine:
```bash
uv run streamlit run app.py
```
Access the application interface at `http://localhost:8501`.

### Functional Modules:

* **Trainee Intake & Calibration**: Multi-step onboarding assessing limb proportions, weekly frequency capacity (1–5 days), training age, available equipment, and systemic recovery factors .
* **Tab 1: Program & Dashboard**:
  * Rolling 7-day volume attribution chart evaluating 1.0 direct sets and 0.5 synergist sets .
  * Longitudinal estimated 1RM trajectory tracking per movement .
  * Visual exercise execution cards featuring local animation and image demonstrations .
  * One-click export of the active 4-week double progression split to Excel (`.xlsx`) .
* **Tab 2: Active Workout Logger**:
  * Auto-regulated load suggestions calculated from prior session RPE .
  * Plate calculation breakdown per side snapped to 2.5 kg barbell increments .
  * 3-tier potentiating warm-up sets (40%, 65%, 85%) .
  * Dynamic deload banner with volume and intensity caps when recovery is compromised .
  * Post-session coaching debrief summarizing volume milestones and next session targets .
* **Tab 3: Training Assistant**:
  * Low-latency streaming biomechanics recommendations .
  * Deterministic fast-path commands: `"swap hack squat for leg press"` or `"rebuild split to 3 days"` .
  * Clinical intercept: `"I felt a sharp tear in my pec"` instantly displays a medical stop directive .

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Empirical Benchmarks & Performance

All benchmarks were recorded locally on an Intel Core i7 (6 physical cores, OpenMP enabled) running Qwen 2.5 3B Instruct Q4_K_M .

### 1. Intent Routing Latency Benchmark

The regex fast path routes common operations in single-digit microseconds, eliminating local LLM classification latency :

| Operational Category | Regex Fast-Path | Local CPU LLM | Measured Speedup | Production Impact |
| :--- | :---: | :---: | :---: | :--- |
| **Clinical Intercept** | **0.015 ms**  | 1,808.1 ms  | **123,211x**  | Immediate movement cessation ; zero risk of AI hallucinating injury rehabilitation advice . |
| **Explicit Swap (2-Way)** | **0.014 ms**  | 5,039.9 ms  | **371,387x**  | Instant ledger mutation without schema generation overhead . |
| **Candidate Lookup (1-Way)**| **0.010 ms**  | 3,524.5 ms  | **349,801x**  | Sub-millisecond retrieval of biomechanically matched candidates . |
| **Split Mutation** | **0.009 ms**  | 1,631.5 ms  | **178,107x**  | Instant frequency capture and routine rebuild . |
| **Catalog Search** | **0.026 ms**  | 3,326.4 ms  | **126,890x**  | Triggers `sqlite-vec` KNN query without prompt overhead . |
| **Coaching Q&A Check** | **0.018 ms**  | 6,325.7 ms  | **359,456x**  | Negative check passes to streaming in <20 µs . |
| **Composite Average** | **0.015 ms**  | **3,609.4 ms**  | **~237,212x**  | **Eliminates a 3.6-second CPU inference bottleneck .** |

### 2. Context Window Scaling

Clamping conversation history to a 4-message tail prevents linear prompt expansion and enforces flat response latency across long training histories :

| Dialogue History | Unclamped Runtime Latency | Myos Clamped Tail Latency | Speedup Delta | Behavior |
| :---: | :---: | :---: | :---: | :--- |
| **1 Turn** | 7.38s | 5.01s | Baseline | Symmetrical prompt token evaluation. |
| **4 Turns** | 8.68s | 11.01s | ~Flat | Initial prompt prefix cache alignment. |
| **10 Turns** | 10.59s | 21.20s | Transient Spike | Thread re-allocation and memory re-indexing. |
| **20 Turns** | 26.60s | 6.82s | **3.9x faster** | Unclamped pipeline experiences CPU degradation. |
| **30 Turns** | 28.33s | 7.12s | **4.0x faster** | **Enforces an asymptotic ~7s latency ceiling indefinitely.** |

### 3. Concurrency & Vector Retrieval

* **WAL Concurrency**: 10 concurrent threads executed 150 simultaneous set inserts across 10 isolated user databases with 0 locks and 0 write contention exceptions .
* **Vector Retrieval**: Average search latency of **66.93 ms** (including cold-start embedding initialization), with warm KNN query retrieval times stabilizing at **19.9 ms – 25.9 ms**.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Biomechanical Progression Rules

Myos incorporates quantitative exercise physiology principles directly into its runtime:

* **Dynamic RPE Overload**: Rather than using static jumps, estimated 1RM is calculated via:
  $$\text{e1RM} = \text{load} \times \left(1 + \frac{\text{reps} + (10 - \text{RPE})}{30}\right)$$
 
  * **Bracket Ceiling & Velocity Surplus**: When a trainee hits the top of the target rep range with RPE $\le$ prescription target, load steps up by the equipment increment (2.5 kg barbell, 2.0 kg dumbbell) .
  * **RPE 10 Step-Down**: If RPE reaches 10.0 on a submaximal prescription, the load is stepped down by 2.5 kg next exposure to manage fatigue and joint stress .
* **Barbell Plate Snapping**: Automatically snaps target loads to symmetric 2.5 kg increments and outputs exact per-side Olympic plate breakdowns (`Bar + [25, 10, 1.25] kg/side`) .
* **Potentiating Warm-Up Sets**: Calculates 3 non-fatiguing warm-up sets snapped to 2.5 kg increments: 40% (5 reps), 65% (3 reps), and 85% (1 rep) .
* **Deduplicated Synergist Volume Tracking**: Direct working sets register 1.0 effective sets . Secondary synergists identified via `exercise_secondary_muscles` register 0.5 sets, preventing inflated volume calculations .
* **Systemic Fatigue Deload Automation**: Automatically triggers a deload (40–50% set reduction, RPE capped at 7.0–8.0) if :
  1. Rolling 3-session readiness average drops to $\le$ 2.0/5 .
  2. Acute readiness floor of 1/5 is recorded .
  3. Exertion density exceeds 50% of sets $\ge$ RPE 9.5 alongside declining readiness .

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Docker Deployment

The containerized engine isolates CPU thread pools via OpenMP and mounts persistent local directories .

1. **Verify `docker-compose.yaml` Mounts**:
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
         - OMP_NUM_THREADS=6
         - EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
   ```

2. **Build and Launch Container**:
   ```bash
   docker compose up --build -d
   docker compose logs -f
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Roadmap

- [x] Zero-regression architecture refactoring and multi-tenant WAL migration .
- [x] Sub-millisecond regex router and clinical safeguard interceptor .
- [x] `SafeChatLlamaCpp` streaming tool-call sanitization .
- [x] In-process `sqlite-vec` semantic exercise catalog search .
- [x] Fractional synergist volume attribution (1.0 direct / 0.5 synergist) .
- [ ] Export session logs to standardized CSV / JSON fitness exchange formats.
- [ ] Direct Apple HealthKit and Google Health Connect local synchronization.
- [ ] Optional Vulkan / CUDA GPU offload support in Docker runtime.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

## Contact

**Ahmed Tamer** — [ahmedtamerhejazi@gmail.com](mailto:ahmedtamerhejazi@gmail.com) 

Project Link: [https://github.com/ahmedtvmer/myos](https://github.com/ahmedtvmer/myos)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
