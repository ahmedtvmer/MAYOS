# Myos: Architectural Benchmarks & System Comparative Analysis

This document provides a comparative analysis and empirical benchmark evaluation of the Myos engine, detailing performance metrics, context scaling, concurrency thresholds, deterministic triage guarantees, and biomechanical auto-regulation protocols against standard LLM agent frameworks and conventional workout trackers.

---

## 1. Intent Routing & Latency Elimination

Traditional agent frameworks route every user interaction through an LLM classification prompt to determine whether a query requires database operations, routine modification, or clinical intervention. Running classification prompts on consumer CPUs introduces significant latency bottlenecks.

Myos implements a deterministic fast-path router (`agent/assistant_graph.py`) that evaluates incoming turns against compiled regex pattern sets and dynamic ledger reconcilers — pure-regex paths resolve in microseconds, while non-trivial queries add a Tier-1 semantic guard (~30 ms on CPU) — completely bypassing the local model on structured operations.

### Benchmark Methodology (2026-09 Model Refresh)

* **Host Hardware**: Intel Core i7-9850H (6 physical cores / 12 threads; `OMP_NUM_THREADS=6`).
* **GPU**: NVIDIA Quadro T2000 (4 GB VRAM); production model **fully offloaded** (`N_GPU_LAYERS=-1`).
* **Local Model Core**: **Qwen3.5-4B Instruct GGUF** (`q4_k_m`) executed via `SafeChatLlamaCpp`.
* **Embedding Model**: `BAAI/bge-small-en-v1.5` (384 dimensions, normalized CPU inference).
* **Sampling Protocol**: 5 iterations per query category following 2 warmup passes (`tests/benchmark_routing.py`).

| Operational Category | Query Pattern Sample | Fast-Path Latency | LLM Classification Latency | Empirical Speedup |
| :--- | :--- | :---: | :---: | :---: |
| **Clinical Intercept** | *"I felt a sharp pop in my shoulder during bench press"* | 0.014 ms | 5,197.1 ms | **375,847x** |
| **Candidate Lookup (1-Way)** | *"alternatives for assisted pull-up"* | 0.075 ms | 5,370.5 ms | **71,639x** |
| **Catalog Search** | *"search incline dumbbell press"* | 0.064 ms | 5,263.5 ms | **82,504x** |
| **Explicit Swap (2-Way)** | *"swap barbell squat for pendulum squat"* | 32.860 ms | 6,249.9 ms | **190x** |
| **Split Mutation** | *"switch routine to 4 days a week"* | 35.263 ms | 6,341.1 ms | **180x** |
| **Coaching Q&A Pass-Through** | *"how do I optimize mechanical tension on RDLs?"* | 34.551 ms | 5,408.5 ms | **157x** |
| **Composite Average** | — | **17.138 ms** | **5,638.4 ms** | **~329x** |

> **Reading these numbers honestly.** The rows at ~33–35 ms include the **Tier-1 BGE semantic cosine guard** (~30 ms CPU embedding) that every non-trivial query passes through for clinical safety (ADR 002). Pure-regex paths — clinical Tier-0 hits and short queries with no clinical tokens (which short-circuit the guard before embedding) — remain at **0.014–0.075 ms**, i.e. **71,000–375,000× faster** than LLM classification. Even the guard-inclusive worst case eliminates a **5.6-second** structured-output classification call with a **~33 ms** deterministic pass. Moving embeddings to GPU (`EMBEDDING_DEVICE=cuda`) collapses the guard cost to single-digit milliseconds on hosts with spare VRAM.

### Model Refresh Comparison (Qwen 2.5 3B → Qwen 3.5 4B)

| Metric | Previous stack (Qwen 2.5 3B) | Current stack (Qwen 3.5 4B) | Verdict |
| :--- | :---: | :---: | :--- |
| Pure-regex fast-path latency | 0.009–0.026 ms | 0.014–0.075 ms | **No degradation** (same microsecond class) |
| LLM classification latency (mean) | 3,609 ms | 5,638 ms | Expected: larger model costs ~1.6× more to classify |
| Best-case speedup vs LLM routing | 371,387x | 375,847x | **No degradation** |
| Average speedup (all categories) | ~237,212x | ~329x | Not comparable: the old router had **no Tier-1 semantic guard**; the current average includes it |
| Clamped context latency ceiling | ~7 s | **~4.2 s** | **Improved** (see §2) |

**Conclusion:** the model upgrade does not degrade the deterministic engine — pure-regex paths and best-case speedups are unchanged, while the safety layer (Tier-0b context gating + Tier-1 semantic guard) is now included in the measured router. The ~237,212x headline from the previous stack measured a router *without* the semantic guard and is retained only as a historical figure.

---

## 2. Context Window Scaling & Memory Management

Without context clamping, conversational history expands linearly across multi-session training cycles. In CPU-bound environments, evaluating accumulating historical tokens degrades prompt evaluation times (`prompt_eval_duration`) and risks exceeding fixed context ceilings (`n_ctx=2048`).

Myos maintains a constant compute footprint through two mechanisms:
1. **Context Window Clamping**: The conversation payload passed to the LLM is clamped to a fixed 6-message tail (`TAIL_WINDOW_SIZE = 6`).
2. **Compact Telemetry Hydration**: Workout history is dynamically distilled into a compact 5-line string containing current trainee biometrics, routine metadata, last session performance, and systemic fatigue states.

### Context Scaling Benchmark (2026-09 Refresh, Qwen3.5-4B, Full GPU Offload)

| Dialogue History | Unclamped Runtime Latency | Myos Clamped Tail Latency | Clamped vs Unclamped |
| :---: | :---: | :---: | :--- |
| **1 Turn** | 4.91 s | 3.23 s | Clamped is 1.5× faster |
| **4 Turns** | 4.28 s | 4.09 s | ~Flat |
| **10 Turns** | 5.50 s | 4.17 s | 1.3× faster |
| **20 Turns** | 7.59 s | 4.23 s | 1.8× faster |
| **30 Turns** | 10.14 s | **4.18 s** | **2.4× faster — flat ceiling** |

The clamped path holds an asymptotic **~4.2 s ceiling** regardless of history length, while the unclamped path grows monotonically past 10 s by turn 30. Compared to the previous stack's ~7 s ceiling, the 4B + GPU offload combination improved the invariant by ~40% while handling a 33% larger model.

---

## 3. Database Architecture, Concurrency & State Isolation

Myos rejects external vector daemons and monolithic database topologies in favor of an embedded, multi-tenant SQLite architecture.

            +-----------------------------------------+
            |          DatabaseManager                |
            |   (Thread-Local Connection Routing)     |
            +--------------------+--------------------+
                                 |
           +---------------------+---------------------+
           |                                           |
           v                                           v
+----------------------+                    +----------------------+
|  Thread 1 (User A)   |                    |  Thread 2 (User B)   |
|  Mounts: user_a.db   |                    |  Mounts: user_b.db   |
|  Mode: WAL           |                    |  Mode: WAL           |
|  ATTACH catalog.db   |                    |  ATTACH catalog.db   |
+----------+-----------+                    +----------+-----------+
           |                                           |
           +---------------------+---------------------+
                                 |
                                 v
                    +-------------------------+
                    |   catalog.db (Attached) |
                    |   - exercises           |
                    |   - secondary_muscles   |
                    |   - vec_exercises       |
                    +-------------------------+

### Architectural Differentiators

* **Embedded `sqlite-vec` vs. Vector Daemons**: Replaces external client-server vector stores with an embedded SQLite C extension (`sqlite-vec`). Vector KNN matches run directly inside SQLite via virtual tables (`vec_exercises`), eliminating external process overhead and network socket serialization.
* **Hard Multi-Tenancy via Isolated SQLite Databases**: Each user operates out of a dedicated SQLite file (`db/users/<trainee_id>.db`) mounted via Python's `threading.local`. This guarantees zero risk of cross-tenant data leakage.
* **WAL Mode Concurrency**: Setting `PRAGMA journal_mode = WAL;` enables concurrent readers and writers without lock contention.
  * *Concurrency Stress Test*: 10 concurrent threads simultaneously logged 150 sets across 10 distinct user ledgers with zero write contention or database lock exceptions.
* **Relational Integrity via Cascading Deletes**: `PRAGMA foreign_keys = ON;` guarantees that deleting a workout session cascades to all child `workout_sets` records, preventing orphaned database artifacts.

---

## 4. Vector Retrieval & Semantic Search

The movement catalog is indexed using 384-dimensional normalized vectors generated by `bge-small-en-v1.5`.

### Retrieval Latency & Semantic Relevance
* **Mean Search Latency**: 66.93 ms (cold start); warm search latency stabilizes at **19.9 ms – 25.9 ms**.
* **Biomechanical Constraints**:
  * High-risk movement patterns (*behind-the-neck presses*, *upright rows*) are systematically filtered out at the catalog query layer before vector similarity scoring occurs (`EXCLUDED_BIOMECHANICAL_PATTERNS`).
  * Non-hypertrophy movements (e.g., yoga, stretching, cardio patterns) are filtered out at the SQL view level (`EXCLUDED_TERMS`).

---

## 5. Biomechanical Engine vs. Conventional Workout Trackers

| Functional Domain | Conventional Trackers (Strong, Hevy, 5x5) | Myos Biomechanics Engine |
| :--- | :--- | :--- |
| **Progression Algorithm** | Static linear progression (e.g., add 2.5 kg next week regardless of velocity or actual exertion). | **Dynamic RPE Scaling**: Computes effective 1RM via: $$\text{e1RM} = w \cdot \left(1 + \frac{\text{effective\_reps}}{30}\right)$$ where $\text{effective\_reps} = r + (10 - \text{RPE})$. Dynamically upscales on reserve velocity or flags bracket graduation. |
| **Failure Protection** | None. Prescribes heavier loads following failed sets or near-injury overshoots. | **RPE 10 Step-Down**: Detects overshoots (RPE 10 @ target $\le$ 8.5) and drops load by 2.5 kg to protect joint and connective tissue integrity. |
| **Barbell Plate Math** | Floating point decimal targets (e.g., 73.3 kg), requiring manual gym plate math. | **Olympic Snapping**: Automatically snaps weights to 2.5 kg increments and outputs exact per-side Olympic plate configurations (e.g., `Bar + [25, 5, 1.25] kg/side`). |
| **Warm-Up Calculations** | Generic percentages or omitted entirely. | **Potentiating Ramp Sets**: Generates 3 non-fatiguing potentiating sets snapped to 2.5 kg:<br>• W1: 40% (5 reps, pattern calibration)<br>• W2: 65% (3 reps, acceleration intent)<br>• W3: 85% (1 rep, neural potentiation) |
| **Volume Attribution** | Binary: counts 1 set for every tagged muscle, artificially inflating arm and shoulder volume. | **Fractional Synergist Tracking**: Direct targets = 1.0 sets; secondary synergists = 0.5 sets, deduplicated against catalog relational tables. |
| **Fatigue Intervention** | Fixed calendar-based deload weeks (e.g., every 4th or 6th week). | **Multi-Variable Fatigue Floor**: Triggers deloads when:<br>1. Rolling 3-session readiness average drops $\le$ 2.0/5.<br>2. An acute floor of 1/5 readiness is logged.<br>3. Exertion density exceeds 50% of sets at $\ge$ RPE 9.5 with declining readiness. |
| **Clinical Safety** | Buried disclaimer in terms of service; LLM chat might validate training through joint pain. | **Zero-LLM Hard Intercept**: Immediately blocks inference and halts movement upon detecting acute injury markers (*"sharp pop"*, *"shooting pain"*, *"numbness"*, *"tore"*) in <0.02 ms. |

---

## 6. Runtime Stability: Streaming vs. Structured Output Parsing

Under `llama-cpp-python`, streaming tool calls repeatedly emit the schema name across every argument delta chunk. LangChain's chunk aggregator concatenates these delta names, multiplying the tool name string by the total number of output tokens (e.g., `'IntentClassification' * 37 = 740 chars`), causing schema validation exceptions in `openai_tools.py`.

Myos resolves this with `SafeChatLlamaCpp` (`utils/model_downloader.py`), a subclass that monitors tool call indices (`seen_tool_indices`):
* **Chunk 0**: Emits the intended function name and registers the tool call index.
* **Chunks 1 to N**: Suppresses repeated name parameters (`tc["name"] = None`), passing only argument JSON deltas.

This patch enables `streaming=True` globally, allowing real-time token streaming through the FastAPI SSE endpoint (`POST /chat/messages`) to `st.write_stream` in the UI without breaking Pydantic structured output parsers.

---

## 7. LLM-as-a-Judge Clinical & Generalization Benchmark Suite

To guarantee deterministic clinical safety, numerical fidelity, and zero-hallucination guardrails prior to deployment, Myos evaluates its engine pipeline using an automated LLM-as-a-Judge evaluation suite (`tests/eval/run_evaluation.py`).

### Evaluation Architecture & Judge Specs
* **Evaluator Model Core**: **Qwen3.5-9B Instruct GGUF** (`q4_k_m`) — **two-phase GPU lifecycle**: the production model is explicitly unloaded (`unload_llm()`) before the judge loads, so a single 4 GB GPU serves both models sequentially. On the reference T2000, **16 of 32 layers** offload (`--gpu-layers 16`); higher counts fail context creation and the hardened loader retries once on CPU rather than crashing.
* **Inference Pipeline**: Strict Pydantic structured output validation (`safe_invoke_judge`) scoring across 5 discrete dimensions per module.
* **Pass Threshold**: Composite `is_passed == True` requires $\ge 4/5$ on non-fatal dimensions and strictly $5/5$ on fatal dimensions (`clinical_safety`, `groundedness`).

### 1. Standard Production Evaluation Benchmark (65 Cases — 2026-09 Refresh)

The standard test suite validates baseline compliance across onboarding intake validation, post-workout analytics, and active session coaching.

| Pipeline Target | Cases | Passed | Failed | Pass Rate | Mean Gen Latency | Primary Architectural Solution |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Onboarding Intake** | 15 | 13 | 2 | **86.7%** | ~7.1 s | Pydantic delta-profile scoring; explicit rejection criteria on omitted vs. negative fields. 2 extraction-fidelity misses (see below). |
| **Post-Workout Debrief** | 25 | 25 | 0 | **100.0%** | ~0.0 s | Deterministic Python assembly of overload deltas and CNS checks — zero model inference. |
| **Coaching Q&A** | 25 | 25 | 0 | **100.0%** | ~4.1 s | Dynamic entity reconciler (`reconcile_telemetry_query`) and zero-data ledger boundary enforcement. |
| **Total Engine Pipeline** | **65** | **63** | **2** | **96.9%** | **~3.2 s** | **Zero clinical-safety or groundedness failures; both misses are onboarding extraction fidelity.** |

**The two onboarding misses are substantive and actionable** (both are extraction bugs in otherwise-passing turns, not safety regressions):

1. `onboard_s1_01` — the trainee stated their **torso is longer**, but the extractor persisted `long_legs` (inverted proportions parsing).
2. `onboard_s2_01` — an **unstated** rep preference was persisted as the schema default `balanced` instead of being left unset (hallucinated default).

### 2. Unseen Generalization Benchmark (15 Cases — 2026-09 Refresh)

To verify that the pipeline did not overfit to specific benchmark wording, an unseen 15-case generalization suite was executed (`tests/eval/datasets/generalization_cases.json`). This suite introduced novel exercise permutations (e.g., *Bulgarian split squats*, *JM presses*), inverted syntax queries, third-party contraindication traps, and non-shoulder clinical complaints (*patellar tendon aching*).

| Generalization Target | Cases | Passed | Failed | Pass Rate | Mean Gen Latency | Empirical Behavioral Verification |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Coaching Q&A (Unseen)** | 5 | 5 | 0 | **100.0%** | 3.77 s | Universal diagnosis refusal on patellar aching; dynamic ledger checks on unlogged movements; lengthened-loading cues on novel press variants. |
| **Debrief (Unseen)** | 5 | 5 | 0 | **100.0%** | ~0.0 s | Exact volume & e1RM fidelity on multi-compound progressions; enforced deloads on spinal fatigue and acute 1/5 readiness floors. |
| **Onboarding (Unseen)** | 5 | 5 | 0 | **100.0%** | 6.39 s | Captured non-standard biometric phrasing; rejected out-of-range age and 6-day frequency; zero extraction drift this run. |
| **Total Generalization** | **15** | **15** | **0** | **100.0%** | **~3.4 s** | **Robust generalization confirmed across unseen movements and query syntax.** |

> **Comparison to the previous stack:** standard 100% → **96.9%** and generalization 93.3% → **100.0%** on the Qwen3.5-4B refresh. The standard-suite delta is entirely onboarding extraction fidelity (the two cases above), while all clinical-safety, groundedness, and budget dimensions passed across both suites. The judge's composite verdicts carry some run-to-run variance at temperature 0; the two failures were reproducible in generation (extraction output, not judge scoring).

### 3. Deterministic vs. Generative Execution Profile

The benchmark confirms runtime separation between sub-millisecond deterministic guards and generative coaching:

Fast-Path Safety & Ledger Intercepts (0.014 ms - 0.075 ms)
├── Clinical Trauma Halts (sharp pop, radiating pain, joint pinch)
├── Universal Musculoskeletal Diagnosis Refusal
├── Banned Biomechanical Movement Vetoes (behind-the-neck, upright rows, burn sets)
└── Dynamic Introspective Ledger Reconciliation (unlogged lifts, set count auditing)

Generative Coaching & Directive Assembly (3.8 s - 7.1 s)
├── Exercise Biomechanics & Technique Cueing (lengthened loading, pause mechanics)
├── Next Session Tactical Directives (step-up loads, rep pocket progression)
└── Multi-Step Trainee Profile Extraction & Intake Validation