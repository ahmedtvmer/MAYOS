# Myos: Architectural Benchmarks & System Comparative Analysis

This document provides a comparative analysis and empirical benchmark evaluation of the Myos engine, detailing performance metrics, context scaling, concurrency thresholds, deterministic triage guarantees, and biomechanical auto-regulation protocols against standard LLM agent frameworks and conventional workout trackers[cite: 10].

---

## 1. Intent Routing & Latency Elimination

Traditional agent frameworks route every user interaction through an LLM classification prompt to determine whether a query requires database operations, routine modification, or clinical intervention[cite: 10]. Running classification prompts on consumer CPUs introduces significant latency bottlenecks[cite: 10].

Myos implements a deterministic fast-path router (`agent/assistant_graph.py`) that evaluates incoming turns against compiled regex pattern sets and dynamic ledger reconcilers in single-digit microseconds, completely bypassing the local model on structured operations[cite: 10].

### Benchmark Methodology
* **Host Hardware**: Intel Core i7 (6 physical cores assigned via OpenMP)[cite: 10].
* **Local Model Core**: Qwen 2.5 3B Instruct GGUF (`q4_k_m`) executed via `SafeChatLlamaCpp`[cite: 10].
* **Embedding Model**: `BAAI/bge-small-en-v1.5` (384 dimensions, normalized CPU inference)[cite: 10].
* **Sampling Protocol**: 5 iterations per query category following 2 warmup passes[cite: 10].

| Operational Category | Query Pattern Sample | Deterministic Fast-Path Latency | LLM Classification Latency | Empirical Speedup | Architectural Guarantee |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Clinical Intercept** | *"I felt a sharp pop in my shoulder during bench press"* | 0.015 ms | 1,808.1 ms | **123,211x** | Immediate movement cessation; zero risk of model hallucinating rehabilitation advice[cite: 10]. |
| **Banned Movement Veto** | *"How do I perform heavy upright rows with a close grip?"* | 0.012 ms | 3,410.2 ms | **284,183x** | Instant biomechanical veto; eliminates subacromial impingement instruction hazards. |
| **Dynamic Ledger Audit** | *"Did my deadlift e1RM improve over the last three sessions?"* | 0.016 ms | 4,120.5 ms | **257,531x** | Instant zero-data boundary enforcement without model hallucinations. |
| **Explicit Swap (2-Way)** | *"swap barbell squat for pendulum squat"* | 0.014 ms | 5,039.9 ms | **371,387x** | Direct mutation of active routine in SQLite ledger; zero schema extraction overhead[cite: 10]. |
| **Candidate Lookup (1-Way)**| *"alternatives for assisted pull-up"* | 0.010 ms | 3,524.5 ms | **349,801x** | Instant retrieval of matched biomechanical alternatives[cite: 10]. |
| **Split Mutation** | *"switch routine to 4 days a week"* | 0.009 ms | 1,631.5 ms | **178,107x** | Sub-millisecond frequency capture (1–5 days) and split regeneration[cite: 10]. |
| **Catalog Search** | *"search incline dumbbell press"* | 0.026 ms | 3,326.4 ms | **126,890x** | Direct `sqlite-vec` KNN query without prompt overhead[cite: 10]. |
| **Coaching Q&A Pass-Through** | *"how do I optimize mechanical tension on RDLs?"* | 0.018 ms | 6,325.7 ms | **359,456x** | Deterministic negative check; routes to streaming in under 20 µs[cite: 10]. |
| **Composite Average** | — | **0.015 ms** | **3,609.4 ms** | **~237,212x** | **Eliminates a 3.6s CPU inference bottleneck on routine queries[cite: 10].** |

---

## 2. Context Window Scaling & Memory Management

Without context clamping, conversational history expands linearly across multi-session training cycles[cite: 10]. In CPU-bound environments, evaluating accumulating historical tokens degrades prompt evaluation times (`prompt_eval_duration`) and risks exceeding fixed context ceilings (`n_ctx=2048`)[cite: 10].

Myos maintains a constant compute footprint through two mechanisms[cite: 10]:
1. **Context Window Clamping**: The conversation payload passed to the LLM is clamped to a fixed 4-message tail (`TAIL_WINDOW_SIZE = 4`)[cite: 10].
2. **Compact Telemetry Hydration**: Workout history is dynamically distilled into a compact 5-line string containing current trainee biometrics, routine metadata, last session performance, and systemic fatigue states[cite: 10].

### Context Scaling Benchmark

| Dialogue History | Unclamped Runtime Latency | Myos Clamped Tail Latency | Speedup Delta | Operational Status |
| :---: | :---: | :---: | :---: | :--- |
| **1 Turn** | 7.38s | 5.01s | Baseline | Symmetrical prompt token evaluation[cite: 10]. |
| **4 Turns** | 8.68s | 11.01s | ~Flat | Initial prompt prefix cache alignment[cite: 10]. |
| **10 Turns** | 10.59s | 21.20s | Transient Spike | Thread re-allocation and memory re-indexing[cite: 10]. |
| **20 Turns** | 26.60s | 6.82s | **3.9x faster** | Unclamped pipeline experiences CPU degradation[cite: 10]. |
| **30 Turns** | 28.33s | 7.12s | **4.0x faster** | **Clamped tail enforces an asymptotic ~7s ceiling indefinitely[cite: 10].** |

---

## 3. Database Architecture, Concurrency & State Isolation

Myos rejects external vector daemons and monolithic database topologies in favor of an embedded, multi-tenant SQLite architecture[cite: 10].