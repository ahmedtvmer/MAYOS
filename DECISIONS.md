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
* **Rule**: Split safety evaluation into Tier 0 (Fast-Path Regex, <0.02 ms) and Tier 1 (BGE-small Semantic Cosine Guard, ~15 ms at threshold >= 0.70), while bypassing physiological fatigue terms (e.g., metabolic burn, quad exhaustion). Tier 0 is itself split: Tier 0a is unconditional (sharp pain/pop, shooting/radiating pain, numbness, tingling, pinched nerve, hernia, dislocation, cannot-move, joint clicking with pain); Tier 0b context-gates the DOMS-ambiguous tokens (swell/swollen, tear/tore/torn, pop, tweaked) so they intercept only with mechanism perception ("felt/heard a pop"), anatomical-structure proximity (joints, tendons, pec/bicep/ACL, ...), or body-part objects. DOMS idioms ("torn up", muscle-group swelling "from leg day", "tweaked my program", painless "knees pop when") defer to Tier 1.
* **Context**: Human trainees describe musculoskeletal damage colloquial-first ("velcro tearing", "hot glass in joint", "pins and needles"). Keyword-only regex creates false negatives, while evaluating full LLM prompts on every message introduces CPU thermal throttling and multi-second latency.
* **Rationale**: **Defensive Safety Architecture.** Acute musculoskeletal trauma demands an immediate halt. Combining deterministic token matching for common trauma terms with an in-memory 8-anchor semantic cosine guard catches edge-case somatosensory feedback while allowing normal hypertrophic fatigue to reach the coaching prompt.
* **Code References**: `agent/clinical_guard.py` (`evaluate_clinical_semantic_guard`), `agent/assistant_graph.py` (`router_node`, `_acute_injury_hit`, `RE_AMBIGUOUS_TRAUMA`).

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

---

### ADR 005: Lazy Per-User Schema Migrations & Atomic Snapshotting
* **Status**: Accepted
* **Rule**: Per-user databases (`db/users/<id>.db`) migrate lazily upon connection mount in `DatabaseManager.switch_user()`. Version state is tracked using `PRAGMA user_version`. Backups use `sqlite3.Connection.backup()`, enforcing a 3+1 retention policy (3 rolling session backups + 1 immutable pre-migration snapshot).
* **Context**: SQLite `CREATE TABLE IF NOT EXISTS` cannot alter tables or handle schema evolutions. Eager migrations on engine boot degrade startup performance with large user directories, and raw file copies during WAL execution risk file corruption.
* **Rationale**: **Local-First Resilience & Zero-Downtime Snapshots.** Using SQLite's native online backup API flushes active WAL frames into a consistent snapshot while transactions remain open. Lazy execution bounds startup time to $O(1)$ relative to total users. If a migration fails mid-stream, the engine executes an atomic rollback from the pre-migration snapshot.
* **Code References**: `database/migration_manager.py`, `database/database_manager.py` (`switch_user`, `create_user_schema`).

---

### ADR 006: Token-Version Session Epoch (Revoke-All on Password Change)
* **Status**: Accepted
* **Rule**: Per-ledger `auth_credentials.token_version` (schema v3) is stamped into every JWT as the `tv` claim at issue time (`register`/`login`/`claim`). `get_current_trainee` rejects any token whose `tv` differs from the ledger's current version with the same 401 as a revoked `jti`. `change_password`, email `reset_password_with_token`, and the admin CLI all `bump_token_version()`, killing every session including the caller's.
* **Context**: Revocation was per-`jti` only (`revoked_tokens`), so a password change left all other sessions alive — exactly the sessions an account-takeover victim needs dead. Enumerating live `jti`s per user was never stored, making "revoke all" inexpressible.
* **Rationale**: **Fail-closed session invalidation.** A single monotonic epoch per ledger expresses "all tokens before X are dead" in O(1) without a session table. Pre-v3 tokens without `tv` read as version 1, so rollout is backwards compatible until the first password event bumps the epoch. Change-password failures return 400 (never 401) so clients don't misread "wrong current password" as session expiry.
* **Code References**: `database/migration_manager.py` (`_migrate_v2_to_v3`), `database/database_manager.py` (`get_token_version`, `bump_token_version`), `svc/auth.py` (`create_access_token`, `token_version_of`), `svc/dependencies.py` (`get_current_trainee`), `service/auth.py` (`change_password`), `svc/routers/auth.py` (`change_password`).

---

### ADR 007: Catalog-Side Recovery Identity & Single-Use Reset Tokens
* **Status**: Accepted
* **Rule**: Recovery emails (`trainee_emails`) and reset tokens (`password_reset_tokens`) live in the **shared catalog DB**, not per-user ledgers, because the logged-out forgot-password flow cannot know which ledger to open. Tables are provisioned at catalog boot (`ensure_account_schema()` outside any held lock). A recovery email is **mandatory**: after login, a minimal gate page (Logout only) blocks dashboard and onboarding until one is saved; onboarding email is collected there, never parsed by the LLM. Tokens are `secrets.token_urlsafe(32)` with only the SHA-256 stored, TTL 30 min (env `RESET_TOKEN_TTL_MINUTES`, clamped 5–120), single-use via atomic `used_at` claim, and redemption bumps `token_version`. Both endpoints are anti-enumeration: `forgot-password` returns the identical 202 message for known/unknown emails, and unknown/expired/used tokens share one 400 error. Strict `3/hour` rate limit; SMTP optional with a console-dev backend (`SMTP_HOST` unset logs the link server-side). The UI transport helper `request_json()` never raises and never calls `st.stop()`, so malformed/HTML/timeout responses surface inline instead of blanking the page.
* **Context**: Ledgers are keyed by trainee_id with no contact channel; classic email reset had no identity to address and no table reachable while logged out. Per-ledger token tables would require scanning every `db/users/*.db` per request.
* **Rationale**: **Local-first compatible recovery.** Catalog-side storage keeps lookup O(1) and lets the admin CLI (`scripts/reset_password.py`) remain the no-email backstop with identical revoke-all semantics. Storing hashes (never raw tokens) and constant-shape responses preserves the existing indistinguishable-credentials posture from `service/auth.py`.
* **Code References**: `database/database_manager.py` (`ensure_account_schema`, `consume_reset_token`, …), `service/password_reset.py`, `service/email_sender.py`, `svc/routers/auth.py` (`forgot-password`, `reset-password`, `email`), `scripts/reset_password.py`, `ui/api_client.py` (`request_json`), `ui/views/auth.py` (`render_email_gate`), `app.py` (post-login gate).

---

### ADR 008: Hardened Local Model Lifecycle (Atomic Download, Explicit Test Mode)
* **Status**: Accepted
* **Rule**: GGUF downloads take a cross-process file lock, re-check under the lock, clean up zero-byte partials, and verify an optional pinned SHA-256/revision (`MODEL_SHA256`, `MODEL_REVISION`); logging replaces `print`. Test doubles engage on explicit `TESTING`/`SKIP_LLM_LOAD`/`CI`, plus a pytest-only fallback **iff the model file is absent** — a test run can therefore never trigger a multi-GB download. Lazy proxies no longer load on dunder/repr access, and the judge shares `SafeChatLlamaCpp` (tool-call dedup) with its own mock branch (previously it always pulled the 9B GGUF, even in CI).
* **Context**: The loader used an import-time stale path, a `threading.Lock` that can't stop multi-worker OOM, string-matched `ValueError`s, hardcoded `n_ctx`/`max_tokens`, and `"pytest" in sys.modules` detection that flipped production behavior whenever pytest was merely installed.
* **Rationale**: **No-surprise edge inference.** Every change removes a class of startup/OOM flakiness while keeping the public surface (`get_llm`, `get_judge_llm`, `llm`, `judge_llm`) stable; inference tuning is now env-overridable (`LLM_N_CTX`, `LLM_MAX_TOKENS`, `LLM_THREADS`, honoring `OMP_NUM_THREADS`).
* **Code References**: `utils/model_downloader.py` (`_file_lock`, `_should_use_mock`, `_attach_prompt_cache`, `_LazyLLMProxy`).

---

### ADR 009: Deterministic Personal Record Detection (Exact-Rep + e1RM)
* **Status**: Accepted
* **Rule**: After every session batch insert, `evaluate_session_prs` reduces the working sets to the heaviest set per exact rep count plus the best-e1RM set and records only values that **strictly exceed** the trainee's historical max (ties are never PRs). Two record types are stored append-only in `personal_records`: `max_weight` scoped to the exact rep count (heaviest 5-rep set) and `max_e1rm` exercise-wide. At most one row per record type per movement per session is written. Warmup-flagged, zero-load, and zero-rep sets are ignored. Migration v3→v4 creates the table and backfills history with first-achievement timestamps. The `🏆 New PR` lines are injected deterministically into the debrief's Overload Deltas block and the dashboard renders global + per-movement PR shelves; no LLM is involved anywhere in the path.
* **Context**: e1RM was already computed per set for overload deltas, but PRs were never detected, so the ledger could not answer "is this my best 5?" — and forward-only recording would have set trivially-true PRs on the first post-ship session against an empty table.
* **Rationale**: **Zero-Drift Engineering + motivation loop.** Exact-rep brackets mirror how lifters actually benchmark (a 3-rep and a 5-rep max are different achievements), while strict-greater comparison keeps the ledger stable under ties and re-logged sessions. Backfill-on-migration (ADR 005) makes the timeline truthful from day one without a new dependency or LLM surface.
* **Code References**: `agent/progression_engine.py` (`check_and_record_pr`, `evaluate_session_prs`), `service/workouts.py` (`commit_session`), `agent/debrief.py` (`format_pr_events`), `database/migration_manager.py` (`_migrate_v3_to_v4`), `service/dashboard.py`, `svc/routers/dashboard.py` (`/dashboard/personal-records`).

---

### ADR 010: Consented Remember-Me Cookie Sessions
* **Status**: Accepted
* **Rule**: The Streamlit client persists the bearer JWT in a browser cookie (`mayos_jwt`) only after the trainee ticks "Remember me on this device" on login/register. Remembered tokens are minted with `JWT_REMEMBER_ME_HOURS` (default 720 h = 30 days, clamped 1–8760); the default 2-hour token path is unchanged. On boot the client hydrates session state from the cookie (unverified `sub` read for display/gating only — every API call still sends the bearer for server-side verification); invalid or expired tokens fall through to the existing 401 clear-and-flash flow. Logout and any 401 clear the cookie. All cookie operations are best-effort: without the component the app behaves exactly as before.
* **Context**: A browser refresh starts a fresh Streamlit websocket session, wiping in-memory state, so trainees were bounced to the login page on every refresh; the 2-hour default TTL compounded it, and no persistence mechanism existed.
* **Rationale**: **Local-first convenience without weakening server authority.** The cookie is a client-side memory of the same revocable JWT — ADR 006 `tv` epoch bumps and `jti` logout revocation still apply instantly — and consent is explicit. Storage is a plain (non-HttpOnly, SameSite=Lax, Path=/) cookie on the Streamlit origin because the FastAPI service is only ever called server-side by the UI process; the browser never talks to the API directly. Degradation is safe by construction (every cookie operation wrapped).
* **Code References**: `ui/cookies.py`, `ui/session.py` (`restore_auth_from_cookies`, `establish_session`), `ui/views/auth.py`, `app.py`, `svc/auth.py` (`remember_me_hours`), `svc/routers/auth.py` (login/register/claim), `svc/schemas.py` (`TraineeIn.remember_me`).

---

### ADR 011: Movement-Slot Blueprints (Belghamdi-Style) as the Program Generation Unit
* **Status**: Accepted
* **Rule**: Program assembly is driven by ordered **movement slots** per day (`incline_press`, `horizontal_row`, `biceps_preacher`, `forearm_wrist`, `adductors`, ...), not one-exercise-per-muscle. `agent/program_blueprints.py` owns the slot SQL patterns/equipment preferences, prescriptions (warm-up sets 0–4, working sets 1–4, rep windows, 2–5 min rests), Arabic cues, general warm-up blocks (Pallof/scapula push plus/glute bridge/dead bug/reverse hyper) and the split day templates. `agent/program_rules.py` resolves slots against the catalog (word-boundary exclusions, name-pattern and equipment ranking) and routes split preferences deterministically (Full Body, Upper/Lower, Arnold, Arnold x U/L, Anterior/Posterior, PPL, female glute-biased). Exercise-selection output carries `slot_key`, `warmup_sets`, Arabic notes, and program/day-level instructions; the xlsx export mirrors the source sheets' Arabic column layout.
* **Context**: Generated programs were fixed at exactly 5 exercises (one per hardcoded muscle target), almost never selected direct biceps/triceps/forearm work, never included incline chest, shrugs, adductors or the front lat pulldown machine, and had no Arnold or anterior/posterior option. Root causes: 5-muscle presets, a `min(target)`/machine-first candidate ordering that buried cable/dumbbell movements, target vocabulary missing `forearms`/`adductors`/`traps`, and SQL `LIKE '%term%'` exclusions whose substrings silently killed valid movements (`reach` → preacher, `run` → crunch, `chin` → machine).
* **Rationale**: **Reference-program fidelity + Zero-Drift structure.** The seven reference sheets in `programs/` (Belghamdi Full Body, Arnold x U/L, Muscle Mommies, Sardy U/L, personal microcycles) all encode the same structural contract: fixed movement slots per day type (FB 8–12, Upper 7–12, Lower 6–10), mandatory weekly coverage of flat+incline chest, vertical+horizontal pull, glutes, both arm slots, forearms, adductors, calves and shrugs, 1–3 working sets with separate ramp sets, failure-based intensity, and 3–5 minute rests. Encoding slots as deterministic Python keeps the LLM bounded to split-shape selection while the heuristics (set/rep/rest, coverage, equipment ranking) remain auditable and testable; word-boundary exclusion in Python fixes the substring collisions at the source.
* **Code References**: `agent/program_blueprints.py` (`SLOT_SPECS`, `WARMUP_SPECS`, `DayBlueprint`, `build_split_days`, `PROGRAM_INSTRUCTIONS_AR`), `agent/program_rules.py` (`fetch_slot_candidates`, `fetch_warmup_candidates`, `_is_excluded`, `_name_rank_sql`, `resolve_split`, `SYSTEM_SPLIT_PROMPT`), `agent/program_generator.py` (`assemble_deterministic_day`, `build_warmup_block`), `agent/ProgramState.py` (`WarmupExerciseSchema`, `ProgramExerciseSchema.slot_key/warmup_sets`), `database/migration_manager.py` (`_migrate_v4_to_v5`), `utils/exporter.py`, `tests/test_program_blueprints.py`.
