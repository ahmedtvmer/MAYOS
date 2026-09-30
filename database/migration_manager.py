# database/migration_manager.py
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from utils.logger import MyosLogger
from utils.equipment_access import (
    EQUIPMENT_ACCESS_VALUES,
    map_equipment_access,
)

logger = MyosLogger().get_logger(__name__)

# Current target schema version for all user ledgers
CURRENT_LEDGER_SCHEMA_VERSION: int = 17

_EQUIPMENT_ACCESS_NOT_IN = "NEW.equipment_access NOT IN (" + ", ".join(
    "'" + value.replace("'", "''") + "'" for value in EQUIPMENT_ACCESS_VALUES
) + ")"

EQUIPMENT_ACCESS_DDL: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS user_profile_equipment_access_insert"
    " BEFORE INSERT ON user_profile"
    f" WHEN {_EQUIPMENT_ACCESS_NOT_IN}"
    " BEGIN SELECT RAISE(ABORT, 'Invalid Equipment access'); END",
    "CREATE TRIGGER IF NOT EXISTS user_profile_equipment_access_update"
    " BEFORE UPDATE OF equipment_access ON user_profile"
    f" WHEN {_EQUIPMENT_ACCESS_NOT_IN}"
    " BEGIN SELECT RAISE(ABORT, 'Invalid Equipment access'); END",
)

#: Performed-date correction DDL (ADR 035). Kept in one place so the
#: fresh-create path (``DatabaseManager.create_ledger_schema``) and the v10->v11
#: migration cannot drift apart.
PERFORMED_DATE_CORRECTIONS_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS performed_date_corrections ("
    " id TEXT PRIMARY KEY,"
    " session_id TEXT NOT NULL,"
    " previous_date TEXT NOT NULL,"
    " corrected_date TEXT NOT NULL,"
    " corrected_at TEXT NOT NULL,"
    " FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_performed_date_corrections_session"
    " ON performed_date_corrections(session_id)",
)

#: Structured onboarding intake DDL (ADR 021). ``intake_answers`` stores one
#: named, validated decision per row (the value as JSON) with the timestamp it
#: was last written and whether a legacy three-step intake prefilled it.
#: ``intake_state`` is the single-row status row: in_progress vs confirmed, the
#: hosted-processing disclosure acknowledgement, and the replayed confirmation
#: result so a re-confirm never generates a second program. Kept in one place so
#: the fresh-create path and the v11->v12 migration cannot drift apart.
INTAKE_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS intake_answers ("
    " field TEXT PRIMARY KEY,"
    " value TEXT NOT NULL,"
    " prefilled INTEGER NOT NULL DEFAULT 0,"
    " updated_at TEXT NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS intake_state ("
    " id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
    " status TEXT NOT NULL DEFAULT 'in_progress',"
    " disclosure_acknowledged INTEGER NOT NULL DEFAULT 0,"
    " confirmed_at TEXT,"
    " program_name TEXT,"
    " weekly_frequency INTEGER,"
    " program_message TEXT,"
    " updated_at TEXT NOT NULL"
    ")",
)

#: Warm-up movements live outside working-set history and progression queries.
SESSION_WARMUP_SETS_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS session_warmup_sets ("
    " session_id TEXT NOT NULL,"
    " movement_index INTEGER NOT NULL CHECK (movement_index >= 0),"
    " exercise_id TEXT,"
    " exercise_name TEXT NOT NULL,"
    " set_index INTEGER NOT NULL CHECK (set_index BETWEEN 1 AND 10),"
    " weight_kg REAL CHECK (weight_kg IS NULL OR weight_kg BETWEEN 0 AND 500),"
    " reps INTEGER NOT NULL CHECK (reps BETWEEN 1 AND 50),"
    " logged_at TEXT NOT NULL,"
    " PRIMARY KEY (session_id, movement_index, set_index),"
    " FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_session_warmup_sets_session"
    " ON session_warmup_sets(session_id, movement_index, set_index)",
)

#: Cardio is a session fact outside working-set history and progression.
SESSION_CARDIO_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS session_cardio ("
    " session_id TEXT PRIMARY KEY,"
    " prescription TEXT NOT NULL CHECK (length(prescription) BETWEEN 1 AND 500),"
    " minutes INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 600),"
    " logged_at TEXT NOT NULL,"
    " FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE"
    ")",
)

CHECKPOINT_REVIEWS_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS checkpoint_reviews ("
    " checkpoint INTEGER PRIMARY KEY CHECK (checkpoint > 0),"
    " session_id TEXT NOT NULL UNIQUE,"
    " period_start TEXT NOT NULL,"
    " period_end TEXT NOT NULL,"
    " facts_json TEXT NOT NULL,"
    " rating_json TEXT NOT NULL,"
    " text TEXT,"
    " text_language TEXT,"
    " last_attempt_at TEXT,"
    " created_at TEXT NOT NULL,"
    " opened_at TEXT,"
    " FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE"
    ")",
)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Adds auth_credentials for password hashes (legacy ledgers stay unclaimed)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_credentials (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            password_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Adds per-ledger token_version so password changes/resets revoke all sessions."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(auth_credentials)").fetchall()}
    if "token_version" not in columns:
        conn.execute("ALTER TABLE auth_credentials ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1")


def _legacy_e1rm(weight_kg: float, reps: int, rpe: float | None) -> float:
    """Mirrors ``agent.progression_engine.set_e1rm`` (importing it here would be circular).

    An unrated legacy row scores plain Epley — RPE 10 / RIR 0 — never a
    default effort (#111).
    """
    effective_rpe = rpe if rpe is not None else 10.0
    effective_reps = reps + (10.0 - min(max(effective_rpe, 6.0), 10.0))
    return weight_kg * (1.0 + (effective_reps / 30.0))


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Adds personal_records and backfills historical PRs from workout_sets.

    Backfill keeps first-achievement semantics: rows are walked chronologically and
    a record is only written when it strictly beats the running max, so ``achieved_at``
    points at the earliest set that reached the final value.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal_records (
            id TEXT PRIMARY KEY,
            exercise_id TEXT NOT NULL,
            record_type TEXT NOT NULL CHECK (record_type IN ('max_weight', 'max_e1rm')),
            reps INTEGER,
            value REAL NOT NULL,
            prev_value REAL,
            achieved_at TEXT NOT NULL,
            session_id TEXT,
            FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_exercise ON personal_records(exercise_id, record_type)")

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if not {"workout_sets", "workout_sessions"}.issubset(tables):
        return

    rows = conn.execute("""
        SELECT ws.exercise_id, ws.weight_kg, ws.reps, ws.rpe, ws.set_index, ws.logged_at,
               s.id AS session_id, s.started_at, s.session_date
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        WHERE ws.is_warmup = 0 AND ws.weight_kg > 0 AND ws.reps > 0
        ORDER BY COALESCE(s.started_at, s.session_date) ASC, ws.rowid ASC
    """).fetchall()

    best_weight: dict[tuple[str, int], float] = {}
    best_e1rm: dict[str, float] = {}
    payload: list[tuple] = []

    for exercise_id, weight, reps, rpe, _set_index, logged_at, session_id, started_at, session_date in rows:
        achieved_at = logged_at or started_at or session_date
        weight_key = (exercise_id, int(reps))
        if weight > best_weight.get(weight_key, 0.0):
            best_weight[weight_key] = weight
            payload.append(
                (str(uuid.uuid4()), exercise_id, "max_weight", int(reps), weight, None, achieved_at, session_id)
            )

        e1rm = _legacy_e1rm(float(weight), int(reps), rpe)
        if e1rm > best_e1rm.get(exercise_id, 0.0):
            best_e1rm[exercise_id] = e1rm
            payload.append(
                (str(uuid.uuid4()), exercise_id, "max_e1rm", int(reps), round(e1rm, 2), None, achieved_at, session_id)
            )

    if payload:
        conn.executemany(
            """
            INSERT INTO personal_records (
                id, exercise_id, record_type, reps, value, prev_value, achieved_at, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            payload,
        )
        logger.info(f"Backfilled {len(payload)} personal records from historical sets.")


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Adds Belghamdi-style program columns: warm-up blocks, cues and slot metadata.

    Ledgers created before the program tables existed (auth-only fixtures, very old
    profiles) are tolerated: each table is upgraded only when present.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    def _columns(table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    if "training_programs" in tables:
        program_cols = _columns("training_programs")
        if "instructions" not in program_cols:
            conn.execute("ALTER TABLE training_programs ADD COLUMN instructions TEXT DEFAULT ''")

    if "program_days" in tables:
        day_cols = _columns("program_days")
        if "warmup_json" not in day_cols:
            conn.execute("ALTER TABLE program_days ADD COLUMN warmup_json TEXT")
        if "cardio" not in day_cols:
            conn.execute("ALTER TABLE program_days ADD COLUMN cardio TEXT")

    if "program_exercises" in tables:
        exercise_cols = _columns("program_exercises")
        if "slot_key" not in exercise_cols:
            conn.execute("ALTER TABLE program_exercises ADD COLUMN slot_key TEXT")
        if "warmup_sets" not in exercise_cols:
            conn.execute("ALTER TABLE program_exercises ADD COLUMN warmup_sets INTEGER DEFAULT 0")


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Records coach provenance and a stable version on every training program.

    Existing rows are numbered sequentially by ``created_at`` (oldest first) and
    keep NULL provenance (self-service). The assignment is immutable afterwards:
    it identifies the exact program a player trained against (ADR 020/026).
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "training_programs" not in tables:
        return

    columns = {row[1] for row in conn.execute("PRAGMA table_info(training_programs)").fetchall()}
    if "version" not in columns:
        conn.execute("ALTER TABLE training_programs ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    if "published_by_coach_account_id" not in columns:
        conn.execute("ALTER TABLE training_programs ADD COLUMN published_by_coach_account_id TEXT")

    rows = conn.execute(
        "SELECT id FROM training_programs ORDER BY created_at ASC, rowid ASC"
    ).fetchall()
    for version, (program_id,) in enumerate(rows, start=1):
        conn.execute("UPDATE training_programs SET version = ? WHERE id = ?", (version, program_id))


def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Adds session_divergences: factual skipped/unplanned rows on workout history.

    Divergences are ledger history, never program state (ADR 018/028). The table
    cascades with its session so deleting a workout drops its divergences too.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_divergences (
            session_id TEXT NOT NULL,
            exercise_id TEXT NOT NULL,
            exercise_name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('skipped', 'unplanned')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (session_id, exercise_id, kind),
            FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
        )
    """)


def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Adds the player's expected training schedule and prospective pauses (ADR 029).

    Schedule versions are effective-dated ledger facts: a new expected weekday set
    is appended, never rewritten, so attendance for a past date resolves against
    the schedule effective then. Pauses are prospective, bounded ledger rows shown
    to the assigned coach. Both are separate from the program's weekly frequency.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_schedules (
            id TEXT PRIMARY KEY,
            trainee_id TEXT NOT NULL,
            weekdays TEXT NOT NULL,
            timezone TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_schedules_trainee"
        " ON training_schedules(trainee_id, effective_from)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_pauses (
            id TEXT PRIMARY KEY,
            trainee_id TEXT NOT NULL,
            starts_on TEXT NOT NULL,
            ends_on TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_pauses_trainee ON training_pauses(trainee_id)"
    )


def _migrate_v8_to_v9(conn: sqlite3.Connection) -> None:
    """Adds the offline-sync contract to committed workouts (ADR 020/033, #34).

    ``workout_sessions`` gains the client-generated session identity, the
    performed timezone, the captured program version, and capture/upload audit
    timestamps. ``session_commits`` stores the exact response returned for a
    client session id so a retry (or a lost response reconciled through the
    status lookup) never commits a second workout. The unique index is partial
    so already-committed legacy sessions keep a NULL client session id.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "workout_sessions" in tables:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workout_sessions)").fetchall()}
        if "client_session_id" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN client_session_id TEXT")
        if "performed_timezone" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN performed_timezone TEXT")
        if "program_version" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN program_version INTEGER")
        if "captured_at" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN captured_at TEXT")
        if "uploaded_at" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN uploaded_at TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workout_sessions_client"
            " ON workout_sessions(client_session_id) WHERE client_session_id IS NOT NULL"
        )

    # Independent of whether a workout_sessions table exists yet; a fresh
    # ``create_ledger_schema`` create is idempotent with this.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_commits (
            client_session_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            response_json TEXT NOT NULL,
            committed_at TEXT NOT NULL
        )
    """)


def _migrate_v9_to_v10(conn: sqlite3.Connection) -> None:
    """Records the active program version a workout synced against (ADR 020/034).

    A draft captured against an older program may be accepted later as history
    (#35). Storing the version that was active when it synced lets every reader
    show the version difference without replaying program history. Legacy and
    online-only sessions keep NULL.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "workout_sessions" not in tables:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(workout_sessions)").fetchall()}
    if "active_program_version_at_sync" not in columns:
        conn.execute("ALTER TABLE workout_sessions ADD COLUMN active_program_version_at_sync INTEGER")


def _migrate_v10_to_v11(conn: sqlite3.Connection) -> None:
    """Adds performed-date corrections to committed workouts (ADR 020/035).

    ``workout_sessions`` gains ``edited_at`` so a correction is auditable while
    the original capture/upload timestamps stay untouched. Every correction is
    an immutable ``performed_date_corrections`` row (previous date, corrected
    date, and time); the rows cascade with their session so deleting a workout
    drops its correction history too.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "workout_sessions" in tables:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workout_sessions)").fetchall()}
        if "edited_at" not in columns:
            conn.execute("ALTER TABLE workout_sessions ADD COLUMN edited_at TEXT")

    for statement in PERFORMED_DATE_CORRECTIONS_DDL:
        conn.execute(statement)


def _migrate_v11_to_v12(conn: sqlite3.Connection) -> None:
    """Adds structured, resumable onboarding intake tables (ADR 021).

    ``intake_answers`` keeps one named decision per row (with per-field
    ``updated_at`` and a legacy-prefill marker); ``intake_state`` is the single
    status row (in_progress/confirmed, disclosure acknowledgement, and the
    stored confirmation result). Existing accounts keep their profile and
    onboarding state untouched: the intake read synthesizes their current values.
    """
    for statement in INTAKE_DDL:
        conn.execute(statement)


def _migrate_v12_to_v13(conn: sqlite3.Connection) -> None:
    """Adds separate history storage for Warm-up movements (#218)."""
    for statement in SESSION_WARMUP_SETS_DDL:
        conn.execute(statement)


def _migrate_v13_to_v14(conn: sqlite3.Connection) -> None:
    """Adds separate history storage for Cardio (#219)."""
    for statement in SESSION_CARDIO_DDL:
        conn.execute(statement)


def _migrate_v14_to_v15(conn: sqlite3.Connection) -> None:
    """Adds one durable, computed review for each reached Checkpoint (#221)."""
    for statement in CHECKPOINT_REVIEWS_DDL:
        conn.execute(statement)


def _migrate_v15_to_v16(conn: sqlite3.Connection) -> None:
    """Adds retry throttling for lazy Checkpoint review text generation (#222)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(checkpoint_reviews)").fetchall()}
    if "last_attempt_at" not in columns:
        conn.execute("ALTER TABLE checkpoint_reviews ADD COLUMN last_attempt_at TEXT")


def _ledger_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _user_profile_has_equipment_access(conn: sqlite3.Connection) -> bool:
    if not _ledger_table_exists(conn, "user_profile"):
        return False
    return any(
        column[1] == "equipment_access"
        for column in conn.execute("PRAGMA table_info(user_profile)")
    )


def _migrate_profile_equipment_access(conn: sqlite3.Connection) -> None:
    if not _user_profile_has_equipment_access(conn):
        return
    profile_rows = conn.execute("SELECT id, equipment_access FROM user_profile").fetchall()
    conn.executemany(
        "UPDATE user_profile SET equipment_access = ? WHERE id = ?",
        [(map_equipment_access(access_text), profile_id) for profile_id, access_text in profile_rows],
    )


def _migrate_intake_equipment_access(conn: sqlite3.Connection) -> None:
    if not _ledger_table_exists(conn, "intake_answers"):
        return
    for (encoded_answer,) in conn.execute(
        "SELECT value FROM intake_answers WHERE field = 'equipment_access'"
    ).fetchall():
        try:
            intake_answer = json.loads(encoded_answer)
        except (TypeError, json.JSONDecodeError):
            intake_answer = encoded_answer
        conn.execute(
            "UPDATE intake_answers SET value = ? WHERE field = 'equipment_access'",
            (json.dumps(map_equipment_access(intake_answer)),),
        )


def _migrate_v16_to_v17(conn: sqlite3.Connection) -> None:
    """Apply #228 so old profiles and new writes share one Equipment access contract."""
    _migrate_profile_equipment_access(conn)
    _migrate_intake_equipment_access(conn)
    if _user_profile_has_equipment_access(conn):
        for statement in EQUIPMENT_ACCESS_DDL:
            conn.execute(statement)


def get_ledger_schema_version(conn: sqlite3.Connection) -> int:
    """Reads the current user_version PRAGMA from the SQLite connection."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def set_ledger_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Sets the user_version PRAGMA integer."""
    conn.execute(f"PRAGMA user_version = {int(version)};")


def create_atomic_backup(
    conn: sqlite3.Connection,
    backup_path: Path,
) -> Path:
    """Creates a consistent, online point-in-time snapshot using the SQLite backup API.

    Safely drains WAL pages into the target file without taking the database offline.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    dest_conn = sqlite3.connect(str(backup_path))
    try:
        conn.backup(dest_conn)
    finally:
        dest_conn.close()

    logger.info(f"Atomic snapshot created: {backup_path.name}")
    return backup_path


def restore_atomic_backup(
    backup_path: Path,
    target_conn: sqlite3.Connection,
) -> None:
    """Restores database state from a backup snapshot into an active SQLite connection."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup snapshot not found: {backup_path}")

    src_conn = sqlite3.connect(str(backup_path))
    try:
        src_conn.backup(target_conn)
    finally:
        src_conn.close()

    logger.warning(f"Database successfully restored from snapshot: {backup_path.name}")


def prune_ledger_backups(ledger_backup_dir: Path, max_rolling: int = 3) -> None:
    """Enforces the 3+1 retention policy:

    - Keeps all immutable pre-migration snapshots (*_pre_v*).
    - Retains only the most recent `max_rolling` (default: 3) automated snapshots.
    """
    if not ledger_backup_dir.is_dir():
        return

    rolling_snapshots = []
    for f in ledger_backup_dir.glob("*.db"):
        if "_pre_v" not in f.name:
            rolling_snapshots.append(f)

    # Sort ascending by modification time (oldest first)
    rolling_snapshots.sort(key=lambda p: p.stat().st_mtime)

    # Prune oldest if exceeding retention
    while len(rolling_snapshots) > max_rolling:
        oldest = rolling_snapshots.pop(0)
        try:
            oldest.unlink()
            logger.info(f"Pruned expired rolling snapshot: {oldest.name}")
        except OSError as e:
            logger.warning(f"Failed to prune snapshot {oldest}: {e}")


# ---------------------------------------------------------------------------
# Migration Registry & Upgrade Handlers
# ---------------------------------------------------------------------------

MigrationCallable = Callable[[sqlite3.Connection], None]

# Migration map: from_version -> migration function to reach (from_version + 1)
# Example: 1: migrate_v1_to_v2
MIGRATION_REGISTRY: dict[int, MigrationCallable] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
    9: _migrate_v9_to_v10,
    10: _migrate_v10_to_v11,
    11: _migrate_v11_to_v12,
    12: _migrate_v12_to_v13,
    13: _migrate_v13_to_v14,
    14: _migrate_v14_to_v15,
    15: _migrate_v15_to_v16,
    16: _migrate_v16_to_v17,
}


def apply_lazy_migrations(
    conn: sqlite3.Connection,
    username: str,
    ledgers_dir: Path,
    backups_dir: Path,
    target_version: int = CURRENT_LEDGER_SCHEMA_VERSION,
) -> None:
    """Evaluates and executes lazy migrations on the mounted ledger.

    Execution Flow:
    1. Check PRAGMA user_version.
    2. If version == 0 and tables exist (pre-migration legacy DB), stamp to v1.
    3. If version == 0 and empty, the caller initializes baseline schema and sets v1.
    4. If version < target_version, snapshot the DB, run sequential migrations in a
       transaction, and update user_version.
    5. If an error occurs, rollback and restore snapshot.
    """
    current_version = get_ledger_schema_version(conn)

    # Handle legacy databases initialized prior to PRAGMA user_version tracking
    if current_version == 0:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile';")
        if cursor.fetchone():
            # Existing legacy v1 database detected
            set_ledger_schema_version(conn, 1)
            conn.commit()
            current_version = 1
        else:
            # Fresh database: caller will provision baseline v1 schema
            return

    if current_version == target_version:
        return

    if current_version > target_version:
        raise RuntimeError(
            f"User ledger '{username}' has schema version {current_version}, which is "
            f"newer than the engine's target version {target_version}. Please update Mayos."
        )

    # Migration required: current_version < target_version
    ledger_backup_dir = backups_dir / username
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    snapshot_path = ledger_backup_dir / f"{username}_pre_v{current_version}_to_v{target_version}_{timestamp}.db"

    create_atomic_backup(conn, snapshot_path)

    try:
        conn.execute("BEGIN IMMEDIATE;")
        step_version = current_version
        while step_version < target_version:
            if step_version not in MIGRATION_REGISTRY:
                raise NotImplementedError(
                    f"Missing migration step from schema version {step_version} to {step_version + 1}."
                )
            logger.info(f"Applying migration v{step_version} -> v{step_version + 1} for '{username}'...")
            MIGRATION_REGISTRY[step_version](conn)
            step_version += 1

        set_ledger_schema_version(conn, target_version)
        conn.commit()
        logger.info(f"Successfully migrated '{username}' ledger to schema v{target_version}.")
    except Exception as exc:
        conn.rollback()
        logger.error(f"Migration failed for '{username}': {exc}. Triggering atomic rollback...")
        restore_atomic_backup(snapshot_path, conn)
        raise RuntimeError(f"Database migration aborted and reverted for '{username}': {exc}") from exc
