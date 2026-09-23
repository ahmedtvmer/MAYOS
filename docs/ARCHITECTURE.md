# Myos: System Architecture, LangGraph Workflows & Execution Topologies

This document provides a comprehensive architectural specification of the Myos engine, detailing state graphs, LangChain/LangGraph execution pipelines, sub-millisecond fast-path routing, data flow topologies, and runtime data contracts.

---

## 1. High-Level System Architecture

The following diagram illustrates the lifecycle of a trainee interaction, showing how the Flutter app (the product client; the legacy Streamlit interface serves no users per ADR 017) reaches the engine through the FastAPI service layer (JWT auth, rate limiting, SSE delivery), and how the LangGraph state engine, in-process vector database, and local quantized GGUF runtime interact:

```mermaid
flowchart TD
    subgraph UI_Layer ["Presentation Layer (Flutter app)"]
        UI_Input["User Turn (Chat / Set Log / Split Mutation)"]
        UI_Render["Token-by-Token Stream / Metric Dashboards"]
    end

    subgraph Service_Layer ["Service Layer (FastAPI, single replica)"]
        API_Auth["JWT Guard, Rate Limits, Ledger Binding"]
        API_SSE["SSE Chat Stream (/chat/messages)"]
    end

    subgraph LangGraph_Engine ["LangGraph Execution Graph"]
        State_Init["AssistantState Initialization & Hydration"]
        Fast_Router{"Deterministic Regex Fast-Path"}

        subgraph Deterministic_Nodes ["Zero-LLM Execution Nodes (<0.03ms + Tier-1 guard)"]
            Node_Clinical["clinical_intercept_node"]
            Node_Sub["exercise_substitution_node"]
            Node_Mutation["program_mutation_node"]
            Node_Catalog["catalog_search_node"]
        end

        subgraph In_Process_LLM ["Local Inference Core (SafeChatLlamaCpp)"]
            Context_Clamper["6-Message Context Tail Clamper"]
            Telemetry_Hydrator["5-Line Compact Telemetry Injection"]
            Prompt_Assembler["System Core + Coaching Directives"]
            LLM_Stream["SafeChatLlamaCpp (Qwen3.5-4B GGUF)"]
            Chunk_Sanitizer["Tool Call Delta Deduplicator"]
        end
    end

    subgraph Storage_Layer ["Dual-Database Topology"]
        DBM["DatabaseManager (threading.local Router)"]
        User_WAL[("Private User Ledger\n(db/users/<id>.db - WAL)")]
        Catalog_Shared[("Shared Catalog\n(db/catalog.db - exercises + account tables)")]
        Vec_Index[("sqlite-vec Virtual Table\n(vec_exercises - 384d Cosine)")]
    end

    UI_Input --> API_Auth
    API_Auth --> State_Init
    State_Init --> Fast_Router

    %% Deterministic Fast Paths
    Fast_Router -- "Acute Red Flag Pattern" --> Node_Clinical
    Fast_Router -- "Swap / Candidate Pattern" --> Node_Sub
    Fast_Router -- "Rebuild / Frequency Pattern" --> Node_Mutation
    Fast_Router -- "Search / Lookup Pattern" --> Node_Catalog

    %% Non-Deterministic Coaching Path
    Fast_Router -- "Coaching Q&A Pass-Through" --> Context_Clamper

    Context_Clamper --> Telemetry_Hydrator
    Telemetry_Hydrator --> Prompt_Assembler
    Prompt_Assembler --> LLM_Stream
    LLM_Stream --> Chunk_Sanitizer
    Chunk_Sanitizer --> API_SSE
    API_SSE --> UI_Render

    %% Deterministic Node Storage Operations
    Node_Clinical --> API_SSE
    Node_Sub <--> DBM
    Node_Mutation <--> DBM
    Node_Catalog <--> DBM

    %% Database Routing
    DBM --> User_WAL
    DBM --> Catalog_Shared
    Catalog_Shared --- Vec_Index
```

> The service layer owns identity and transport: bearer JWTs are verified against the catalog account registry (status, capability, session epoch) and the ledger's revocation list before any graph node runs, and graph output is re-streamed as Server-Sent Events. See §9 for the full request lifecycle and [`AUTHENTICATION.md`](AUTHENTICATION.md) for the auth specification.

---

## 2. LangGraph State Schema & Data Contracts

The runtime state (`AssistantState`) flows immutably across nodes in `agent/assistant_graph.py`:

```python
IntentType = Literal[
    "clinical_intercept",
    "banned_movement",
    "telemetry_intercept",
    "exercise_history",
    "exercise_substitution",
    "program_mutation",
    "catalog_search",
    "coaching_qa",
    "composite_intent",
]


class AssistantState(TypedDict):
  messages: Annotated[Sequence[BaseMessage], add_messages]
  trainee_id: str
  coach_tone: str
  custom_instructions: str
  preferred_name: str | None
  telemetry_context: str | None
  intent: IntentType | None
  intent_metadata: dict[str, Any]
  active_intents: list[dict[str, Any]] | None
  program_updated: bool
  response_content: str | None
  pipeline_error: str | None
```

### State Node Execution Lifecycle

```mermaid
stateDiagram-v2
    [*] --> HydrateContext: Incoming Turn
    HydrateContext --> RouterNode: Trainee Snapshot Injected
    
    state RouterNode {
        [*] --> ClinicalCheck
        ClinicalCheck --> HistoryFollowupCheck: Negative
        HistoryFollowupCheck --> ClauseSplitCheck: Not a follow-up
        ClauseSplitCheck --> ActionHintCheck: Single clause
        ActionHintCheck --> CoachingQA: Negative (<0.02ms)
        ActionHintCheck --> SubRegexCheck: Positive
        ActionHintCheck --> MutationRegexCheck: Positive
        ActionHintCheck --> CatalogRegexCheck: Positive
    }

    RouterNode --> ClinicalInterceptNode: intent == clinical_intercept
    RouterNode --> ExerciseHistoryNode: intent == exercise_history
    RouterNode --> SubstitutionNode: intent == exercise_substitution
    RouterNode --> ProgramMutationNode: intent == program_mutation
    RouterNode --> CatalogSearchNode: intent == catalog_search
    RouterNode --> CompositeIntentNode: intent == composite_intent
    RouterNode --> LLMStreamingNode: intent == coaching_qa

    ClinicalInterceptNode --> SmoothStream: Yield Hardcoded Directive
    ExerciseHistoryNode --> SmoothStream: Deterministic Ledger Read
    SubstitutionNode --> SmoothStream: Execute Ledger Mutation
    ProgramMutationNode --> SmoothStream: Rebuild Program Days
    CatalogSearchNode --> SmoothStream: Query sqlite-vec
    CompositeIntentNode --> SmoothStream: Sequential Sub-Intent Dispatch
    LLMStreamingNode --> SmoothStream: Yield Quantized Delta Chunks

    SmoothStream --> [*]: SSE Frames to FastAPI Client
```

> Multi-clause turns (e.g. *"swap bench for incline press and how many reps for curls?"*) are split by `RE_CLAUSE_SPLIT` into per-clause sub-intents. `composite_intent_node` re-checks clinical safety across the whole turn, then dispatches each clause through its own handler with prior results injected as dialogue context.

---

## 3. Deterministic Fast-Path Routing Logic

The fast-path router eliminates LLM classification latency on routine user queries through a multi-tiered hierarchy of compiled regular expressions:

```mermaid
flowchart TD
    Start(["Raw Trainee Query"]) --> Tier0{"Tier 0: Clinical Safety\n0a: unconditional trauma regex\n0b: context-gated ambiguous tokens\nSemantic guard: BGE cosine >= 0.70"}

    Tier0 -- "Acute Trauma / Diagnosis Request" --> ClinNode["clinical_intercept_node\n(Halt movement / Decline diagnosis)"]
    Tier0 -- Safe --> Banned{"Banned Biomechanics\nRE_BANNED_MOVEMENT"}

    Banned -- "Behind-Neck / Upright Row / Burn Sets" --> BannedNode["banned_movement_node\n(Deterministic VETO)"]
    Banned -- Safe --> Hist{"Exercise History\nWhole-session / performance / history patterns"}

    Hist -- "History Lookup" --> HistNode["exercise_history_node\n(Deterministic ledger comparison)"]
    Hist -- No --> Telemetry{"Dynamic Ledger Reconciler\nreconcile_telemetry_query()"}

    Telemetry -- "Unlogged Lift / Set Count Audit" --> TelemetryNode["telemetry_intercept_node\n(Zero-data refusal / Audit)"]
    Telemetry -- "Conceptual or Logged" --> Mutations{"Structured Mutations\nRE_PROGRAM_MUTATION | RE_EXPLICIT_SWAP"}

    Mutations -- "Split Rebuild / Frequency Change" --> MutNode["program_mutation_node"]
    Mutations -- "Movement Swap / Candidate Lookup" --> SubNode["exercise_substitution_node"]
    Mutations -- "None" --> Search{"Catalog Search\nRE_SEARCH_TOKENS"}

    Search -- "Search / Lookup Query" --> CatNode["catalog_search_node"]
    Search -- "General Coaching Question" --> GenNode["generation_node\n(Local Qwen3.5-4B Inference)"]
```

> Tier-0b is where DOMS slang is separated from genuine injury reports: ambiguous tokens (`swelling`, `tear/tore/torn`, `pop`, `tweaked`) only intercept with explicit injury context — mechanism perception (*"felt a pop"*), anatomical proximity (joints, tendons, pec/bicep/ACL…), or body-part objects. Fatigue idioms (*"torn up from leg day"*, *"tweaked my program"*, painless *"knees pop when"*) defer to the Tier-1 semantic guard. See ADR 002 in [`DECISIONS.md`](../DECISIONS.md).

---

## 4. Dual-Database Topology & Thread-Local Connection Model

Myos combines a shared exercise catalog (`catalog.db` — seeded exercises, the `sqlite-vec` index, and the account-recovery identity tables) with dynamic, isolated per-user transaction ledgers (`db/users/<user_id>.db`). The Flutter client never touches these directly: it calls the FastAPI service, and each API worker thread binds the ledger for the verified account through `DatabaseManager`'s `threading.local` routing. Cross-tenant leakage is physically impossible, and SQLite Write-Ahead Logging (`WAL`) prevents write contention:

```mermaid
sequenceDiagram
    autonumber
    actor Worker as API Worker Thread (Thread A)
    participant DBM as DatabaseManager (_local)
    participant UserDB as User Ledger (WAL Mode)
    participant CatalogDB as Attached Shared Catalog
    participant VecExt as sqlite-vec Virtual Table

    Worker->>DBM: switch_user("ahmed")
    DBM->>UserDB: sqlite3.connect("db/users/ahmed.db")
    DBM->>UserDB: PRAGMA journal_mode = WAL;
    DBM->>UserDB: PRAGMA foreign_keys = ON;
    DBM->>UserDB: ATTACH DATABASE 'catalog.db' AS catalog;
    DBM->>UserDB: CREATE TEMP VIEW exercises AS SELECT * FROM catalog.exercises;
    
    Note over Worker,UserDB: Batch Set Logging Transaction
    Worker->>DBM: log_workout_sets_batch(15 sets)
    DBM->>UserDB: BEGIN IMMEDIATE TRANSACTION;
    DBM->>UserDB: executemany(INSERT INTO workout_sets ...)
    DBM->>UserDB: COMMIT;
    
    Note over Worker,VecExt: Biomechanical Vector Alternative Lookup
    Worker->>DBM: search_similar_exercises(vector, limit=5)
    DBM->>CatalogDB: SELECT candidate rows
    CatalogDB->>VecExt: MATCH embedding AND k = 15
    VecExt-->>CatalogDB: Cosine KNN results
    CatalogDB-->>DBM: Filter EXCLUDED_BIOMECHANICAL_PATTERNS
    DBM-->>Worker: Return top 5 valid movements
```

### Ledger Schema Evolution (ADR 005)

User ledgers carry a schema version in `PRAGMA user_version` (current target: **v4**) and migrate **lazily** when mounted by `switch_user()`:

* On upgrade, an atomic pre-migration snapshot is written with `sqlite3.Connection.backup()` (WAL-safe, online) into `db/backups/<user>/`, followed by sequential migration steps inside a transaction.
* A 3+1 retention policy keeps three rolling snapshots plus immutable pre-migration backups; failure triggers rollback from the snapshot.
* **v3** adds `auth_credentials.token_version`; for enrolled accounts, the authoritative session epoch now lives in the catalog account registry (`accounts.session_epoch`) and is bumped on password changes and resets (ADR 006/015). An enrolled ledger without a password hash uses the one-time claim flow; a bare local ledger requires the opted-in import path (ADR 019).
* **v4** adds `personal_records` and backfills historical PRs (heaviest set per exact rep count + best e1RM) from `workout_sets` with first-achievement timestamps (ADR 009).

### Catalog Account Tables (ADR 007)

Password recovery needs an email → account mapping while **logged out**, so recovery identity lives in the shared catalog (not per-user ledgers):

| Table | Purpose |
| :--- | :--- |
| `trainee_emails` | Unique recovery address per account (keyed by immutable account id) |
| `password_reset_tokens` | SHA-256-hashed, single-use, TTL-clamped reset tokens (keyed by immutable account id) |

Both are provisioned idempotently at catalog boot. See [`AUTHENTICATION.md`](AUTHENTICATION.md) for the full specification.

---

## 5. Token Streaming & Tool-Call Sanitization Flow

To prevent `llama-cpp-python` streaming tool calls from corrupting Pydantic structured output parsers via repeated function name concatenation, `SafeChatLlamaCpp` intercepts the raw C++ chunk stream:

```mermaid
sequenceDiagram
    autonumber
    participant Engine as SafeChatLlamaCpp
    participant CppCore as llama_cpp (C++ Runtime)
    participant Sanitizer as _filter_tool_chunks()
    participant UI as SSE Client (FastAPI /chat/messages)

    Engine->>CppCore: stream(prompt_payload)
    
    rect rgb(240, 248, 255)
        Note over CppCore,Sanitizer: Chunk 0 (First Frame)
        CppCore->>Sanitizer: Chunk 0: {id: 0, name: "SaveProfile", args: "{"}
        Sanitizer->>Sanitizer: seen_tool_indices.add(0)
        Sanitizer-->>UI: Yield Chunk 0 (Retains "SaveProfile")
    end

    rect rgb(255, 245, 245)
        Note over CppCore,Sanitizer: Chunks 1 to N (Delta Frames)
        CppCore->>Sanitizer: Chunk 1: {id: 0, name: "SaveProfile", args: "gender\":"}
        Sanitizer->>Sanitizer: Index 0 already seen -> tc["name"] = None
        Sanitizer-->>UI: Yield Chunk 1 ({id: 0, name: None, args: "gender\":"})
        
        CppCore->>Sanitizer: Chunk 2: {id: 0, name: "SaveProfile", args: "male\"}"}
        Sanitizer->>Sanitizer: Index 0 already seen -> tc["name"] = None
        Sanitizer-->>UI: Yield Chunk 2 ({id: 0, name: None, args: "male\"}"})
    end

    Note over UI: Aggregator parses clean JSON payload without string duplication
```

---

## 6. Biomechanical Auto-Regulation State Machine

During active workout logging in Tab 2, working sets are auto-regulated using RPE-adjusted effective 1RM calculations, Olympic barbell plate quantization, and fatigue thresholds:

```mermaid
flowchart TD
    LogSet["Logged Set: Weight (w), Reps (r), RPE (e)"] --> CalcE1RM["Compute Effective 1RM:\ne1RM = w * (1 + (r + (10 - e)) / 30)"]
    
    CalcE1RM --> CheckOvershoot{"RPE Overshoot?\n(e >= 10.0 & target_rpe <= 8.5)"}
    
    CheckOvershoot -- Yes --> OvershootAction["Status: RPE_OVERSHOOT_DELOAD\nStep load down by -2.5kg\nRe-establish reserve"]
    CheckOvershoot -- No --> CheckTopCorridor{"Hit Rep Ceiling?\n(r >= target_reps_max & e <= target_rpe)"}
    
    CheckTopCorridor -- Yes --> ProgressionUp["Status: PROGRESSION_UP\nAdvance load by equipment step:\n+2.5kg Barbell / +2.0kg Dumbbell"]
    CheckTopCorridor -- No --> CheckVelocity{"Velocity Surplus?\n(r >= target_reps_min & e <= target_rpe - 1.5)"}
    
    CheckVelocity -- Yes --> DynamicUpscale["Status: DYNAMIC_UPSCALE\nStep load up by reserve delta"]
    CheckVelocity -- No --> Consolidate["Status: CONSOLIDATING\nMaintain weight; advance rep target"]

    OvershootAction --> SnapPlates
    ProgressionUp --> SnapPlates
    DynamicUpscale --> SnapPlates
    Consolidate --> SnapPlates

    subgraph SnapPlates ["Olympic Plate Quantization Engine"]
        RoundStep["Snap Target to Nearest Symmetric 2.5kg Step"]
        SubtractBar["Per-Side Remainder = (Snapped Load - 20kg) / 2"]
        GreedyFit["Greedy Plate Matching:\n[25kg, 20kg, 15kg, 10kg, 5kg, 2.5kg, 1.25kg]"]
        OutputDisplay["Output Plate String:\n'Bar + [25, 10, 1.25] kg/side'"]
        
        RoundStep --> SubtractBar --> GreedyFit --> OutputDisplay
    end

    OutputDisplay --> PotentiatingWarmups["Generate 3-Set Potentiating Ramp:\n- Set 1: 40% x 5 reps (Pattern Calibration)\n- Set 2: 65% x 3 reps (Acceleration Intent)\n- Set 3: 85% x 1 rep (Neural Potentiation)"]
```

---

## 7. Context Clamping & Telemetry Hydration Pipeline

To maintain flat inference latency and prevent token evaluation degradation across long training histories, Myos replaces full chat serialization with a bounded context pipeline:

```mermaid
flowchart LR
    subgraph Raw_History ["Persistent SQLite State"]
        H1["Turn 1...N-6 (Archived)"]
        H2["Turn N-5"]
        H3["Turn N-4"]
        H4["Turn N-3"]
        H5["Turn N-2"]
        H6["Turn N-1"]
        H7["Turn N (Current User Query)"]
    end

    subgraph Clamping_Pipeline ["Context Tail Clamper (TAIL_WINDOW_SIZE = 6)"]
        H1 -.->|Dropped from Prompt| Trash["Evicted from Active n_ctx"]
        H2 --> Tail
        H3 --> Tail
        H4 --> Tail
        H5 --> Tail
        H6 --> Tail
        H7 --> Tail
        Tail["6-Message Active Dialogue Tail"]
    end

    subgraph Telemetry_Synthesis ["Compact Telemetry Generator"]
        DB_Profile[("user_profile")] --> Synth["get_compact_telemetry()"]
        DB_Prog[("training_programs")] --> Synth
        DB_Sets[("workout_sets")] --> Synth
        DB_Fatigue[("readiness_eval")] --> Synth
        Synth --> TelemetryStr["5-Line Compact Snapshot:\n- Trainee Biometrics & Proportions\n- Split & Frequency Metadata\n- Prior Session Top Set\n- Progression Trajectory Signals\n- Systemic Recovery State"]
    end

    subgraph Prompt_Payload ["Constructed LLM Payload"]
        SystemCore["STATIC_SYSTEM_CORE\n(Directives, Word Budgets, Scrubber Rules)"]
        TelemetryStr --> SystemBlock["System Message"]
        SystemCore --> SystemBlock
        SystemBlock --> FinalPayload["Model Context Window (n_ctx = 2048 by default via LLM_N_CTX)"]
        Tail --> FinalPayload
    end

    FinalPayload --> Inference["SafeChatLlamaCpp (flat clamped latency, ~4 s on GPU offload)"]

---

## 8. Hybrid Post-Workout Debrief Architecture

To prevent small quantized models (4B) from hallucinating mathematical calculations or echoing bracketed prompt templates, session debriefs are assembled via a hybrid deterministic-generative pipeline:

1. **Deterministic Metrics Calculation (`format_overload_deltas`)**:
   Calculates e1RM deltas, load advancements (+2.5 kg), and rep-corridor holds directly in Python. If no load advancement occurred, yields an exact maintenance directive.
2. **Deterministic PR Injection (`format_pr_events`)**:
   `commit_session` runs `evaluate_session_prs` over the session's working sets after the batch insert. Sets that strictly exceed the trainee's historical max (heaviest set per exact rep count and best e1RM, backfilled on migration v4) are appended as `🏆 New PR` lines inside the Overload Deltas block (ADR 009).
3. **Deterministic Fatigue Snapshot (`format_fatigue_cns_check`)**:
   Extracts logged readiness ($X/5$), volume load tonnage, and trainee notes into a pre-formatted markdown block.
4. **Bounded Directive Synthesis (`generate_session_debrief`)**:
   The LLM is tasked *exclusively* with generating 2 to 3 concise bullet points under `**Next Session Directives**:` adhering strictly to active deload RPE caps or progression directives.
```

---

## 9. Service-Layer Request Lifecycle

The Flutter client holds **no** server database, model, or domain logic. Chat and program changes are HTTP calls to the FastAPI service (`svc/`), which owns identity, thread affinity, and streaming; the client may capture workout drafts locally for offline logging and sync them idempotently when connected (ADR 020):

```mermaid
sequenceDiagram
    autonumber
    actor UI as Flutter Client
    participant API as FastAPI Route
    participant Dep as get_current_trainee
    participant Thread as Worker Thread (asyncio.to_thread)
    participant Graph as Assistant Graph / Service Layer
    participant DB as Thread-Local Ledger

    UI->>API: POST /chat/messages (Bearer JWT) + SSE request
    API->>Dep: token_claims -> registry status/capability/epoch -> bind_user -> revocation check
    Dep-->>API: verified trainee id (never from the body)
    API->>Thread: _run_turn(db, trainee, content)
    Thread->>DB: add user message, build tail (6-message window)
    Thread->>Graph: stream_assistant_turn(state)
    Graph-->>Thread: scrubbed token pieces
    Thread-->>API: queue.put(("token", piece))
    API-->>UI: data: {"token": ...} frames (SSE)
    Thread->>DB: persist authoritative assistant message
    API-->>UI: data: {"done": true, "program_updated": ...}
```

Key invariants:

* **Identity is derived only from the verified JWT** — request bodies may carry a `trainee_id`, but it is ignored (schema-level rejection in most routes).
* **Ledger binding happens per thread.** `DatabaseManager` routes connections through `threading.local`, and every worker thread re-runs the registry live/capability/epoch check and re-binds the trainee before touching SQLite (`bind_request` / `_bind_trainee_connection`). This worker-side recheck closes the gap between request-scoped verification and the thread that performs ledger work.
* **Blocking work is isolated.** Sync DB and GGUF inference run on worker threads via `asyncio.to_thread`; llama-cpp calls are additionally serialized by an inference lock and a single-slot semaphore so overload fails fast instead of piling up.
* **Errors never leak.** SSE error frames carry a fixed pipeline-error string; unhandled exceptions return a generic `502` detail.
* **Auth endpoints are rate-limited** (`slowapi`), with strict buckets for login/register and per-token buckets for chat.

> Full endpoint tables, JWT claims, and recovery flows: [`AUTHENTICATION.md`](AUTHENTICATION.md).
