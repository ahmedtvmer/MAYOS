# Myos: System Architecture, LangGraph Workflows & Execution Topologies

This document provides a comprehensive architectural specification of the Myos engine, detailing state graphs, LangChain/LangGraph execution pipelines, sub-millisecond fast-path routing, data flow topologies, and runtime data contracts.

---

## 1. High-Level System Architecture

The following diagram illustrates the lifecycle of a trainee interaction, showing how the Streamlit UI, LangGraph state engine, in-process vector database, and local quantized GGUF runtime interact:

```mermaid
flowchart TD
    subgraph UI_Layer ["Presentation Layer (Streamlit)"]
        UI_Input["User Turn (Chat / Set Log / Split Mutation)"]
        UI_Render["Token-by-Token Stream / Metric Dashboards"]
    end

    subgraph LangGraph_Engine ["LangGraph Execution Graph"]
        State_Init["AssistantState Initialization & Hydration"]
        Fast_Router{"Deterministic Regex Fast-Path"}
        
        subgraph Deterministic_Nodes ["Zero-LLM Execution Nodes (<0.03ms)"]
            Node_Clinical["clinical_intercept_node"]
            Node_Sub["exercise_substitution_node"]
            Node_Mutation["program_mutation_node"]
            Node_Catalog["catalog_search_node"]
        end

        subgraph In_Process_LLM ["Local Inference Core (SafeChatLlamaCpp)"]
            Context_Clamper["4-Message Context Tail Clamper"]
            Telemetry_Hydrator["5-Line Compact Telemetry Injection"]
            Prompt_Assembler["System Core + Coaching Directives"]
            LLM_Stream["SafeChatLlamaCpp (Qwen 2.5 3B GGUF)"]
            Chunk_Sanitizer["Tool Call Delta Deduplicator"]
        end
    end

    subgraph Storage_Layer ["Dual-Database Topology"]
        DBM["DatabaseManager (threading.local Router)"]
        User_WAL[("Private User Ledger\n(db/users/<id>.db - WAL)")]
        Catalog_RO[("Shared Static Catalog\n(db/catalog.db - Read-Only)")]
        Vec_Index[("sqlite-vec Virtual Table\n(vec_exercises - 384d Cosine)")]
    end

    UI_Input --> State_Init
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
    Chunk_Sanitizer --> UI_Render

    %% Deterministic Node Storage Operations
    Node_Clinical --> UI_Render
    Node_Sub <--> DBM
    Node_Mutation <--> DBM
    Node_Catalog <--> DBM

    %% Database Routing
    DBM --> User_WAL
    DBM --> Catalog_RO
    Catalog_RO --- Vec_Index
```

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
]


class AssistantState(TypedDict):
  messages: Annotated[Sequence[BaseMessage], add_messages]
  trainee_id: str
  coach_tone: str
  custom_instructions: str
  telemetry_context: str | None
  intent: IntentType | None
  intent_metadata: dict[str, Any]
  program_updated: bool
  response_content: str | None
```

### State Node Execution Lifecycle

```mermaid
stateDiagram-v2
    [*] --> HydrateContext: Incoming Turn
    HydrateContext --> RouterNode: Trainee Snapshot Injected
    
    state RouterNode {
        [*] --> ClinicalCheck
        ClinicalCheck --> ActionHintCheck: Negative
        ActionHintCheck --> CoachingQA: Negative (<0.02ms)
        ActionHintCheck --> SubRegexCheck: Positive
        ActionHintCheck --> MutationRegexCheck: Positive
        ActionHintCheck --> CatalogRegexCheck: Positive
    }

    RouterNode --> ClinicalInterceptNode: intent == clinical_intercept
    RouterNode --> SubstitutionNode: intent == exercise_substitution
    RouterNode --> ProgramMutationNode: intent == program_mutation
    RouterNode --> CatalogSearchNode: intent == catalog_search
    RouterNode --> LLMStreamingNode: intent == coaching_qa

    ClinicalInterceptNode --> SmoothStream: Yield Hardcoded Directive
    SubstitutionNode --> SmoothStream: Execute Ledger Mutation
    ProgramMutationNode --> SmoothStream: Rebuild Program Days
    CatalogSearchNode --> SmoothStream: Query sqlite-vec
    LLMStreamingNode --> SmoothStream: Yield Quantized Delta Chunks

    SmoothStream --> [*]: Stream to Streamlit UI
```

---

## 3. Deterministic Fast-Path Routing Logic

The fast-path router eliminates LLM classification latency on routine user queries through a multi-tiered hierarchy of compiled regular expressions:

```mermaid
lowchart TD
    Start(["Raw Trainee Query"]) --> Tier0{"Tier 0: Red Flag & Clinical Safety\nRE_ACUTE_INJURY | RE_DIAGNOSIS"}
    
    Tier0 -- "Acute Trauma / Diagnosis Request" --> ClinNode["clinical_intercept_node\n(Halt movement / Decline diagnosis in 0.005s)"]
    Tier0 -- Safe --> Tier1{"Tier 1: Banned Biomechanics\nRE_BANNED_MOVEMENT"}
    
    Tier1 -- "Behind-Neck / Upright Row / Burn Sets" --> BannedNode["banned_movement_node\n(Deterministic VETO in 0.002s)"]
    Tier1 -- Safe --> Tier2{"Tier 2: Dynamic Ledger Reconciler\nreconcile_telemetry_query()"}
    
    Tier2 -- "Historical Query on Unlogged Lift / Set Count" --> TelemetryNode["telemetry_intercept_node\n(Zero-data refusal / Audit in 0.002s)"]
    Tier2 -- "Conceptual or Logged" --> Tier3{"Tier 3: Structured Mutations\nRE_PROGRAM_MUTATION | RE_EXPLICIT_SWAP"}
    
    Tier3 -- "Split Rebuild / Frequency Change" --> MutNode["program_mutation_node"]
    Tier3 -- "Movement Swap / Candidate Lookup" --> SubNode["exercise_substitution_node"]
    Tier3 -- "None" --> Tier4{"Tier 4: Catalog Search\nRE_SEARCH_TOKENS"}
    
    Tier4 -- "Search / Lookup Query" --> CatNode["catalog_search_node"]
    Tier4 -- "General Coaching Question" --> GenNode["generation_node\n(Local Qwen 2.5 3B Inference)"]
```

---

## 4. Dual-Database Topology & Thread-Local Connection Model

Myos combines a static, read-only exercise catalog (`catalog.db`) with dynamic, isolated per-user transaction ledgers (`db/users/<user_id>.db`). Cross-tenant leakage is physically impossible, and SQLite Write-Ahead Logging (`WAL`) prevents write contention:

```mermaid
sequenceDiagram
    autonumber
    actor Trainee as Streamlit Session (Thread A)
    participant DBM as DatabaseManager (_local)
    participant UserDB as User Ledger (WAL Mode)
    participant CatalogDB as Attached Catalog (Read-Only)
    participant VecExt as sqlite-vec Virtual Table

    Trainee->>DBM: switch_user("ahmed")
    DBM->>UserDB: sqlite3.connect("db/users/ahmed.db")
    DBM->>UserDB: PRAGMA journal_mode = WAL;
    DBM->>UserDB: PRAGMA foreign_keys = ON;
    DBM->>UserDB: ATTACH DATABASE 'catalog.db' AS catalog;
    DBM->>UserDB: CREATE TEMP VIEW exercises AS SELECT * FROM catalog.exercises;
    
    Note over Trainee,UserDB: Batch Set Logging Transaction
    Trainee->>DBM: log_workout_sets_batch(15 sets)
    DBM->>UserDB: BEGIN IMMEDIATE TRANSACTION;
    DBM->>UserDB: executemany(INSERT INTO workout_sets ...)
    DBM->>UserDB: COMMIT;
    
    Note over Trainee,VecExt: Biomechanical Vector Alternative Lookup
    Trainee->>DBM: search_similar_exercises(vector, limit=5)
    DBM->>CatalogDB: SELECT candidate rows
    CatalogDB->>VecExt: MATCH embedding AND k = 15
    VecExt-->>CatalogDB: Cosine KNN results
    CatalogDB-->>DBM: Filter EXCLUDED_BIOMECHANICAL_PATTERNS
    DBM-->>Trainee: Return top 5 valid movements
```

---

## 5. Token Streaming & Tool-Call Sanitization Flow

To prevent `llama-cpp-python` streaming tool calls from corrupting Pydantic structured output parsers via repeated function name concatenation, `SafeChatLlamaCpp` intercepts the raw C++ chunk stream:

```mermaid
sequenceDiagram
    autonumber
    participant Engine as SafeChatLlamaCpp
    participant CppCore as llama_cpp (C++ Runtime)
    participant Sanitizer as _filter_tool_chunks()
    participant UI as Streamlit (st.write_stream)

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
        H1["Turn 1...N-5 (Archived)"]
        H2["Turn N-4"]
        H3["Turn N-3"]
        H4["Turn N-2"]
        H5["Turn N-1"]
        H6["Turn N (Current User Query)"]
    end

    subgraph Clamping_Pipeline ["Context Tail Clamper (TAIL_WINDOW_SIZE = 4)"]
        H1 -.->|Dropped from Prompt| Trash["Evicted from Active n_ctx"]
        H3 --> Tail
        H4 --> Tail
        H5 --> Tail
        H6 --> Tail
        Tail["4-Message Active Dialogue Tail"]
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
        SystemBlock --> FinalPayload["Model Context Window (n_ctx <= 512 tokens)"]
        Tail --> FinalPayload
    end

    FinalPayload --> Inference["SafeChatLlamaCpp (Flat ~7s CPU Invariant)"]

---

## 8. Hybrid Post-Workout Debrief Architecture

To prevent small language models (3B) from hallucinating mathematical calculations or echoing bracketed prompt templates, session debriefs are assembled via a hybrid deterministic-generative pipeline:

1. **Deterministic Metrics Calculation (`format_overload_deltas`)**:
   Calculates e1RM deltas, load advancements (+2.5 kg), and rep-corridor holds directly in Python. If no load advancement occurred, yields an exact maintenance directive.
2. **Deterministic Fatigue Snapshot (`format_fatigue_cns_check`)**:
   Extracts logged readiness ($X/5$), volume load tonnage, and trainee notes into a pre-formatted markdown block.
3. **Bounded Directive Synthesis (`generate_session_debrief`)**:
   The LLM is tasked *exclusively* with generating 2 to 3 concise bullet points under `**Next Session Directives**:` adhering strictly to active deload RPE caps or progression directives.
```