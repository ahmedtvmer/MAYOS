# Architecture Decision Records (ADRs) & Engine Safeguards

This document records the architectural, algorithmic, and heuristic decisions implemented in the MYOS engine.

---

### ADR 001: Hypertrophic Frequency Clamping (1–5 Days)
* **Status**: Accepted
* **Rule**: The onboarding intake graph rejects requested training frequencies > 5 days/week and clamps split generation strictly to 1–5 days per microcycle.
* **Context**: Trainees frequently request 6- or 7-day splits. Generating high-frequency routines via edge models often produces overlapping movement patterns with inadequate recovery between identical muscle groups.
* **Rationale**: **Internal Coaching Heuristic & Safeguard.** Natural trainees training with genuine proximity to failure (0–3 RIR) require sufficient recovery capacity between high-tension sessions. Enforcing a 5-day ceiling guarantees at least two non-training recovery days per microcycle, maintaining systemic recovery without relying on the LLM to balance complex 6-day split distributions.
* **Code References**: `agent/onboarding_graph.py` (`STEP2_SEGMENT_RE`, `weekly_frequency` validator).

---

### ADR 002: Multi-Tier Clinical Safety Intercept
* **Status**: Accepted
* **Rule**: Split safety evaluation into Tier 0 (Fast-Path Regex, <0.02 ms) and Tier 1 (BGE-small Semantic Cosine Guard, ~15 ms at threshold >= 0.70), while bypassing physiological fatigue terms (e.g., metabolic burn, quad exhaustion).
* **Context**: Human trainees describe musculoskeletal damage colloquial-first ("velcro tearing", "hot glass in joint", "pins and needles"). Keyword-only regex creates false negatives, while evaluating full LLM prompts on every message introduces CPU thermal throttling and multi-second latency.
* **Rationale**: **Defensive Safety Architecture.** Acute musculoskeletal trauma demands an immediate halt. Combining deterministic token matching for common trauma terms with an in-memory 8-anchor semantic cosine guard catches edge-case somatosensory feedback while allowing normal hypertrophic fatigue to reach the coaching prompt.
* **Code References**: `agent/clinical_guard.py` (`evaluate_clinical_semantic_guard`), `agent/assistant_graph.py` (`router_node`).

---

### ADR 003: Deterministic Post-Workout Debrief Synthesis
* **Status**: Accepted
* **Rule**: Post-workout debriefs assemble **Overload Deltas**, **Fatigue & CNS Check**, and **Next Session Directives** deterministically in Python rather than generating them via free-form LLM inference.
* **Context**: Quantized 3B models under CPU load suffered from instruction drift, omitting deload directives in 40% of generalization test cases and introducing non-deterministic progression advice.
* **Rationale**: **Zero-Drift Engineering.** Analytical calculations (e1RM, volume load, load increments, fatigue states) are mathematical, not probabilistic. Assembling the response deterministically guarantees 100% deload compliance, eliminates hallucinatory load increases, and reduces CI debrief evaluation time from ~14 minutes to single-digit milliseconds.
* **Code References**: `agent/debrief.py` (`generate_session_debrief`).

---

### ADR 004: Systemic Fatigue Floor & Reactive Deload Triggers
* **Status**: Accepted
* **Rule**: A reported readiness score of 1/5, an acute readiness collapse, or sustained high exertion density triggers an immediate reactive deload: a 50% session volume cut and a mandatory RPE 7.0 ceiling (minimum 3 RIR).
* **Context**: Allowing progressive overload or RPE 9–10 top sets under acute systemic exhaustion or unrecovered joint strain sharply elevates soft-tissue injury risk.
* **Rationale**: **Internal Coaching Heuristic (Auto-regulation).** While general tapering literature indicates volume reductions between 30% and 70% dissipate fatigue while preserving adaptation, the specific combination of a 50% set cut and an RPE 7.0 cap is an auto-regulatory heuristic. Halving working sets cuts mechanical accumulation, and capping intensity at RPE 7.0 prevents failure-induced strain while reinforcing motor patterns.
* **Code References**: `agent/progression_engine.py` (readiness and deload evaluation), `agent/prompts.py` (`STATIC_SYSTEM_CORE`).