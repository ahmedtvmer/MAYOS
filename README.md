# Myos - Adaptive Resistance Training Engine

A production-ready AI training assistant built with Streamlit and Ollama. Myos autonomously generates personalized resistance training programs, manages workout logs, and adapts prescriptions based on biomechanical principles and progressive overload.

## 🏗️ Core Architecture & Database Model

Myos utilizes a decoupled, multi-tenant SQLite architecture that ensures strict data isolation while eliminating redundant vector storage:

* **Shared Exercise Catalog (`db/catalog.db`):** A static, read-only database storing all core exercise definitions, secondary muscle maps, and dense embeddings inside a `sqlite-vec` virtual table (`vec_exercises`).


* **Isolated Trainee Ledgers (`db/users/{trainee_id}.db`):** Individual, portable SQLite databases generated per user containing their private `user_profile`, generated routines (`training_programs`, `program_days`, `program_exercises`), and session logs (`workout_sessions`, `workout_sets`).


* **Dynamic Catalog Attachment:** When a user logs in, their private database mounts `catalog.db` as an attached database and creates `TEMP VIEW` references, enabling SQL joins across catalog and workout data without duplicating exercise records.



---

### Key Features & Current State

* **Private Authentication Gate:** Trainees authenticate via unique Trainee IDs without exposing other users' accounts or data.


* **Session-Scoped Connections:** `DatabaseManager` runs without application-wide connection state collisions in multi-user Streamlit sessions.


* **Dynamic Persona & Guardrails:** Trainees can configure custom coach personas (e.g., biomechanics-focused, drill sergeant) and explicit behavioral guardrails stored directly in their profile ledger and injected into the LLM system prompt.
* **Warmup & Progression Engine:** Automatic warm-up ramp calculations based on working loads and double-progression directives derived from Epley estimated 1-Rep Max ($\text{e1RM}$) calculations.

---

### Verification & Testing

Verify the two-tier database initialization, vector indexing, and foreign key cascades:

```bash
uv run python scripts/test_db.py

```

Run vector embeddings generation for `catalog.db`:

```bash
uv run python scripts/seed_vectors.py

```

Launch the application:

```bash
uv run streamlit run app.py

```