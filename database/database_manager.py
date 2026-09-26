import json
import os
import re
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import sqlite_vec

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.storage import configured_data_root, resolve_data_root, validate_data_root

#: Catalog, ledgers, and migration/backup work area all hang off one data root.
#: Local development keeps ``<repo>/db``; containers set ``MAYOS_DATA_DIR`` to
#: the mounted volume (``/data``) so every path below is durable from boot.
_DATA_ROOT = resolve_data_root()
DEFAULT_CATALOG_PATH = _DATA_ROOT / "catalog.db"
DEFAULT_USERS_DIR = _DATA_ROOT / "users"
DEFAULT_BACKUPS_DIR = _DATA_ROOT / "backups"
DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
    WarmupExerciseSchema,
)
from database.migration_manager import (
    CURRENT_USER_SCHEMA_VERSION,
    PERFORMED_DATE_CORRECTIONS_DDL,
    apply_lazy_migrations,
    create_atomic_backup,
    get_user_schema_version,
    prune_user_backups,
    set_user_schema_version,
)
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def _normalize_exercise_name(name: str) -> str:
    """Lowercase and collapse punctuation so "push up" ≡ "push-up" and "two arm" ≡ "two-arm"."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


class DatabaseManager:
    _instance = None
    EMBEDDING_DIM = 384
    _lock: threading.Lock = threading.Lock()
    _local: threading.local = threading.local()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        catalog_path=None,
        users_dir=None,
        backups_dir=None,
        active_user: str | None = None,
    ):
        if getattr(self, "_initialized", False):
            if active_user is not None:
                sanitized = self._sanitize_username(active_user)
                if sanitized and sanitized != self.active_user:
                    self.switch_user(sanitized)
            return

        with self._lock:
            if getattr(self, "_initialized", False):
                return

            # Resolve the data root at construction time so MAYOS_DATA_DIR is
            # honored even when the env is set after this module was imported.
            # When a data root is configured, validate it *before* any mkdir or
            # SQLite open so a missing/unwritable volume fails closed — including
            # when a route lazily constructs the manager after startup failed.
            # Local no-env runs and explicit-path construction (tests, operator
            # overrides) keep working unchanged.
            if configured_data_root() is not None:
                root = validate_data_root()
            else:
                root = resolve_data_root()
            self.catalog_path = Path(catalog_path) if catalog_path is not None else root / "catalog.db"
            self.users_dir = Path(users_dir) if users_dir is not None else root / "users"
            self.backups_dir = Path(backups_dir) if backups_dir is not None else root / "backups"
            self._default_user = self._sanitize_username(active_user) if active_user else "default"
            # A re-entrant lock lets a ``catalog_transaction`` hold the lock while
            # the catalog methods it calls re-acquire it (their own writes only
            # commit when no transaction is active).
            self._catalog_lock = threading.RLock()

            os.makedirs(self.catalog_path.parent, exist_ok=True)
            os.makedirs(self.users_dir, exist_ok=True)
            os.makedirs(self.backups_dir, exist_ok=True)

            self.catalog_conn = sqlite3.connect(self.catalog_path, check_same_thread=False)
            self.catalog_conn.execute("PRAGMA foreign_keys = ON;")
            self.catalog_conn.execute("PRAGMA journal_mode = WAL;")
            self.catalog_conn.execute("PRAGMA busy_timeout = 5000;")
            self.catalog_conn.execute("PRAGMA synchronous = NORMAL;")
            self.catalog_conn.enable_load_extension(True)
            sqlite_vec.load(self.catalog_conn)
            self.catalog_conn.enable_load_extension(False)

            # Recovery identity tables must exist for the login/forgot gates.
            # Called outside any held lock: ensure_account_schema takes _catalog_lock.
            self.ensure_account_schema()

            self.switch_user(self._default_user)

            self._initialized = True
            logger.info(f"DatabaseManager initialized with user ledger ({self.active_user}).")

    @property
    def active_user(self) -> str:
        return getattr(self._local, "active_user", getattr(self, "_default_user", "default"))

    @active_user.setter
    def active_user(self, val: str):
        self._local.active_user = val

    @property
    def user_conn(self) -> sqlite3.Connection | None:
        return getattr(self._local, "user_conn", None)

    @user_conn.setter
    def user_conn(self, val: sqlite3.Connection | None):
        self._local.user_conn = val

    @property
    def conn(self) -> sqlite3.Connection:
        c = self.user_conn
        if c is None:
            self.switch_user(self.active_user)
            c = self.user_conn
        if c is None:
            raise RuntimeError(f"No active database connection mounted for user '{self.active_user}'.")
        return c

    @staticmethod
    def _sanitize_username(username: str) -> str:
        clean = re.sub(r"[^\w\-]", "", str(username).strip().lower())
        return clean or "default"

    def switch_user(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        if not sanitized:
            return False

        current_conn = self.user_conn
        if current_conn is not None and self.active_user == sanitized:
            return True

        if current_conn is not None:
            try:
                current_conn.commit()
                current_conn.close()
            except Exception as e:
                logger.warning(f"Error closing active connection for {self.active_user}: {e}")
            self.user_conn = None

        self.active_user = sanitized
        user_db_path = self.users_dir / f"{sanitized}.db"

        new_conn = sqlite3.connect(user_db_path, check_same_thread=False)
        new_conn.row_factory = sqlite3.Row
        new_conn.execute("PRAGMA foreign_keys = ON;")
        new_conn.execute("PRAGMA journal_mode = WAL;")
        new_conn.execute("PRAGMA busy_timeout = 5000;")
        new_conn.execute("PRAGMA synchronous = NORMAL;")

        escaped_path = str(self.catalog_path.resolve()).replace("'", "''")
        new_conn.execute(f"ATTACH DATABASE '{escaped_path}' AS catalog;")
        new_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercises AS SELECT * FROM catalog.exercises;")
        new_conn.execute(
            "CREATE TEMP VIEW IF NOT EXISTS exercise_secondary_muscles AS SELECT * FROM catalog.exercise_secondary_muscles;"
        )

        self.user_conn = new_conn

        # Lazily migrate the mounted ledger (fresh DBs return early; legacy
        # v0 ledgers are stamped v1 then migrated step-by-step with snapshot).
        apply_lazy_migrations(new_conn, sanitized, self.users_dir, self.backups_dir)

        self.create_user_schema()
        prune_user_backups(self.backups_dir / sanitized, max_rolling=3)
        return True

    def unmount_user(self) -> None:
        """Closes and clears this thread's mounted ledger connection.

        Background work (the alert sweep) shares ``asyncio``'s worker threads
        with request handlers; without this, a player's ledger connection would
        stay bound to that thread after the work finishes. Resets the thread to
        the default identity so the next ``bind_user``/``switch_user`` mounts
        cleanly.
        """
        current_conn = self.user_conn
        if current_conn is not None:
            try:
                current_conn.commit()
                current_conn.close()
            except Exception as e:
                logger.warning(f"Error closing active connection for {self.active_user}: {e}")
        self.user_conn = None
        self.active_user = getattr(self, "_default_user", "default")


    @contextmanager
    def catalog_locked(self) -> Iterator[sqlite3.Connection]:
        """Yields the shared catalog connection under the catalog lock.

        All direct catalog reads must go through this helper; the raw
        ``catalog_conn`` cursor is not thread-safe on its own.
        """
        with self._catalog_lock:
            yield self.catalog_conn

    def user_exists(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        return (self.users_dir / f"{sanitized}.db").is_file() if sanitized else False

    def get_connection(self) -> sqlite3.Connection:
        return self.conn

    def create_catalog_schema(self) -> None:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.executescript(f"""
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS exercises (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    body_part TEXT NOT NULL,
                    target_muscle TEXT NOT NULL,
                    equipment TEXT NOT NULL,
                    image_path TEXT,
                    gif_path TEXT,
                    instructions TEXT
                );
                CREATE TABLE IF NOT EXISTS exercise_secondary_muscles (
                    exercise_id TEXT NOT NULL,
                    muscle TEXT NOT NULL,
                    FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_exercises USING vec0(
                    exercise_id INTEGER PRIMARY KEY,
                    embedding float[{self.EMBEDDING_DIM}] distance_metric=cosine
                );
                CREATE INDEX IF NOT EXISTS idx_secondary_muscles_ex ON exercise_secondary_muscles(exercise_id);
            """)
            self.catalog_conn.commit()
        # Outside the lock block: ensure_account_schema acquires _catalog_lock itself.
        self.ensure_account_schema()

    def create_user_schema(self) -> None:
        cursor = self.conn.cursor()
        cursor.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                gender TEXT DEFAULT 'male',
                proportions TEXT NOT NULL,
                age INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                height_cm REAL NOT NULL,
                rep_preference TEXT DEFAULT 'balanced',
                current_goal TEXT NOT NULL,
                long_term_goal TEXT NOT NULL,
                weekly_frequency INTEGER NOT NULL,
                training_age_years REAL NOT NULL,
                equipment_access TEXT NOT NULL,
                injuries_or_limitations TEXT DEFAULT 'None',
                stress_and_sleep TEXT NOT NULL,
                coach_tone TEXT DEFAULT 'Direct, grounded, and pragmatic',
                custom_instructions TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_credentials (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                password_hash TEXT NOT NULL,
                token_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_programs (
                id TEXT PRIMARY KEY,
                program_name TEXT NOT NULL,
                name TEXT NOT NULL,
                split_type TEXT NOT NULL,
                weekly_frequency INTEGER NOT NULL,
                instructions TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                published_by_coach_account_id TEXT
            );
            CREATE TABLE IF NOT EXISTS program_days (
                id TEXT PRIMARY KEY,
                program_id TEXT NOT NULL,
                day_name TEXT NOT NULL,
                day_order INTEGER NOT NULL,
                warmup_json TEXT,
                cardio TEXT,
                FOREIGN KEY(program_id) REFERENCES training_programs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS program_exercises (
                id TEXT PRIMARY KEY,
                day_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                order_in_day INTEGER NOT NULL,
                slot_key TEXT,
                warmup_sets INTEGER DEFAULT 0,
                target_sets INTEGER NOT NULL,
                target_reps_min INTEGER NOT NULL,
                target_reps_max INTEGER NOT NULL,
                target_rpe REAL,
                rest_seconds INTEGER DEFAULT 120,
                notes TEXT,
                FOREIGN KEY(day_id) REFERENCES program_days(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_program_days_prog ON program_days(program_id);
            CREATE INDEX IF NOT EXISTS idx_program_ex_day ON program_exercises(day_id);

            CREATE TABLE IF NOT EXISTS workout_sessions (
                id TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                split_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                session_notes TEXT,
                readiness_score INTEGER CHECK(readiness_score BETWEEN 1 AND 5),
                coach_debrief TEXT,
                client_session_id TEXT,
                performed_timezone TEXT,
                program_version INTEGER,
                active_program_version_at_sync INTEGER,
                captured_at TEXT,
                uploaded_at TEXT,
                edited_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workout_sessions_client
                ON workout_sessions(client_session_id) WHERE client_session_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS session_commits (
                client_session_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                response_json TEXT NOT NULL,
                committed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workout_sets (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                set_index INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                reps INTEGER NOT NULL,
                rpe REAL CHECK(rpe BETWEEN 1 AND 10),
                is_warmup INTEGER DEFAULT 0,
                logged_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS session_divergences (
                session_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('skipped', 'unplanned')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, exercise_id, kind),
                FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
            );
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
            );
            CREATE INDEX IF NOT EXISTS idx_pr_exercise ON personal_records(exercise_id, record_type);

            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_memory (
                key TEXT PRIMARY KEY CHECK (key = 'preferred_name'),
                value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 60 AND length(trim(value)) > 0)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_history(created_at);
            CREATE INDEX IF NOT EXISTS idx_sets_session ON workout_sets(session_id);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(session_date);

            CREATE TABLE IF NOT EXISTS training_schedules (
                id TEXT PRIMARY KEY,
                trainee_id TEXT NOT NULL,
                weekdays TEXT NOT NULL,
                timezone TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_training_schedules_trainee
                ON training_schedules(trainee_id, effective_from);
            CREATE TABLE IF NOT EXISTS training_pauses (
                id TEXT PRIMARY KEY,
                trainee_id TEXT NOT NULL,
                starts_on TEXT NOT NULL,
                ends_on TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_training_pauses_trainee ON training_pauses(trainee_id);

            CREATE TABLE IF NOT EXISTS engine_telemetry (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                route_intent TEXT NOT NULL,
                fast_path_latency_ms REAL,
                ttft_ms REAL,
                generation_ms REAL,
                token_count INTEGER,
                tps REAL,
                memory_rss_mb REAL
            );
            CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON engine_telemetry(timestamp);

            CREATE TABLE IF NOT EXISTS onboarding_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                intake_step INTEGER NOT NULL,
                is_complete INTEGER NOT NULL DEFAULT 0,
                profile_data TEXT,
                messages TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL,
                revoked_at TEXT NOT NULL
            );
        """ + "\n".join(f"{statement};" for statement in PERFORMED_DATE_CORRECTIONS_DDL))
        if get_user_schema_version(self.conn) < CURRENT_USER_SCHEMA_VERSION:
            set_user_schema_version(self.conn, CURRENT_USER_SCHEMA_VERSION)
        self.conn.commit()

    def backup_active_user(self) -> Path:
        """Creates an on-demand rolling snapshot of the active user ledger."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        user_backup_dir = self.backups_dir / self.active_user
        backup_path = user_backup_dir / f"{self.active_user}_auto_{timestamp}.db"
        create_atomic_backup(self.conn, backup_path)
        prune_user_backups(user_backup_dir, max_rolling=3)
        return backup_path

    def create_schema(self) -> None:
        self.create_catalog_schema()
        self.create_user_schema()

    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH) -> None:
        self.create_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM exercises")
            if cursor.fetchone()[0] > 0:
                logger.info("Database already populated. Skipping CSV seed.")
                return

            logger.info("Seeding database from CSV...")
            try:
                df = pd.read_csv(csv_path)
            except FileNotFoundError:
                logger.error(f"Error: {csv_path} not found.")
                return

            core_df = df[
                ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
            ].copy()
            core_df.rename(columns={"bodyPart": "body_part", "target": "target_muscle"}, inplace=True)
            core_df["name"] = (
                core_df["name"]
                .astype(str)
                .str.replace(r"^lever\s+", "machine ", regex=True, flags=re.IGNORECASE)
                .str.replace(r"\s+v\.\s*\d+", "", regex=True, flags=re.IGNORECASE)
                .str.strip()
            )
            core_df.to_sql("exercises", self.catalog_conn, if_exists="append", index=False)

            muscle_cols = [c for c in df.columns if c.startswith("secondaryMuscles/")]

            if muscle_cols:
                muscles_df = (
                    df.melt(id_vars=["id"], value_vars=muscle_cols, value_name="muscle")
                    .dropna(subset=["muscle"])
                )
                # Clean whitespace and case
                muscles_df["muscle"] = muscles_df["muscle"].astype(str).str.strip().str.lower()
                
                # Filter out empty strings and stringified nulls
                muscles_df = muscles_df[
                    ~muscles_df["muscle"].isin(["", "nan", "none", "null"])
                ]
                
                # Rename and drop duplicate pairs
                muscles_df = (
                    muscles_df[["id", "muscle"]]
                    .rename(columns={"id": "exercise_id"})
                    .drop_duplicates()
                )

                if not muscles_df.empty:
                    muscles_df.to_sql(
                        "exercise_secondary_muscles",
                        self.catalog_conn,
                        if_exists="append",
                        index=False
                    )
                    self.catalog_conn.commit()

    EXCLUDED_BIOMECHANICAL_PATTERNS = ("behind neck", "behind the neck", "upright row")

    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            serialized_vector = sqlite_vec.serialize_float32(query_vector)
            query = """
                WITH knn_matches AS (
                    SELECT exercise_id, distance
                    FROM vec_exercises
                    WHERE embedding MATCH ? AND k = ?
                )
                SELECT e.id, e.name, e.body_part, e.target_muscle, e.equipment, e.instructions, m.distance
                FROM knn_matches m
                JOIN exercises e ON CAST(e.id AS INTEGER) = m.exercise_id
                ORDER BY m.distance ASC;
            """
            cursor.execute(query, (serialized_vector, limit * 3))
            columns = ["id", "name", "body_part", "target_muscle", "equipment", "instructions", "distance"]
            candidates = []
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                if any(p in record["name"].lower() for p in self.EXCLUDED_BIOMECHANICAL_PATTERNS):
                    continue
                candidates.append(record)
                if len(candidates) >= limit:
                    break
            return candidates

    def get_user_profile(self, user_id: int = 1) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_assistant_memory(self) -> dict[str, str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM assistant_memory WHERE key = ?", ("preferred_name",))
        return dict(cursor.fetchall())

    def save_onboarding_state(self, state: dict[str, Any]) -> None:
        """Persists onboarding intake progress in the bound user's ledger (survives restarts)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO onboarding_state (id, intake_step, is_complete, profile_data, messages, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                intake_step = excluded.intake_step, is_complete = excluded.is_complete,
                profile_data = excluded.profile_data, messages = excluded.messages,
                updated_at = excluded.updated_at
            """,
            (
                int(state.get("intake_step", 1)),
                1 if state.get("is_complete") else 0,
                json.dumps(state.get("profile_data")),
                json.dumps(state.get("messages", [])),
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def load_onboarding_state(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT intake_step, is_complete, profile_data, messages FROM onboarding_state WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "intake_step": row["intake_step"],
            "is_complete": bool(row["is_complete"]),
            "profile_data": json.loads(row["profile_data"]) if row["profile_data"] else None,
            "messages": json.loads(row["messages"]) if row["messages"] else [],
        }

    def clear_onboarding_state(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM onboarding_state WHERE id = 1")
        self.conn.commit()

    def revoke_token(self, jti: str, expires_at: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO revoked_tokens (jti, expires_at, revoked_at) VALUES (?, ?, ?)
            ON CONFLICT(jti) DO NOTHING
            """,
            (jti, expires_at, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def is_token_revoked(self, jti: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,))
        return cursor.fetchone() is not None

    def prune_revoked_tokens(self, now_iso: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now_iso,))
        self.conn.commit()
        return cursor.rowcount

    def set_assistant_memory(self, key: str, value: str) -> None:
        if key != "preferred_name":
            raise ValueError("Unsupported assistant memory key")
        if not isinstance(value, str) or not 1 <= len(value) <= 60 or not value.strip() or not value.isprintable():
            raise ValueError("Preferred name must be a nonempty printable string of at most 60 characters")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO assistant_memory (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def upsert_user_profile(self, profile_data: dict, user_id: int = 1) -> None:
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.cursor()
        params = {
            "id": int(profile_data.get("id", user_id)),
            "gender": str(profile_data.get("gender", "male")).lower(),
            "proportions": str(profile_data.get("proportions", "balanced")),
            "age": int(profile_data.get("age", 25)),
            "weight_kg": float(profile_data.get("weight_kg", 75.0)),
            "height_cm": float(profile_data.get("height_cm", 175.0)),
            "rep_preference": str(profile_data.get("rep_preference", "balanced")),
            "current_goal": str(profile_data.get("current_goal", "hypertrophy")),
            "long_term_goal": str(profile_data.get("long_term_goal", "progressive overload")),
            "weekly_frequency": min(max(int(profile_data.get("weekly_frequency", 4)), 1), 5),
            "training_age_years": float(profile_data.get("training_age_years", 1.0)),
            "equipment_access": str(profile_data.get("equipment_access", "commercial gym")),
            "injuries_or_limitations": str(profile_data.get("injuries_or_limitations", "None")),
            "stress_and_sleep": str(profile_data.get("stress_and_sleep", "normal")),
            "created_at": now,
            "updated_at": now,
        }
        cursor.execute(
            """
            INSERT INTO user_profile (
                id, gender, proportions, age, weight_kg, height_cm, rep_preference,
                current_goal, long_term_goal, weekly_frequency, training_age_years,
                equipment_access, injuries_or_limitations, stress_and_sleep, created_at, updated_at
            ) VALUES (
                :id, :gender, :proportions, :age, :weight_kg, :height_cm, :rep_preference,
                :current_goal, :long_term_goal, :weekly_frequency, :training_age_years,
                :equipment_access, :injuries_or_limitations, :stress_and_sleep, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                gender = excluded.gender, proportions = excluded.proportions, age = excluded.age,
                weight_kg = excluded.weight_kg, height_cm = excluded.height_cm,
                rep_preference = excluded.rep_preference, current_goal = excluded.current_goal,
                long_term_goal = excluded.long_term_goal, weekly_frequency = excluded.weekly_frequency,
                training_age_years = excluded.training_age_years, equipment_access = excluded.equipment_access,
                injuries_or_limitations = excluded.injuries_or_limitations, stress_and_sleep = excluded.stress_and_sleep,
                updated_at = excluded.updated_at
        """,
            params,
        )
        self.conn.commit()

    def clear_user_profile(self, user_id: int = 1) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM user_profile WHERE id = ?", (user_id,))
        self.conn.commit()

    def get_password_hash(self) -> str | None:
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT password_hash FROM auth_credentials WHERE id = 1")
        except sqlite3.OperationalError:
            return None
        row = cursor.fetchone()
        return row["password_hash"] if row and row["password_hash"] else None

    def set_password_hash(self, password_hash: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO auth_credentials (id, password_hash, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at
            """,
            (password_hash, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get_token_version(self) -> int:
        """Session epoch for the bound ledger. Bumped on every password change/reset."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT token_version FROM auth_credentials WHERE id = 1")
        except sqlite3.OperationalError:
            return 1
        row = cursor.fetchone()
        try:
            return max(1, int((row["token_version"] if row else 1) or 1))
        except (TypeError, ValueError, KeyError, IndexError):
            return 1

    def bump_token_version(self) -> int:
        """Invalidates all previously issued JWTs for the bound ledger. Returns new version."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT token_version FROM auth_credentials WHERE id = 1")
            row = cursor.fetchone()
            current = max(1, int((row["token_version"] if row else 1) or 1))
        except sqlite3.OperationalError:
            # Pre-v3 ledger mounted without migration (defensive): add the column.
            cursor.execute("ALTER TABLE auth_credentials ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1")
            current = 1
        except (TypeError, ValueError, KeyError, IndexError):
            current = 1
        new_version = current + 1
        # NOTE: the conflict clause only touches token_version/updated_at, so an
        # existing password_hash is preserved. A fresh '' placeholder row (no
        # password ever set) stays falsy and reads back as "no password".
        cursor.execute(
            """
            INSERT INTO auth_credentials (id, password_hash, token_version, updated_at)
            VALUES (1, '', ?, ?)
            ON CONFLICT(id) DO UPDATE SET token_version = excluded.token_version, updated_at = excluded.updated_at
            """,
            (new_version, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
        return new_version

    # ------------------------------------------------------------------
    # Catalog-side account data: recovery emails + single-use reset tokens.
    # Lives in the shared catalog (not per-user ledgers) because the
    # logged-out forgot-password flow cannot know which ledger to open.
    # ------------------------------------------------------------------

    def ensure_account_schema(self) -> None:
        # Provisioned once at boot; guarded so the auth hot path never re-runs DDL.
        if getattr(self, "_account_schema_ready", False):
            return
        with self._catalog_lock:
            if getattr(self, "_account_schema_ready", False):
                return
            self._migrate_coach_alerts_shape()
            self.catalog_conn.executescript("""
                CREATE TABLE IF NOT EXISTS trainee_emails (
                    trainee_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token_hash TEXT PRIMARY KEY,
                    trainee_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reset_tokens_trainee ON password_reset_tokens(trainee_id);

                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    ledger_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    is_player INTEGER NOT NULL DEFAULT 1,
                    is_coach INTEGER NOT NULL DEFAULT 0,
                    session_epoch INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                -- Partial unique index: a username is unique among live accounts, so a
                -- deleted username can later be registered under a new immutable id.
                CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_active_username
                    ON accounts(username) WHERE deleted_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_accounts_ledger ON accounts(ledger_id);

                -- Server-owned Lifter/Coach plan state, keyed by the immutable account
                -- id and one row per capability. A missing row means the ongoing Free
                -- plan; eligibility is decided from the account's live capabilities,
                -- never from client-supplied role or username (issue #56).
                CREATE TABLE IF NOT EXISTS account_plans (
                    account_id TEXT NOT NULL,
                    capability TEXT NOT NULL CHECK (capability IN ('lifter', 'coach')),
                    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro')),
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, capability)
                );

                -- Owner-issued, account-bound coach invitations (ADR 013). Only the
                -- SHA-256 of the token is stored; the raw code is shown once to the
                -- operator. Redemption is a single atomic catalog transaction.
                CREATE TABLE IF NOT EXISTS coach_invites (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_coach_invites_account ON coach_invites(account_id);

                -- Coach-authored profile, keyed by the immutable account id and kept
                -- catalog-side so coach reads never open a player ledger (ADR-007).
                CREATE TABLE IF NOT EXISTS coach_profiles (
                    account_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    bio TEXT NOT NULL DEFAULT '',
                    specialization TEXT NOT NULL DEFAULT '',
                    capacity INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Coach-issued player assignment invites (ADR 014, ticket #24). The code
                -- is a bearer code, not recipient bound: only the SHA-256 hash is stored,
                -- it is single-use, expiring, and bounded by roster capacity. Redemption
                -- claims the code and creates the assignment in one catalog transaction.
                CREATE TABLE IF NOT EXISTS assignment_invites (
                    token_hash TEXT PRIMARY KEY,
                    coach_account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    redeemed_by_account_id TEXT,
                    assignment_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_invites_coach ON assignment_invites(coach_account_id);

                -- Mutually consented coaching assignment. Catalog-side so access checks
                -- and list views never open a player ledger. The partial unique index
                -- enforces at most one active assignment per player (context glossary).
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    ended_by TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_active_player
                    ON assignments(player_account_id) WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_assignments_coach ON assignments(coach_account_id);
                CREATE INDEX IF NOT EXISTS idx_assignments_player ON assignments(player_account_id);

                -- In-app notices for assignment events (redemption today; coach-facing).
                CREATE TABLE IF NOT EXISTS assignment_notices (
                    notice_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    assignment_id TEXT,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_notices_account ON assignment_notices(account_id);

                -- Player-requested program changes (ADR 018/027, ticket #28). Catalog-side,
                -- keyed by assignment. A request pins the exact program version/day/slot it
                -- targets and never mutates the program; resolution is an atomic claim that
                -- only flips a pending row, so double-apply and racing cancels fail cleanly.
                CREATE TABLE IF NOT EXISTS program_requests (
                    request_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('exercise_substitution', 'split_change')),
                    program_version INTEGER NOT NULL,
                    day_name TEXT,
                    exercise_id TEXT,
                    replacement_exercise_id TEXT,
                    desired_weekly_frequency INTEGER,
                    desired_split_preference TEXT,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'applied', 'declined', 'cancelled')),
                    response TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_program_requests_assignment ON program_requests(assignment_id);
                CREATE INDEX IF NOT EXISTS idx_program_requests_player ON program_requests(player_account_id);

                -- Catalog-side per-assignment attendance summary, updated by evaluation so a
                -- roster read never opens the player's ledger (ADR 025/030). The cached
                -- ``timezone`` is the player's local timezone as of the last evaluation;
                -- absence falls back to UTC (ADR 031).
                CREATE TABLE IF NOT EXISTS roster_attendance (
                    assignment_id TEXT PRIMARY KEY,
                    current_missed_streak INTEGER NOT NULL DEFAULT 0,
                    last_evaluated_at TEXT,
                    timezone TEXT
                );

                -- Coach-recorded check-ins (ADR 031, ticket #32). Catalog-side immutable
                -- facts: the coach records the date, contact channel, and an optional note.
                -- The row survives unassignment so the player keeps their history.
                CREATE TABLE IF NOT EXISTS check_ins (
                    check_in_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    coach_account_id TEXT NOT NULL,
                    player_account_id TEXT NOT NULL,
                    checked_in_on TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_check_ins_assignment ON check_ins(assignment_id);
                CREATE INDEX IF NOT EXISTS idx_check_ins_player ON check_ins(player_account_id);

                -- Catalog-side episode state for the progression alerts (ADR 032,
                -- ticket #33). ``subject`` is '' for the systemic deload signal and
                -- the exercise id for performance regression, so a commit that does
                -- not include an exercise leaves its episode untouched.
                CREATE TABLE IF NOT EXISTS alert_signal_state (
                    assignment_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    episode_key TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (assignment_id, kind, subject)
                );

                -- Catalog-side marker of committed sessions whose progression
                -- signals have been evaluated (ADR 032, ticket #33). Written in the
                -- same transaction as the alert transitions, so re-processing an
                -- older session (even after later ones) is a no-op.
                CREATE TABLE IF NOT EXISTS progression_alert_sessions (
                    assignment_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (assignment_id, session_id)
                );

                -- Catalog-side model usage metering (ADR 038, ticket #39). One row per
                -- model call, keyed by the immutable account id and model. ``account_id``
                -- is NULL only for an unattributed call (startup/eval), never a live
                -- request. ``estimated`` marks a row whose tokens fell back to the
                -- documented chars/4 heuristic because the provider returned no usage.
                CREATE TABLE IF NOT EXISTS model_usage (
                    id TEXT PRIMARY KEY,
                    account_id TEXT,
                    role TEXT NOT NULL,
                    model TEXT NOT NULL,
                    purpose TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_usage_account_created
                    ON model_usage(account_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_model_usage_created ON model_usage(created_at);

                -- Spend-alert state: one row per UTC calendar month. ``fired_at`` is the
                -- claim time and ``notified_at`` is set only after the owner email is
                -- delivered, so a failed/absent send leaves the row claimable for retry
                -- and a delivered one is never repeated (ADR 038, AC3).
                CREATE TABLE IF NOT EXISTS model_spend_alerts (
                    period TEXT PRIMARY KEY,
                    projected_usd REAL NOT NULL,
                    actual_usd REAL NOT NULL,
                    fired_at TEXT NOT NULL,
                    notified_at TEXT
                );
            """)
            self._create_coach_alerts_schema()
            self._ensure_roster_attendance_timezone()
            self._ensure_model_spend_alert_columns()
            self._commit_catalog()
            self._account_schema_ready = True

    # ------------------------------------------------------------------
    # Catalog transactions. The whole progression-alert evaluation for one
    # commit runs inside a single explicit transaction under the catalog lock
    # (ADR 032). Catalog write methods detect the active transaction and skip
    # their own commit, so a failure anywhere rolls the whole evaluation back.
    # ------------------------------------------------------------------

    @contextmanager
    def catalog_transaction(self) -> Iterator[None]:
        """Runs a group of catalog writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised. The catalog lock
        is held for the life of the transaction.
        """
        with self._catalog_lock:
            depth = getattr(self._local, "catalog_tx_depth", 0)
            self._local.catalog_tx_depth = depth + 1
            outermost = depth == 0
            original_isolation = self.catalog_conn.isolation_level
            if outermost:
                self.catalog_conn.isolation_level = None
                self.catalog_conn.execute("BEGIN")
            try:
                yield
            except Exception:
                if outermost:
                    self.catalog_conn.execute("ROLLBACK")
                raise
            else:
                if outermost:
                    self.catalog_conn.execute("COMMIT")
            finally:
                self._local.catalog_tx_depth = depth
                if outermost:
                    self.catalog_conn.isolation_level = original_isolation

    def _commit_catalog(self) -> None:
        """Commits a standalone catalog write, or defers to the active transaction."""
        if getattr(self._local, "catalog_tx_depth", 0) == 0:
            self.catalog_conn.commit()

    # ------------------------------------------------------------------
    # Model usage metering + spend alerts (ADR 038, ticket #39). Catalog-side
    # so an owner report and the in-process spend check read one shared table
    # without mounting any player ledger.
    # ------------------------------------------------------------------

    _MODEL_USAGE_COLUMNS = (
        "id, account_id, role, model, purpose, input_tokens, output_tokens, estimated, cost_usd, created_at"
    )

    @staticmethod
    def _model_usage_from_row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "account_id": row[1],
            "role": str(row[2]),
            "model": str(row[3]),
            "purpose": row[4],
            "input_tokens": int(row[5]),
            "output_tokens": int(row[6]),
            "estimated": bool(row[7]),
            "cost_usd": float(row[8]),
            "created_at": str(row[9]),
        }

    def record_model_usage(
        self,
        account_id: str | None,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        estimated: bool,
        purpose: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Appends one metered model call to the catalog.

        ``account_id`` is ``None`` only for an unattributed call (startup/eval).
        A write failure propagates; the metering callback catches it so inference
        is never broken (ADR 038).
        """
        self.ensure_account_schema()
        row = (
            uuid.uuid4().hex,
            str(account_id) if account_id else None,
            str(role or "unknown"),
            str(model),
            str(purpose) if purpose else None,
            max(0, int(input_tokens)),
            max(0, int(output_tokens)),
            1 if estimated else 0,
            float(cost_usd or 0.0),
            created_at or datetime.now(UTC).isoformat(),
        )
        with self._catalog_lock:
            self.catalog_conn.execute(
                f"INSERT INTO model_usage ({self._MODEL_USAGE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._commit_catalog()

    def sum_model_cost(self, start_iso: str, end_iso: str | None = None) -> float:
        """Total metered USD cost in the half-open window ``[start, end)``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            if end_iso is None:
                cursor.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ?", (start_iso,))
            else:
                cursor.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM model_usage WHERE created_at >= ? AND created_at < ?",
                    (start_iso, end_iso),
                )
            row = cursor.fetchone()
        return float(row[0] or 0.0) if row else 0.0

    def sum_model_tokens_for_account(self, account_id: str, start_iso: str, end_iso: str | None = None) -> int:
        """Total (input + output) tokens for one account in ``[start, end)``."""
        if not account_id:
            return 0
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            if end_iso is None:
                cursor.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
                    " WHERE account_id = ? AND created_at >= ?",
                    (str(account_id), start_iso),
                )
            else:
                cursor.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM model_usage"
                    " WHERE account_id = ? AND created_at >= ? AND created_at < ?",
                    (str(account_id), start_iso, end_iso),
                )
            row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    def summarize_model_usage(self, start_iso: str, end_iso: str | None = None) -> list[dict[str, Any]]:
        """Per account/role/model totals for the owner report, ordered for display."""
        self.ensure_account_schema()
        where, params = ("created_at >= ?", [start_iso]) if end_iso is None else (
            "created_at >= ? AND created_at < ?",
            [start_iso, end_iso],
        )
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, role, model, COUNT(*),"
                " COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),"
                " COALESCE(SUM(cost_usd), 0), COALESCE(SUM(estimated), 0)"
                f" FROM model_usage WHERE {where}"
                " GROUP BY account_id, role, model ORDER BY account_id, role, model",
                params,
            )
            rows = cursor.fetchall()
        return [
            {
                "account_id": row[0],
                "role": str(row[1]),
                "model": str(row[2]),
                "requests": int(row[3]),
                "input_tokens": int(row[4]),
                "output_tokens": int(row[5]),
                "cost_usd": float(row[6]),
                "estimated_calls": int(row[7]),
            }
            for row in rows
        ]

    def get_model_spend_alert(self, period: str) -> dict[str, Any] | None:
        """The stored spend-alert row for a UTC ``YYYY-MM`` period, or ``None``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT period, projected_usd, actual_usd, fired_at, notified_at"
                " FROM model_spend_alerts WHERE period = ?",
                (str(period),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "period": str(row[0]),
            "projected_usd": float(row[1]),
            "actual_usd": float(row[2]),
            "fired_at": row[3],
            "notified_at": row[4],
        }

    def claim_model_spend_alert(
        self, period: str, projected_usd: float, actual_usd: float, fired_at: str
    ) -> bool:
        """Claims the once-per-month alert slot; ``True`` only for the first writer.

        ``INSERT OR IGNORE`` on the ``period`` primary key means exactly one
        caller observes ``True`` under concurrent sweeps. ``notified_at`` starts
        NULL and is set only after a successful send (ADR 038).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO model_spend_alerts"
                " (period, projected_usd, actual_usd, fired_at, notified_at) VALUES (?, ?, ?, ?, NULL)",
                (str(period), float(projected_usd), float(actual_usd), str(fired_at)),
            )
            inserted = cursor.rowcount == 1
            self._commit_catalog()
        return inserted

    def mark_model_spend_alert_notified(self, period: str, notified_at: str) -> None:
        """Records that the alert email was delivered for ``period`` (retry-complete)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "UPDATE model_spend_alerts SET notified_at = ? WHERE period = ? AND notified_at IS NULL",
                (str(notified_at), str(period)),
            )
            self._commit_catalog()

    # ------------------------------------------------------------------
    # Ledger transactions. All writes for one workout commit run inside a
    # single explicit transaction on this thread's mounted ledger connection
    # (ADR 020/033). Ledger write helpers detect the active transaction and
    # skip their own commit, so a failure anywhere rolls the whole commit back.
    # ------------------------------------------------------------------

    @contextmanager
    def ledger_transaction(self) -> Iterator[None]:
        """Runs a group of ledger writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised.
        """
        conn = self.conn
        depth = getattr(self._local, "ledger_tx_depth", 0)
        self._local.ledger_tx_depth = depth + 1
        outermost = depth == 0
        original_isolation = conn.isolation_level
        if outermost:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if outermost:
                conn.execute("ROLLBACK")
            raise
        else:
            if outermost:
                conn.execute("COMMIT")
        finally:
            self._local.ledger_tx_depth = depth
            if outermost:
                conn.isolation_level = original_isolation

    def _commit_ledger(self) -> None:
        """Commits a standalone ledger write, or defers to the active transaction."""
        if getattr(self._local, "ledger_tx_depth", 0) == 0:
            self.conn.commit()

    def commit_ledger(self) -> None:
        """Public seam for ledger writers outside this module (e.g. ``agent.progression_engine``)."""
        self._commit_ledger()

    # ------------------------------------------------------------------
    # Idempotent offline-session commits (ADR 020/033, #34). The exact
    # response stored against the client session id is replayed on retry.
    # ------------------------------------------------------------------

    @staticmethod
    def _session_commit_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "client_session_id": str(row[0]),
            "session_id": str(row[1]),
            "response_json": str(row[2]),
            "committed_at": str(row[3]),
        }

    def get_session_commit(self, client_session_id: str) -> dict[str, Any] | None:
        """The stored commit for a client session id, or None when never committed."""
        if not client_session_id:
            return None
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT client_session_id, session_id, response_json, committed_at"
            " FROM session_commits WHERE client_session_id = ?",
            (str(client_session_id),),
        )
        return self._session_commit_from_row(cursor.fetchone())

    def record_session_commit(
        self, client_session_id: str, session_id: str, response_json: str, committed_at: str
    ) -> None:
        """Stores the exact response for a client session id (idempotency record)."""
        self.conn.execute(
            "INSERT INTO session_commits (client_session_id, session_id, response_json, committed_at)"
            " VALUES (?, ?, ?, ?)",
            (str(client_session_id), str(session_id), response_json, committed_at),
        )
        self._commit_ledger()

    # ------------------------------------------------------------------
    # Performed-date corrections (ADR 020/035). A correction rewrites only
    # the session's performed date and appends an immutable audit row; the
    # capture/upload timestamps are never touched.
    # ------------------------------------------------------------------

    def get_workout_session(self, session_id: str) -> dict[str, Any] | None:
        """One session's dates and sync identity, or None when not in this ledger."""
        if not session_id:
            return None
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, session_date, client_session_id, performed_timezone,"
            " captured_at, uploaded_at, edited_at, started_at"
            " FROM workout_sessions WHERE id = ?",
            (str(session_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "session_id": row["id"],
            "session_date": row["session_date"],
            "client_session_id": row["client_session_id"],
            "performed_timezone": row["performed_timezone"],
            "captured_at": row["captured_at"],
            "uploaded_at": row["uploaded_at"],
            "edited_at": row["edited_at"],
            "started_at": row["started_at"],
        }

    def update_session_performed_date(
        self, session_id: str, performed_date: str, edited_at: str
    ) -> None:
        """Rewrites the performed date and stamps ``edited_at``; capture/upload stay."""
        self.conn.execute(
            "UPDATE workout_sessions SET session_date = ?, edited_at = ? WHERE id = ?",
            (str(performed_date), str(edited_at), str(session_id)),
        )
        self._commit_ledger()

    def record_performed_date_correction(
        self, session_id: str, previous_date: str, corrected_date: str, corrected_at: str
    ) -> None:
        """Appends one immutable correction row for a session."""
        self.conn.execute(
            "INSERT INTO performed_date_corrections"
            " (id, session_id, previous_date, corrected_date, corrected_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), str(session_id), str(previous_date), str(corrected_date), str(corrected_at)),
        )
        self._commit_ledger()

    @staticmethod
    def _correction_from_row(row: Any) -> dict[str, Any]:
        return {
            "previous_date": row["previous_date"],
            "corrected_date": row["corrected_date"],
            "corrected_at": row["corrected_at"],
        }

    def list_performed_date_corrections(self, session_id: str) -> list[dict[str, Any]]:
        """Every correction for one session, oldest-first."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT previous_date, corrected_date, corrected_at"
            " FROM performed_date_corrections WHERE session_id = ?"
            " ORDER BY corrected_at ASC, rowid ASC",
            (str(session_id),),
        )
        return [self._correction_from_row(row) for row in cursor.fetchall()]

    def get_session_audit_metadata(self) -> dict[str, dict[str, Any]]:
        """Per-session upload/edit timestamps and correction history, keyed by session id.

        Kept separate from ``get_session_log`` so the ledger export shape is
        unchanged while the coach history can annotate corrections (ADR 035).
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, uploaded_at, edited_at FROM workout_sessions")
        audit: dict[str, dict[str, Any]] = {
            row["id"]: {
                "uploaded_at": row["uploaded_at"],
                "edited_at": row["edited_at"],
                "corrections": [],
            }
            for row in cursor.fetchall()
        }
        cursor.execute(
            "SELECT session_id, previous_date, corrected_date, corrected_at"
            " FROM performed_date_corrections ORDER BY corrected_at ASC, rowid ASC"
        )
        for row in cursor.fetchall():
            entry = audit.get(row["session_id"])
            if entry is not None:
                entry["corrections"].append(self._correction_from_row(row))
        return audit

    # ------------------------------------------------------------------
    # coach_alerts generalised shape (ADR 031). The table + index DDL lives
    # in one place so the fresh-create path and the legacy rebuild cannot
    # drift apart; the rebuild is a single explicit transaction.
    # ------------------------------------------------------------------

    _COACH_ALERTS_TABLE_SQL = (
        "alert_id TEXT PRIMARY KEY,"
        " assignment_id TEXT NOT NULL,"
        " coach_account_id TEXT NOT NULL,"
        " player_account_id TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " dedupe_key TEXT NOT NULL,"
        " details TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'new'"
        " CHECK (state IN ('new', 'acknowledged', 'resolved')),"
        " created_at TEXT NOT NULL,"
        " acknowledged_at TEXT,"
        " resolved_at TEXT,"
        " resolved_by TEXT"
    )
    _COACH_ALERTS_INDEX_SQL = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_alerts_dedupe"
        " ON coach_alerts(assignment_id, kind, dedupe_key)",
        "CREATE INDEX IF NOT EXISTS idx_coach_alerts_coach"
        " ON coach_alerts(coach_account_id, state)",
        "CREATE INDEX IF NOT EXISTS idx_coach_alerts_assignment ON coach_alerts(assignment_id)",
    )
    _LEGACY_COACH_ALERT_COLUMNS = (
        "alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " streak_start_date, last_missed_date, missed_count, state, created_at,"
        " acknowledged_at, resolved_at, resolved_by"
    )

    @classmethod
    def _coach_alerts_create_sql(cls, table: str) -> str:
        return f"CREATE TABLE IF NOT EXISTS {table} ({cls._COACH_ALERTS_TABLE_SQL})"

    def _create_coach_alerts_schema(self) -> None:
        """Fresh-create (or complete) the generalised ``coach_alerts`` and its indexes."""
        statements = [self._coach_alerts_create_sql("coach_alerts"), *self._COACH_ALERTS_INDEX_SQL]
        self.catalog_conn.executescript(";\n".join(statements) + ";")

    @staticmethod
    def _table_columns(cursor: Any, table: str) -> set[str]:
        """Column names present on ``table``; empty when the table does not exist."""
        cursor.execute(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in cursor.fetchall()}

    def _copy_legacy_coach_alert_rows(self, cursor: Any) -> None:
        """Copy legacy missed-day rows into ``coach_alerts_new``, mapping to details.

        A separate method so a failure mid-rebuild is injectable in tests.
        """
        rows = cursor.execute(
            f"SELECT {self._LEGACY_COACH_ALERT_COLUMNS} FROM coach_alerts"
        ).fetchall()
        for row in rows:
            details = {
                "streak_start_date": str(row[5]),
                "last_missed_date": str(row[6]),
                "missed_count": int(row[7]),
            }
            cursor.execute(
                "INSERT INTO coach_alerts_new"
                " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
                " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                    json.dumps(details),
                    str(row[8]),
                    str(row[9]),
                    row[10],
                    row[11],
                    row[12],
                ),
            )

    def _migrate_coach_alerts_shape(self) -> None:
        """Rebuild the legacy missed-day-shaped ``coach_alerts`` in place (ADR 031).

        Idempotent and crash-safe. The caller already holds ``_catalog_lock`` for
        the whole rebuild (``catalog_transaction`` is re-entrant). Shape detection
        handles every crash point:

        * old shape + no leftover: the normal rebuild;
        * old shape + leftover ``coach_alerts_new``: drop the orphan and rebuild;
        * no old table but leftover ``coach_alerts_new``: the crash happened after
          the old table was dropped, so the leftover is complete and is renamed;
        * already migrated: any orphan is dropped and nothing else happens.

        The rebuild runs inside one ``catalog_transaction`` ``BEGIN``/``COMMIT``
        and rolls back on any exception, so a failure leaves the old table and its
        rows intact.
        """
        cursor = self.catalog_conn.cursor()
        old_columns = self._table_columns(cursor, "coach_alerts")
        new_columns = self._table_columns(cursor, "coach_alerts_new")

        if old_columns and "dedupe_key" in old_columns:
            # Already migrated; clear any orphan left by an interrupted run.
            if new_columns:
                with self.catalog_transaction():
                    self.catalog_conn.execute("DROP TABLE IF EXISTS coach_alerts_new")
            return
        if not old_columns and not new_columns:
            return

        with self.catalog_transaction():
            cursor = self.catalog_conn.cursor()
            if not old_columns and new_columns:
                # The old table was already dropped before the crash: finish.
                cursor.execute("ALTER TABLE coach_alerts_new RENAME TO coach_alerts")
            else:
                cursor.execute("DROP TABLE IF EXISTS coach_alerts_new")
                cursor.execute(self._coach_alerts_create_sql("coach_alerts_new"))
                self._copy_legacy_coach_alert_rows(cursor)
                cursor.execute("DROP TABLE coach_alerts")
                cursor.execute("ALTER TABLE coach_alerts_new RENAME TO coach_alerts")
            for statement in self._COACH_ALERTS_INDEX_SQL:
                cursor.execute(statement)

    def _ensure_roster_attendance_timezone(self) -> None:
        """Additive ``timezone`` column on an existing ``roster_attendance`` (ADR 031)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "roster_attendance")
        if columns and "timezone" not in columns:
            cursor.execute("ALTER TABLE roster_attendance ADD COLUMN timezone TEXT")

    def _ensure_model_spend_alert_columns(self) -> None:
        """Additive ``fired_at``/``notified_at`` on an existing ``model_spend_alerts`` (ADR 038)."""
        cursor = self.catalog_conn.cursor()
        columns = self._table_columns(cursor, "model_spend_alerts")
        if columns and "fired_at" not in columns:
            cursor.execute("ALTER TABLE model_spend_alerts ADD COLUMN fired_at TEXT")
        if columns and "notified_at" not in columns:
            cursor.execute("ALTER TABLE model_spend_alerts ADD COLUMN notified_at TEXT")

    _ACCOUNT_COLUMNS = (
        "account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at"
    )

    _PROGRAM_REQUEST_COLUMNS = (
        "request_id, assignment_id, coach_account_id, player_account_id, kind, program_version,"
        " day_name, exercise_id, replacement_exercise_id, desired_weekly_frequency,"
        " desired_split_preference, reason, status, response, created_at, resolved_at, resolved_by"
    )

    @staticmethod
    def _account_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "account_id": str(row[0]),
            "username": str(row[1]),
            "ledger_id": str(row[2]),
            "status": str(row[3]),
            "is_player": bool(row[4]),
            "is_coach": bool(row[5]),
            "session_epoch": max(1, int(row[6] or 1)),
            "created_at": str(row[7]),
            "deleted_at": row[8],
        }

    @staticmethod
    def is_live_account(account: dict[str, Any] | None) -> bool:
        """True only when an account row is live.

        Deletion is authoritative: a non-NULL ``deleted_at`` makes the row dead
        even if ``status`` was left as ``'active'`` by an interrupted deletion.
        Callers use this to fail closed before mounting a ledger.
        """
        return bool(account) and account["status"] == "active" and account["deleted_at"] is None

    def create_account(self, username: str) -> str | None:
        """Atomically reserves ``username`` and returns a new immutable account id.

        Returns ``None`` when a live account already owns the username. The
        uniqueness is enforced by a partial unique index, so concurrent
        registrations cannot both succeed; deleted rows keep their old id, which
        lets the username be reused later under a new id.
        """
        clean_id = self._sanitize_username(username)
        if not clean_id:
            return None
        self.ensure_account_schema()
        account_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO accounts"
                    " (account_id, username, ledger_id, status, is_player, is_coach, session_epoch, created_at, deleted_at)"
                    " VALUES (?, ?, ?, 'active', 1, 0, 1, ?, NULL)",
                    (account_id, clean_id, clean_id, now),
                )
                self.catalog_conn.commit()
            except sqlite3.IntegrityError:
                self.catalog_conn.rollback()
                return None
        return account_id

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        """Reads an account by immutable id. Returns ``None`` when absent (fail closed)."""
        if not account_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (str(account_id),))
            return self._account_from_row(cursor.fetchone())

    def get_active_account_by_username(self, username: str) -> dict[str, Any] | None:
        """Reads the live account owning ``username``.

        Requires both ``status = 'active'`` and ``deleted_at IS NULL`` so an
        inactive row with an unset deletion timestamp can never be treated as
        live by login, claim, or recovery.
        """
        clean_id = self._sanitize_username(username)
        if not clean_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts"
                " WHERE username = ? AND status = 'active' AND deleted_at IS NULL",
                (clean_id,),
            )
            return self._account_from_row(cursor.fetchone())

    def bump_account_session_epoch(self, account_id: str) -> int | None:
        """Advances the registry session epoch, invalidating every prior token. Returns the new epoch."""
        if not account_id:
            return None
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT session_epoch FROM accounts WHERE account_id = ?", (str(account_id),))
            row = cursor.fetchone()
            if row is None:
                return None
            new_epoch = max(1, int(row[0] or 1)) + 1
            cursor.execute("UPDATE accounts SET session_epoch = ? WHERE account_id = ?", (new_epoch, str(account_id)))
            self.catalog_conn.commit()
            return new_epoch

    _PLAN_COLUMNS = "account_id, capability, plan, status, updated_at"

    @staticmethod
    def _plan_from_row(row: Any) -> dict[str, Any]:
        return {
            "account_id": str(row[0]),
            "capability": str(row[1]),
            "plan": str(row[2]),
            "status": str(row[3]),
            "updated_at": str(row[4]),
        }

    def list_plans(self, account_id: str) -> list[dict[str, Any]]:
        """Lists every stored plan override for an immutable account id."""
        if not account_id:
            return []
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PLAN_COLUMNS} FROM account_plans WHERE account_id = ? ORDER BY capability",
                (str(account_id),),
            )
            return [self._plan_from_row(row) for row in cursor.fetchall()]

    def set_plan(self, account_id: str, capability: str, plan: str, status: str = "active") -> None:
        """Upserts one capability's plan. Callers must check capability eligibility first."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                """
                INSERT INTO account_plans (account_id, capability, plan, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, capability) DO UPDATE SET
                    plan = excluded.plan,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (str(account_id), str(capability), str(plan), str(status), now),
            )
            self.catalog_conn.commit()

    def set_trainee_email(self, trainee_id: str, email: str) -> None:
        """Links a normalized email to a trainee. Raises ValueError if taken by another ledger."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row is not None and row[0] != trainee_id:
                raise ValueError("This email is already linked to another ledger.")
            cursor.execute(
                """
                INSERT INTO trainee_emails (trainee_id, email, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(trainee_id) DO UPDATE SET email = excluded.email, updated_at = excluded.updated_at
                """,
                (trainee_id, email, now),
            )
            self.catalog_conn.commit()

    def get_trainee_email(self, trainee_id: str) -> str | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT email FROM trainee_emails WHERE trainee_id = ?", (trainee_id,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def get_trainee_by_email(self, email: str) -> str | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT trainee_id FROM trainee_emails WHERE email = ?", (email,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def store_reset_token(self, token_hash: str, trainee_id: str, expires_at: str) -> None:
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO password_reset_tokens (token_hash, trainee_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (token_hash, trainee_id, expires_at, now),
            )
            self.catalog_conn.commit()

    def consume_reset_token(self, token_hash: str, now_iso: str) -> str | None:
        """Atomically marks a valid (unused, unexpired) token used. Returns trainee_id or None."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT trainee_id, expires_at, used_at FROM password_reset_tokens WHERE token_hash = ?",
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None or row[2] is not None or str(row[1]) <= now_iso:
                return None
            trainee_id = str(row[0])
            cursor.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (now_iso, token_hash),
            )
            if cursor.rowcount != 1:
                return None
            self.catalog_conn.commit()
            return trainee_id

    def prune_reset_tokens(self, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM password_reset_tokens WHERE expires_at < ? OR used_at IS NOT NULL",
                (now_iso,),
            )
            self.catalog_conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Owner-issued coach invitations and the coach profile. Catalog-side
    # and keyed by immutable account id so capability grants survive ledger
    # changes and coach reads never open a player ledger.
    # ------------------------------------------------------------------

    def create_coach_invite(self, token_hash: str, account_id: str, expires_at: str) -> None:
        """Stores a hashed, account-bound invite. The raw token is never persisted."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO coach_invites (token_hash, account_id, expires_at, used_at, created_at)"
                " VALUES (?, ?, ?, NULL, ?)",
                (token_hash, str(account_id), expires_at, now),
            )
            self.catalog_conn.commit()

    def redeem_coach_invite(
        self, token_hash: str, account_id: str, now_iso: str, default_capacity: int
    ) -> dict[str, Any] | None:
        """Atomically claims a coach invite and grants the coach capability.

        ``account_id`` is the caller's verified immutable id; the invite must be
        bound to it, so a leaked code cannot grant an arbitrary account. Returns
        the updated account row on success, or ``None`` when the token is unknown,
        expired, already used, bound to another account, or bound to a
        dead/non-player account. The ``used_at`` claim, the ``is_coach`` flip, and
        the profile seed commit as one transaction, so a leaked code cannot be
        replayed and a crash cannot leave the capability half-granted.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, expires_at, used_at FROM coach_invites WHERE token_hash = ?",
                (token_hash,),
            )
            row = cursor.fetchone()
            if row is None or row[2] is not None or str(row[1]) <= now_iso:
                return None
            if str(row[0]) != str(account_id):
                return None
            cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (account_id,))
            account = self._account_from_row(cursor.fetchone())
            if not self.is_live_account(account) or not account["is_player"]:
                return None
            try:
                cursor.execute(
                    "UPDATE coach_invites SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                    (now_iso, token_hash),
                )
                if cursor.rowcount != 1:
                    self.catalog_conn.rollback()
                    return None
                cursor.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (account_id,))
                cursor.execute(
                    """
                    INSERT INTO coach_profiles
                        (account_id, display_name, bio, specialization, capacity, created_at, updated_at)
                    VALUES (?, ?, '', '', ?, ?, ?)
                    ON CONFLICT(account_id) DO NOTHING
                    """,
                    (account_id, account["username"], int(default_capacity), now_iso, now_iso),
                )
                self.catalog_conn.commit()
            except sqlite3.Error:
                self.catalog_conn.rollback()
                raise
            account["is_coach"] = True
            return account

    def prune_coach_invites(self, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM coach_invites WHERE expires_at < ? OR used_at IS NOT NULL",
                (now_iso,),
            )
            self.catalog_conn.commit()
            return cursor.rowcount

    def get_coach_profile(self, account_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT account_id, display_name, bio, specialization, capacity"
                " FROM coach_profiles WHERE account_id = ?",
                (str(account_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "account_id": str(row[0]),
                "display_name": str(row[1]),
                "bio": str(row[2]),
                "specialization": str(row[3]),
                "capacity": int(row[4]),
            }

    def upsert_coach_profile(self, account_id: str, profile: dict[str, Any]) -> None:
        """Writes coach-authored fields; callers validate and bound them first."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                """
                INSERT INTO coach_profiles
                    (account_id, display_name, bio, specialization, capacity, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    bio = excluded.bio,
                    specialization = excluded.specialization,
                    capacity = excluded.capacity,
                    updated_at = excluded.updated_at
                """,
                (
                    str(account_id),
                    profile["display_name"],
                    profile["bio"],
                    profile["specialization"],
                    int(profile["capacity"]),
                    now,
                    now,
                ),
            )
            self.catalog_conn.commit()

    # ------------------------------------------------------------------
    # Assignment lifecycle (ticket #24). Catalog-side, keyed by immutable
    # account ids, so capacity checks, access checks, and list views never
    # open a player ledger.
    # ------------------------------------------------------------------

    _ASSIGNMENT_COLUMNS = (
        "assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by"
    )

    @classmethod
    def _assignment_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "assignment_id": str(row[0]),
            "coach_account_id": str(row[1]),
            "player_account_id": str(row[2]),
            "status": str(row[3]),
            "started_at": str(row[4]),
            "ended_at": row[5],
            "ended_by": row[6],
        }

    def create_assignment_invite(self, token_hash: str, coach_account_id: str, expires_at: str) -> None:
        """Stores a hashed, capacity-bound assignment invite. The raw code is never persisted."""
        self.ensure_account_schema()
        now = datetime.now(UTC).isoformat()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO assignment_invites"
                " (token_hash, coach_account_id, expires_at, used_at, redeemed_by_account_id, assignment_id, created_at)"
                " VALUES (?, ?, ?, NULL, NULL, NULL, ?)",
                (token_hash, str(coach_account_id), expires_at, now),
            )
            self.catalog_conn.commit()

    def get_assignment_invite(self, token_hash: str) -> dict[str, Any] | None:
        """Reads an invite by hash for preview. Never consumes it."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT coach_account_id, expires_at, used_at, redeemed_by_account_id, assignment_id"
                " FROM assignment_invites WHERE token_hash = ?",
                (str(token_hash),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "coach_account_id": str(row[0]),
                "expires_at": str(row[1]),
                "used_at": row[2],
                "redeemed_by_account_id": row[3],
                "assignment_id": row[4],
            }

    def prune_assignment_invites(self, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "DELETE FROM assignment_invites WHERE expires_at < ? OR used_at IS NOT NULL",
                (now_iso,),
            )
            self.catalog_conn.commit()
            return cursor.rowcount

    def get_coach_capacity(self, coach_account_id: str) -> int | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT capacity FROM coach_profiles WHERE account_id = ?", (str(coach_account_id),))
            row = cursor.fetchone()
            return int(row[0]) if row is not None else None

    def count_active_assignments_for_coach(self, coach_account_id: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM assignments WHERE coach_account_id = ? AND status = 'active'",
                (str(coach_account_id),),
            )
            return int(cursor.fetchone()[0])

    def get_active_assignment_for_player(self, player_account_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE player_account_id = ? AND status = 'active'",
                (str(player_account_id),),
            )
            return self._assignment_from_row(cursor.fetchone())

    def get_active_assignment_for_coach(self, coach_account_id: str, assignment_id: str) -> dict[str, Any] | None:
        """Reads one active assignment only when it belongs to this coach.

        The catalog-only gate for a coach's drill-down reads; ``None`` for an
        unknown, ended, or other coach's assignment, so callers deny all three
        identically and never mount a ledger.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE assignment_id = ? AND coach_account_id = ? AND status = 'active'",
                (str(assignment_id), str(coach_account_id)),
            )
            return self._assignment_from_row(cursor.fetchone())

    def list_active_assignments_for_coach(self, coach_account_id: str) -> list[dict[str, Any]]:
        """Lists active assignments with the player's username; catalog-only, no ledger mount."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id, a.player_account_id, a.started_at, a.status, acc.username"
                " FROM assignments a LEFT JOIN accounts acc ON acc.account_id = a.player_account_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " ORDER BY a.started_at DESC",
                (str(coach_account_id),),
            )
            return [
                {
                    "assignment_id": str(row[0]),
                    "player_account_id": str(row[1]),
                    "started_at": str(row[2]),
                    "status": str(row[3]),
                    "player_username": str(row[4]) if row[4] is not None else "former player",
                }
                for row in cursor.fetchall()
            ]

    def _begin_immediate(self) -> None:
        """Starts a write transaction now, so reads in the block see a locked catalog.

        The catalog lock only orders threads in this process; ``BEGIN IMMEDIATE``
        takes SQLite's write lock before any capacity/account read, so a second
        connection or process cannot interleave between the check and the insert.
        """
        self.catalog_conn.execute("BEGIN IMMEDIATE")

    def _redemption_target(
        self, cursor: Any, token_hash: str, player_account_id: str, now_iso: str
    ) -> dict[str, Any]:
        """Validates a redemption inside the caller's held write transaction.

        Returns ``{"ok": False, "reason": ...}`` for a safe failure, or
        ``{"ok": True, "coach_account_id": ..., "player_username": ...}`` with the
        data the caller needs to write the assignment.
        """
        cursor.execute(
            "SELECT coach_account_id, expires_at, used_at FROM assignment_invites WHERE token_hash = ?",
            (str(token_hash),),
        )
        invite = cursor.fetchone()
        if invite is None or invite[2] is not None or str(invite[1]) <= now_iso:
            return {"ok": False, "reason": "invalid"}
        coach_account_id = str(invite[0])
        if coach_account_id == str(player_account_id):
            return {"ok": False, "reason": "self"}

        cursor.execute(f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (coach_account_id,))
        coach = self._account_from_row(cursor.fetchone())
        if not self.is_live_account(coach) or not coach["is_coach"]:
            return {"ok": False, "reason": "invalid"}

        cursor.execute(
            f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?", (str(player_account_id),)
        )
        player = self._account_from_row(cursor.fetchone())
        if not self.is_live_account(player) or not player["is_player"]:
            return {"ok": False, "reason": "invalid"}

        cursor.execute(
            "SELECT 1 FROM assignments WHERE player_account_id = ? AND status = 'active'",
            (str(player_account_id),),
        )
        if cursor.fetchone() is not None:
            return {"ok": False, "reason": "already_assigned"}

        cursor.execute("SELECT capacity FROM coach_profiles WHERE account_id = ?", (coach_account_id,))
        capacity_row = cursor.fetchone()
        capacity = int(capacity_row[0]) if capacity_row is not None else 0
        cursor.execute(
            "SELECT COUNT(*) FROM assignments WHERE coach_account_id = ? AND status = 'active'",
            (coach_account_id,),
        )
        if int(cursor.fetchone()[0]) >= capacity:
            return {"ok": False, "reason": "capacity"}
        return {"ok": True, "coach_account_id": coach_account_id, "player_username": player["username"]}

    def redeem_assignment_invite(
        self, token_hash: str, player_account_id: str, now_iso: str
    ) -> dict[str, Any]:
        """Atomically claims an assignment invite, creates the assignment and the coach notice.

        A single ``BEGIN IMMEDIATE`` transaction spans the invite read, account and
        capacity checks, the one-use claim, the assignment insert, and the coach
        notice, so concurrent redeemers on the same catalog cannot overfill a coach.
        Returns a reason-tagged result without leaking whether a code exists.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            conn = self.catalog_conn
            self._begin_immediate()
            cursor = conn.cursor()

            def fail(reason: str) -> dict[str, Any]:
                conn.rollback()
                return {"ok": False, "reason": reason}

            try:
                target = self._redemption_target(cursor, token_hash, player_account_id, now_iso)
                if not target["ok"]:
                    return fail(target["reason"])
                coach_account_id = target["coach_account_id"]
                player_username = target["player_username"]

                assignment_id = uuid.uuid4().hex
                notice_id = uuid.uuid4().hex
                cursor.execute(
                    "UPDATE assignment_invites"
                    " SET used_at = ?, redeemed_by_account_id = ?, assignment_id = ?"
                    " WHERE token_hash = ? AND used_at IS NULL",
                    (now_iso, str(player_account_id), assignment_id, str(token_hash)),
                )
                if cursor.rowcount != 1:
                    return fail("invalid")
                cursor.execute(
                    "INSERT INTO assignments"
                    " (assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by)"
                    " VALUES (?, ?, ?, 'active', ?, NULL, NULL)",
                    (assignment_id, coach_account_id, str(player_account_id), now_iso),
                )
                cursor.execute(
                    "INSERT INTO assignment_notices"
                    " (notice_id, account_id, assignment_id, kind, message, created_at, read_at)"
                    " VALUES (?, ?, ?, 'assignment_redeemed', ?, ?, NULL)",
                    (
                        notice_id,
                        coach_account_id,
                        assignment_id,
                        f"{player_username} accepted your coaching invite and is now assigned to you.",
                        now_iso,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return fail("already_assigned")
            except sqlite3.Error:
                conn.rollback()
                raise
            return {
                "ok": True,
                "assignment_id": assignment_id,
                "coach_account_id": coach_account_id,
                "player_account_id": str(player_account_id),
                "player_username": player_username,
                "notice_id": notice_id,
                "started_at": now_iso,
            }

    def end_assignment(self, assignment_id: str, account_id: str, now_iso: str, ended_by: str) -> dict[str, Any]:
        """Ends an active assignment when the caller is a participant. Revocation is immediate."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT coach_account_id, player_account_id, status FROM assignments WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return {"ok": False, "reason": "not_found"}
            if str(row[0]) != str(account_id) and str(row[1]) != str(account_id):
                return {"ok": False, "reason": "forbidden"}
            if str(row[2]) != "active":
                return {"ok": False, "reason": "already_ended"}
            cursor.execute(
                "UPDATE assignments SET status = 'ended', ended_at = ?, ended_by = ?"
                " WHERE assignment_id = ? AND status = 'active'",
                (now_iso, str(ended_by), str(assignment_id)),
            )
            if cursor.rowcount != 1:
                self.catalog_conn.rollback()
                return {"ok": False, "reason": "already_ended"}
            self.catalog_conn.commit()
            return {"ok": True, "assignment_id": str(assignment_id), "ended_at": now_iso, "ended_by": str(ended_by)}

    def disable_coach_account(self, coach_account_id: str, now_iso: str, ended_by: str) -> dict[str, Any]:
        """Ends every active assignment and clears the coach capability in one transaction.

        A redemption that commits before this transaction is ended by it; one that
        arrives after blocks on ``BEGIN IMMEDIATE`` and then sees the cleared
        capability. Either way no assignment can remain active with a disabled coach.
        The player ledger is never touched.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            conn = self.catalog_conn
            self._begin_immediate()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"SELECT {self._ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?",
                    (str(coach_account_id),),
                )
                account = self._account_from_row(cursor.fetchone())
                if not self.is_live_account(account) or not account["is_coach"]:
                    conn.rollback()
                    return {"ok": False}
                cursor.execute(
                    "UPDATE assignments SET status = 'ended', ended_at = ?, ended_by = ?"
                    " WHERE coach_account_id = ? AND status = 'active'",
                    (now_iso, str(ended_by), str(coach_account_id)),
                )
                ended = int(cursor.rowcount)
                cursor.execute(
                    "UPDATE accounts SET is_coach = 0"
                    " WHERE account_id = ? AND status = 'active' AND deleted_at IS NULL",
                    (str(coach_account_id),),
                )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            return {"ok": True, "ended_assignments": ended}

    def create_assignment_notice(
        self, account_id: str, assignment_id: str | None, kind: str, message: str, now_iso: str
    ) -> str:
        """Writes one in-app notice for an account (coach or player)."""
        notice_id = uuid.uuid4().hex
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "INSERT INTO assignment_notices"
                " (notice_id, account_id, assignment_id, kind, message, created_at, read_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (notice_id, str(account_id), assignment_id, kind, message, now_iso),
            )
            self.catalog_conn.commit()
        return notice_id

    def list_assignment_notices(self, account_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT notice_id, assignment_id, kind, message, created_at, read_at"
                " FROM assignment_notices WHERE account_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (str(account_id), max(1, int(limit))),
            )
            return [
                {
                    "notice_id": str(row[0]),
                    "assignment_id": row[1],
                    "kind": str(row[2]),
                    "message": str(row[3]),
                    "created_at": str(row[4]),
                    "read_at": row[5],
                }
                for row in cursor.fetchall()
            ]

    def mark_assignment_notices_read(self, account_id: str, now_iso: str) -> int:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE assignment_notices SET read_at = ? WHERE account_id = ? AND read_at IS NULL",
                (now_iso, str(account_id)),
            )
            self.catalog_conn.commit()
            return int(cursor.rowcount)

    @staticmethod
    def _program_request_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "request_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "kind": str(row[4]),
            "program_version": int(row[5]),
            "day_name": row[6],
            "exercise_id": row[7],
            "replacement_exercise_id": row[8],
            "desired_weekly_frequency": int(row[9]) if row[9] is not None else None,
            "desired_split_preference": row[10],
            "reason": str(row[11]),
            "status": str(row[12]),
            "response": row[13],
            "created_at": str(row[14]),
            "resolved_at": row[15],
            "resolved_by": row[16],
        }

    def create_program_request(
        self,
        request_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        kind: str,
        program_version: int,
        day_name: str | None,
        exercise_id: str | None,
        replacement_exercise_id: str | None,
        desired_weekly_frequency: int | None,
        desired_split_preference: str | None,
        reason: str,
        now_iso: str,
    ) -> str:
        """Inserts a pending player program request. Never touches the player ledger."""
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "INSERT INTO program_requests"
                " (request_id, assignment_id, coach_account_id, player_account_id, kind, program_version,"
                " day_name, exercise_id, replacement_exercise_id, desired_weekly_frequency,"
                " desired_split_preference, reason, status, response, created_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, NULL, NULL)",
                (
                    str(request_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(kind),
                    int(program_version),
                    day_name,
                    exercise_id,
                    replacement_exercise_id,
                    desired_weekly_frequency,
                    desired_split_preference,
                    reason,
                    now_iso,
                ),
            )
            self.catalog_conn.commit()
        return request_id

    def get_program_request(self, request_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests WHERE request_id = ?",
                (str(request_id),),
            )
            return self._program_request_from_row(cursor.fetchone())

    def list_program_requests_for_assignment(self, assignment_id: str) -> list[dict[str, Any]]:
        """Requests for one assignment, newest-first. Catalog-only; no ledger mount."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests"
                " WHERE assignment_id = ? ORDER BY created_at DESC",
                (str(assignment_id),),
            )
            return [self._program_request_from_row(row) for row in cursor.fetchall()]

    def list_program_requests_for_player(self, player_account_id: str) -> list[dict[str, Any]]:
        """The player's own requests across assignments, newest-first."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests"
                " WHERE player_account_id = ? ORDER BY created_at DESC",
                (str(player_account_id),),
            )
            return [self._program_request_from_row(row) for row in cursor.fetchall()]

    def resolve_program_request(
        self, request_id: str, status: str, response: str | None, resolved_by: str, now_iso: str
    ) -> dict[str, Any]:
        """Atomically claims a pending request; a second resolver sees ``rowcount == 0``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE program_requests SET status = ?, response = ?, resolved_at = ?, resolved_by = ?"
                " WHERE request_id = ? AND status = 'pending'",
                (str(status), response, now_iso, str(resolved_by), str(request_id)),
            )
            self.catalog_conn.commit()
            return {"ok": cursor.rowcount == 1, "rowcount": int(cursor.rowcount)}

    def reopen_program_request(self, request_id: str, now_iso: str) -> dict[str, Any]:
        """Reverts an applied request back to pending after a post-claim write failure.

        Resets response and resolution provenance; only a currently-applied row is
        touched, so a racing cancel or decline is never clobbered.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE program_requests SET status = 'pending', response = NULL,"
                " resolved_at = NULL, resolved_by = NULL"
                " WHERE request_id = ? AND status = 'applied'",
                (str(request_id),),
            )
            self.catalog_conn.commit()
            return {"ok": cursor.rowcount == 1, "rowcount": int(cursor.rowcount)}

    # ------------------------------------------------------------------
    # Coach alerts and catalog-side roster attendance (ADR 030/031,
    # tickets #31/#32). Every read and write here is catalog-only: a roster or
    # alert read must never mount a player ledger (ADR 025).
    # ------------------------------------------------------------------

    _COACH_ALERT_COLUMNS = (
        "alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by"
    )

    @classmethod
    def _coach_alert_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            details = json.loads(row[6]) if row[6] else {}
        except (TypeError, ValueError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        # The kind-specific fields stay under ``details`` here; the service layer
        # flattens them into the API response shape (ADR 031).
        return {
            "alert_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "kind": str(row[4]),
            "dedupe_key": str(row[5]),
            "details": details,
            "state": str(row[7]),
            "created_at": str(row[8]),
            "acknowledged_at": row[9],
            "resolved_at": row[10],
            "resolved_by": row[11],
        }

    def insert_coach_alert(
        self,
        alert_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        kind: str,
        dedupe_key: str,
        details: dict[str, Any],
        now_iso: str,
    ) -> dict[str, Any]:
        """Inserts one alert for a dedupe key, ignoring a retry of the same key.

        Returns ``{"alert": ..., "created": bool}``. The unique
        ``(assignment_id, kind, dedupe_key)`` key means a concurrent or repeated
        sweep cannot create a second alert for one recurring fact.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO coach_alerts"
                " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
                " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, NULL, NULL, NULL)",
                (
                    str(alert_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(kind),
                    str(dedupe_key),
                    json.dumps(details),
                    now_iso,
                ),
            )
            created = cursor.rowcount == 1
            self._commit_catalog()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?",
                (str(assignment_id), str(kind), str(dedupe_key)),
            )
            return {"alert": self._coach_alert_from_row(cursor.fetchone()), "created": created}

    def get_coach_alert_by_dedupe(
        self, assignment_id: str, kind: str, dedupe_key: str
    ) -> dict[str, Any] | None:
        """The alert for one exact ``(assignment, kind, dedupe_key)``, or ``None``.

        Read-only, so an episode extension can look the open alert up without
        risking the creation of a new one (ADR 032).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?",
                (str(assignment_id), str(kind), str(dedupe_key)),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def get_coach_alert(self, alert_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts WHERE alert_id = ?",
                (str(alert_id),),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def list_coach_alerts(self, coach_account_id: str, states: tuple[str, ...]) -> list[dict[str, Any]]:
        """Alerts for a coach's still-active assignments only, newest-first, with the player name."""
        self.ensure_account_schema()
        if not states:
            return []
        placeholders = ", ".join("?" for _ in states)
        columns = ", ".join("c." + column for column in self._COACH_ALERT_COLUMNS.split(", "))
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {columns}, acc.username"
                " FROM coach_alerts c"
                " JOIN assignments a ON a.assignment_id = c.assignment_id AND a.status = 'active'"
                " JOIN accounts acc ON acc.account_id = c.player_account_id"
                f" WHERE c.coach_account_id = ? AND c.state IN ({placeholders})"
                " ORDER BY c.created_at DESC, c.rowid DESC",
                (str(coach_account_id), *states),
            )
            alerts = []
            for row in cursor.fetchall():
                alert = self._coach_alert_from_row(row)
                alert["player_username"] = str(row[12])
                alerts.append(alert)
            return alerts

    def update_coach_alert_details(self, alert_id: str, details: dict[str, Any]) -> int:
        """Extends an open alert's kind-specific fields; a no-op reports ``rowcount == 0``."""
        self.ensure_account_schema()
        encoded = json.dumps(details)
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET details = ?"
                " WHERE alert_id = ? AND state IN ('new', 'acknowledged')"
                " AND details != ?",
                (encoded, str(alert_id), encoded),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    def acknowledge_coach_alert(
        self, alert_id: str, coach_account_id: str, now_iso: str
    ) -> dict[str, Any] | None:
        """Moves ``new`` → ``acknowledged``; already-acknowledged and resolved are left as-is.

        Returns the alert for its owning coach, or ``None`` when it does not
        belong to that coach.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'acknowledged', acknowledged_at = ?"
                " WHERE alert_id = ? AND coach_account_id = ? AND state = 'new'",
                (now_iso, str(alert_id), str(coach_account_id)),
            )
            self.catalog_conn.commit()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE alert_id = ? AND coach_account_id = ?",
                (str(alert_id), str(coach_account_id)),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def resolve_coach_alert(
        self, alert_id: str, coach_account_id: str, now_iso: str, resolved_by: str
    ) -> dict[str, Any] | None:
        """Moves ``new``/``acknowledged`` → ``resolved``; already-resolved is left as-is.

        Returns the alert for its owning coach, or ``None`` when it does not
        belong to that coach.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = ?"
                " WHERE alert_id = ? AND coach_account_id = ? AND state IN ('new', 'acknowledged')",
                (now_iso, str(resolved_by), str(alert_id), str(coach_account_id)),
            )
            self.catalog_conn.commit()
            cursor.execute(
                f"SELECT {self._COACH_ALERT_COLUMNS} FROM coach_alerts"
                " WHERE alert_id = ? AND coach_account_id = ?",
                (str(alert_id), str(coach_account_id)),
            )
            return self._coach_alert_from_row(cursor.fetchone())

    def resolve_open_coach_alerts_for_assignment(
        self,
        assignment_id: str,
        now_iso: str,
        kind: str,
        except_dedupe_key: str | None = None,
    ) -> int:
        """Auto-resolves open alerts of one kind when their dedupe key is no longer current.

        With ``except_dedupe_key`` set, only alerts for a different key are
        resolved, so a continuing fact's alert is updated rather than closed.
        Scoping to ``kind`` keeps resolutions from crossing alert kinds.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = 'system'"
                " WHERE assignment_id = ? AND kind = ? AND state IN ('new', 'acknowledged')"
                " AND (? IS NULL OR dedupe_key != ?)",
                (now_iso, str(assignment_id), str(kind), except_dedupe_key, except_dedupe_key),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    def resolve_open_coach_alerts_for_dedupe(
        self, assignment_id: str, kind: str, dedupe_key: str, now_iso: str
    ) -> int:
        """Auto-resolves the open alert for one exact dedupe key (ADR 032).

        Used by a progression episode close: each exercise's alert carries its own
        ``<subject>:<episode_key>`` dedupe key, so resolving by key closes only
        that episode's alert, never a sibling exercise's.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE coach_alerts SET state = 'resolved', resolved_at = ?, resolved_by = 'system'"
                " WHERE assignment_id = ? AND kind = ? AND dedupe_key = ?"
                " AND state IN ('new', 'acknowledged')",
                (now_iso, str(assignment_id), str(kind), str(dedupe_key)),
            )
            self._commit_catalog()
            return int(cursor.rowcount)

    # ------------------------------------------------------------------
    # Alert signal episodes (ADR 032, ticket #33). Catalog-only transition
    # state so the commit-time evaluator never needs the player ledger.
    # ------------------------------------------------------------------

    _ALERT_SIGNAL_STATE_COLUMNS = "assignment_id, kind, subject, active, episode_key"

    @classmethod
    def _alert_signal_state_from_row(cls, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "assignment_id": str(row[0]),
            "kind": str(row[1]),
            "subject": str(row[2]),
            "active": int(row[3]),
            "episode_key": row[4],
        }

    def get_alert_signal_state(self, assignment_id: str, kind: str, subject: str) -> dict[str, Any] | None:
        """The episode state for one (assignment, kind, subject), or ``None``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ALERT_SIGNAL_STATE_COLUMNS} FROM alert_signal_state"
                " WHERE assignment_id = ? AND kind = ? AND subject = ?",
                (str(assignment_id), str(kind), str(subject)),
            )
            return self._alert_signal_state_from_row(cursor.fetchone())

    def upsert_alert_signal_state(
        self,
        assignment_id: str,
        kind: str,
        subject: str,
        active: int,
        episode_key: str | None,
        now_iso: str,
    ) -> None:
        """Opens, extends, or closes one episode state row."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO alert_signal_state"
                " (assignment_id, kind, subject, active, episode_key, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(assignment_id, kind, subject) DO UPDATE SET"
                " active = excluded.active,"
                " episode_key = excluded.episode_key,"
                " updated_at = excluded.updated_at",
                (str(assignment_id), str(kind), str(subject), int(active), episode_key, now_iso),
            )
            self._commit_catalog()

    def is_progression_session_processed(self, assignment_id: str, session_id: str) -> bool:
        """Whether this session's progression signals were already evaluated (ADR 032)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT 1 FROM progression_alert_sessions"
                " WHERE assignment_id = ? AND session_id = ?",
                (str(assignment_id), str(session_id)),
            )
            return cursor.fetchone() is not None

    def mark_progression_session_processed(
        self, assignment_id: str, session_id: str, now_iso: str
    ) -> None:
        """Records a processed session in the same transaction as its alert changes (ADR 032)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO progression_alert_sessions"
                " (assignment_id, session_id, processed_at) VALUES (?, ?, ?)",
                (str(assignment_id), str(session_id), now_iso),
            )
            self._commit_catalog()

    def upsert_roster_attendance(
        self,
        assignment_id: str,
        current_missed_streak: int,
        now_iso: str,
        timezone: str | None = None,
    ) -> None:
        """Records the latest catalog-side attendance summary for one assignment.

        ``timezone`` is the player's local timezone as of this evaluation; when
        omitted the previously cached value is preserved (absent means UTC).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO roster_attendance"
                " (assignment_id, current_missed_streak, last_evaluated_at, timezone)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(assignment_id) DO UPDATE SET"
                " current_missed_streak = excluded.current_missed_streak,"
                " last_evaluated_at = excluded.last_evaluated_at,"
                " timezone = COALESCE(excluded.timezone, roster_attendance.timezone)",
                (str(assignment_id), int(current_missed_streak), now_iso, timezone),
            )
            self.catalog_conn.commit()

    def get_roster_timezone(self, assignment_id: str) -> str | None:
        """The player's cached timezone for an assignment, or ``None`` when unknown."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT timezone FROM roster_attendance WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None or not str(row[0]).strip():
                return None
            return str(row[0])

    def latest_check_in_on(self, assignment_id: str) -> str | None:
        """The most recent check-in date for an assignment, or ``None`` if never."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT MAX(checked_in_on) FROM check_ins WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def get_roster_alert_badges(self, coach_account_id: str) -> dict[str, dict[str, int]]:
        """New/acknowledged alert counts and streak length per active assignment (catalog-only)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id,"
                " COALESCE(r.current_missed_streak, 0) AS streak,"
                " COALESCE(SUM(CASE WHEN c.state = 'new' THEN 1 ELSE 0 END), 0) AS new_count,"
                " COALESCE(SUM(CASE WHEN c.state = 'acknowledged' THEN 1 ELSE 0 END), 0) AS ack_count"
                " FROM assignments a"
                " LEFT JOIN roster_attendance r ON r.assignment_id = a.assignment_id"
                " LEFT JOIN coach_alerts c ON c.assignment_id = a.assignment_id"
                " AND c.state IN ('new', 'acknowledged')"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " GROUP BY a.assignment_id",
                (str(coach_account_id),),
            )
            return {
                str(row[0]): {
                    "current_missed_streak": int(row[1]),
                    "alerts_new": int(row[2]),
                    "alerts_acknowledged": int(row[3]),
                }
                for row in cursor.fetchall()
            }

    def list_all_active_assignments(self) -> list[dict[str, Any]]:
        """Every active assignment across coaches, for the sweep (catalog-only)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._ASSIGNMENT_COLUMNS} FROM assignments"
                " WHERE status = 'active' ORDER BY started_at ASC",
            )
            return [self._assignment_from_row(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Coach check-ins (ADR 031, ticket #32). Catalog-side immutable facts,
    # keyed by assignment and player so a player keeps their history after
    # unassignment while the former coach loses access at the gate.
    # ------------------------------------------------------------------

    _CHECK_IN_COLUMNS = (
        "check_in_id, assignment_id, coach_account_id, player_account_id,"
        " checked_in_on, channel, note, created_at"
    )

    @staticmethod
    def _check_in_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "check_in_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "checked_in_on": str(row[4]),
            "channel": str(row[5]),
            "note": row[6],
            "created_at": str(row[7]),
        }

    def create_check_in(
        self,
        check_in_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        checked_in_on: str,
        channel: str,
        note: str | None,
        now_iso: str,
    ) -> dict[str, Any]:
        """Inserts one immutable check-in row and returns it."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO check_ins"
                " (check_in_id, assignment_id, coach_account_id, player_account_id,"
                " checked_in_on, channel, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(check_in_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(checked_in_on),
                    str(channel),
                    note,
                    now_iso,
                ),
            )
            self.catalog_conn.commit()
            cursor.execute(
                f"SELECT {self._CHECK_IN_COLUMNS} FROM check_ins WHERE check_in_id = ?",
                (str(check_in_id),),
            )
            return self._check_in_from_row(cursor.fetchone())

    def list_assignment_check_ins(self, assignment_id: str) -> list[dict[str, Any]]:
        """Every check-in for one assignment, newest date first."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._CHECK_IN_COLUMNS} FROM check_ins"
                " WHERE assignment_id = ? ORDER BY checked_in_on DESC, rowid DESC",
                (str(assignment_id),),
            )
            return [self._check_in_from_row(row) for row in cursor.fetchall()]

    def list_player_check_ins(self, player_account_id: str) -> list[dict[str, Any]]:
        """Every check-in the player ever received, across active and ended assignments.

        The coach's current username is joined for display without ever reading
        another player's rows.
        """
        self.ensure_account_schema()
        columns = ", ".join("ci." + column for column in self._CHECK_IN_COLUMNS.split(", "))
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {columns}, acc.username, a.status"
                " FROM check_ins ci"
                " LEFT JOIN accounts acc ON acc.account_id = ci.coach_account_id"
                " LEFT JOIN assignments a ON a.assignment_id = ci.assignment_id"
                " WHERE ci.player_account_id = ?"
                " ORDER BY ci.checked_in_on DESC, ci.rowid DESC",
                (str(player_account_id),),
            )
            rows = []
            for row in cursor.fetchall():
                item = self._check_in_from_row(row)
                item["coach_username"] = str(row[8]) if row[8] else "former coach"
                item["assignment_status"] = str(row[9]) if row[9] else "ended"
                rows.append(item)
            return rows

    def list_roster_follow_up_basis(self, coach_account_id: str) -> dict[str, dict[str, Any]]:
        """Catalog-only follow-up inputs per active assignment for the roster.

        Returns ``assignment_id -> {started_at, timezone, latest_check_in_on}`` so
        the service can compute ``next_follow_up_on`` without mounting a ledger.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id, a.started_at, r.timezone, MAX(ci.checked_in_on)"
                " FROM assignments a"
                " LEFT JOIN roster_attendance r ON r.assignment_id = a.assignment_id"
                " LEFT JOIN check_ins ci ON ci.assignment_id = a.assignment_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " GROUP BY a.assignment_id, a.started_at, r.timezone",
                (str(coach_account_id),),
            )
            return {
                str(row[0]): {
                    "started_at": str(row[1]),
                    "timezone": str(row[2]) if row[2] else None,
                    "latest_check_in_on": str(row[3]) if row[3] else None,
                }
                for row in cursor.fetchall()
            }

    def get_exercise_catalog_entry(self, exercise_id: str) -> dict[str, Any] | None:
        """One catalog exercise by exact id, with the fields needed to swap it into a program."""
        if not isinstance(exercise_id, str) or not exercise_id:
            return None
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path"
                " FROM exercises WHERE id = ?",
                (str(exercise_id),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "body_part": row[2],
            "target_muscle": row[3],
            "equipment": row[4],
            "instructions": row[5],
            "image_path": row[6],
            "gif_path": row[7],
        }

    def save_training_program(
        self, program_data: dict, published_by_coach_account_id: str | None = None
    ) -> str:
        """Persists a new active program, stamping a stable version and provenance.

        ``published_by_coach_account_id`` is ``None`` for player self-service and the
        assigning coach's account id for a coach publication (ADR 026).
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE training_programs SET is_active = 0")
            prog_id = program_data.get("id") or str(uuid.uuid4())
            created_at = program_data.get("created_at") or datetime.now(UTC).isoformat()
            prog_name = program_data.get("program_name") or program_data.get("name", "Custom Program")

            cursor.execute("PRAGMA table_info(training_programs)")
            existing_cols = {col[1] for col in cursor.fetchall()}

            cols = ["id", "weekly_frequency", "split_type", "is_active", "created_at"]
            vals = [
                prog_id,
                program_data.get("weekly_frequency", 4),
                program_data.get("split_type", "custom"),
                1,
                created_at,
            ]

            if "name" in existing_cols:
                cols.append("name")
                vals.append(prog_name)
            if "program_name" in existing_cols:
                cols.append("program_name")
                vals.append(prog_name)
            if "instructions" in existing_cols:
                cols.append("instructions")
                vals.append(program_data.get("instructions", ""))
            if "version" in existing_cols:
                cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM training_programs")
                cols.append("version")
                vals.append(int(cursor.fetchone()[0]))
            if "published_by_coach_account_id" in existing_cols:
                cols.append("published_by_coach_account_id")
                vals.append(published_by_coach_account_id)

            cursor.execute(
                f"INSERT INTO training_programs ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(vals))})", vals
            )

            cursor.execute("PRAGMA table_info(program_days)")
            day_cols = {col[1] for col in cursor.fetchall()}
            cursor.execute("PRAGMA table_info(program_exercises)")
            exercise_cols = {col[1] for col in cursor.fetchall()}

            for day in program_data.get("days", []):
                day_id = day.get("id") or str(uuid.uuid4())
                day_values = {
                    "id": day_id,
                    "program_id": prog_id,
                    "day_name": day["day_name"],
                    "day_order": day["day_order"],
                }
                if "warmup_json" in day_cols:
                    day_values["warmup_json"] = json.dumps(day.get("warmup_exercises", []), ensure_ascii=False)
                if "cardio" in day_cols:
                    day_values["cardio"] = day.get("cardio")
                cursor.execute(
                    f"INSERT INTO program_days ({', '.join(day_values)}) VALUES ({', '.join(['?'] * len(day_values))})",
                    list(day_values.values()),
                )

                for order_idx, ex in enumerate(day.get("exercises", []), start=1):
                    pe_id = ex.get("id") or str(uuid.uuid4())
                    exercise_values = {
                        "id": pe_id,
                        "day_id": day_id,
                        "exercise_id": str(ex["exercise_id"]),
                        "order_in_day": order_idx,
                        "target_sets": ex.get("target_sets", 2),
                        "target_reps_min": ex.get("target_reps_min", 8),
                        "target_reps_max": ex.get("target_reps_max", 12),
                        "target_rpe": ex.get("target_rpe", 8.5),
                        "rest_seconds": ex.get("rest_seconds", 180),
                        "notes": ex.get("notes", ""),
                    }
                    if "slot_key" in exercise_cols:
                        exercise_values["slot_key"] = ex.get("slot_key")
                    if "warmup_sets" in exercise_cols:
                        exercise_values["warmup_sets"] = ex.get("warmup_sets", 0)
                    cursor.execute(
                        f"INSERT INTO program_exercises ({', '.join(exercise_values)}) "
                        f"VALUES ({', '.join(['?'] * len(exercise_values))})",
                        list(exercise_values.values()),
                    )

            self.conn.commit()
            return prog_id
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")

    def _load_program(self, where_sql: str, params: tuple = ()) -> GeneratedProgramSchema | None:
        """Loads one stored program, its days and exercises, by an arbitrary predicate.

        Shared by ``get_active_program`` and ``get_program_by_version`` so the
        historical-program path can never drift from the active one (ADR 034).
        """
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(training_programs)")
        program_cols = {col[1] for col in cursor.fetchall()}
        instructions_expr = "instructions" if "instructions" in program_cols else "'' AS instructions"
        version_expr = "version" if "version" in program_cols else "NULL AS version"
        provenance_expr = (
            "published_by_coach_account_id"
            if "published_by_coach_account_id" in program_cols
            else "NULL AS published_by_coach_account_id"
        )
        created_at_expr = "created_at" if "created_at" in program_cols else "NULL AS created_at"
        cursor.execute(f"""
            SELECT id, COALESCE(program_name, name), weekly_frequency, split_type, {instructions_expr},
                   {version_expr}, {provenance_expr}, {created_at_expr}
            FROM training_programs
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT 1
        """, params)
        row = cursor.fetchone()
        if not row:
            return None

        prog_id, prog_name, freq, split_type, instructions, version, published_by, created_at = row

        cursor.execute("PRAGMA table_info(program_days)")
        day_cols = {col[1] for col in cursor.fetchall()}
        day_extras = ""
        if "warmup_json" in day_cols:
            day_extras += ", warmup_json"
        if "cardio" in day_cols:
            day_extras += ", cardio"
        cursor.execute(
            f"SELECT id, day_name, day_order{day_extras} FROM program_days WHERE program_id = ? ORDER BY day_order ASC",
            (prog_id,),
        )
        days_rows = cursor.fetchall()
        if not days_rows:
            return None

        cursor.execute("PRAGMA table_info(program_exercises)")
        exercise_cols = {col[1] for col in cursor.fetchall()}
        has_slot_key = "slot_key" in exercise_cols
        has_warmup_sets = "warmup_sets" in exercise_cols

        days = []
        try:
            for day_row in days_rows:
                d_id, d_name, d_order = day_row[0], day_row[1], day_row[2]
                warmup_json = day_row[3] if "warmup_json" in day_cols else None
                cardio = day_row[4] if "cardio" in day_cols and len(day_row) > 4 else None

                select_cols = (
                    "pe.exercise_id, e.name, pe.target_sets, pe.target_reps_min, "
                    "pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes, "
                    "e.image_path, e.gif_path"
                )
                if has_slot_key:
                    select_cols += ", pe.slot_key"
                if has_warmup_sets:
                    select_cols += ", pe.warmup_sets"
                cursor.execute(
                    f"""
                    SELECT {select_cols}
                    FROM program_exercises pe
                    JOIN catalog.exercises e ON pe.exercise_id = e.id
                    WHERE pe.day_id = ?
                    ORDER BY pe.order_in_day ASC
                """,
                    (d_id,),
                )
                exercises = []
                for r in cursor.fetchall():
                    exercises.append(
                        ProgramExerciseSchema(
                            exercise_id=str(r[0]),
                            exercise_name=r[1],
                            target_sets=int(r[2]),
                            target_reps_min=int(r[3]),
                            target_reps_max=int(r[4]),
                            target_rpe=float(r[5]) if r[5] is not None else 8.5,
                            rest_seconds=int(r[6]) if r[6] is not None else 180,
                            notes=r[7] or "",
                            image_path=r[8],
                            gif_path=r[9],
                            slot_key=r[10] if has_slot_key else None,
                            warmup_sets=int(r[11]) if has_warmup_sets and r[11] is not None else 0,
                        )
                    )

                warmup_exercises = []
                if warmup_json:
                    try:
                        warmup_exercises = [WarmupExerciseSchema(**item) for item in json.loads(warmup_json)]
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Skipping malformed warm-up block on day '{d_name}': {exc}")

                days.append(
                    ProgramDaySchema(
                        day_name=d_name,
                        day_order=d_order,
                        warmup_exercises=warmup_exercises,
                        exercises=exercises,
                        cardio=cardio,
                    )
                )

            return GeneratedProgramSchema(
                program_name=prog_name,
                weekly_frequency=int(freq),
                split_type=split_type or "custom",
                instructions=instructions or "",
                days=days,
                version=int(version) if version is not None else None,
                published_by_coach_account_id=published_by,
                created_at=created_at,
            )
        except Exception as exc:
            logger.warning(f"Program '{prog_id}' is malformed or incomplete: {exc}")
            return None

    def get_active_program(self) -> GeneratedProgramSchema | None:
        return self._load_program("is_active = 1")

    def get_program_by_version(self, version: int) -> GeneratedProgramSchema | None:
        """The player's program with this stable version, active or historical (ADR 034).

        Publishing a new program only flips ``is_active``; older rows and their
        days/exercises are kept, so an offline draft captured against an older
        version resolves to the exact prescription it trained against.
        """
        return self._load_program("version = ?", (int(version),))

    def update_user_frequency(self, frequency: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET weekly_frequency = ?, updated_at = ? WHERE id = 1",
            (min(max(int(frequency), 1), 5), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def log_workout_session(
        self,
        session_id: str,
        session_date: str,
        split_name: str,
        started_at: str,
        completed_at: str,
        readiness_score: int = 4,
        notes: str = "",
        client_session_id: str | None = None,
        performed_timezone: str | None = None,
        program_version: int | None = None,
        active_program_version_at_sync: int | None = None,
        captured_at: str | None = None,
        uploaded_at: str | None = None,
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO workout_sessions (
                id, session_date, split_name, started_at, completed_at, session_notes, readiness_score,
                client_session_id, performed_timezone, program_version, active_program_version_at_sync,
                captured_at, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_id,
                session_date,
                split_name,
                started_at,
                completed_at,
                notes,
                readiness_score,
                client_session_id,
                performed_timezone,
                program_version,
                active_program_version_at_sync,
                captured_at,
                uploaded_at,
            ),
        )
        self._commit_ledger()

    def log_workout_set(
        self,
        set_id: str,
        session_id: str,
        exercise_id: str,
        set_index: int,
        weight_kg: float,
        reps: int,
        rpe: float,
        is_warmup: int = 0,
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                set_id,
                session_id,
                exercise_id,
                set_index,
                weight_kg,
                reps,
                rpe,
                is_warmup,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def log_workout_sets_batch(self, sets_payload: list[dict[str, Any]]) -> None:
        """Persists all session sets in a single atomic transaction."""
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (:id, :session_id, :exercise_id, :set_index, :weight_kg, :reps, :rpe, :is_warmup, :logged_at)
        """,
            sets_payload,
        )
        self._commit_ledger()

    def get_latest_session_summary(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, session_date, split_name, readiness_score,
                   program_version, active_program_version_at_sync,
                   uploaded_at, edited_at
            FROM workout_sessions
            ORDER BY session_date DESC, started_at DESC, rowid DESC
            LIMIT 1
        """)
        session = cursor.fetchone()
        if session is None:
            return None

        cursor.execute(
            """
            SELECT COALESCE(e.name, ws.exercise_id) AS name,
                   COUNT(*) AS sets, SUM(ws.reps) AS reps,
                   SUM(ws.weight_kg * ws.reps) AS volume_kg
            FROM workout_sets ws
            LEFT JOIN catalog.exercises e ON e.id = ws.exercise_id
            WHERE ws.session_id = ? AND ws.is_warmup = 0
            GROUP BY ws.exercise_id, e.name
            ORDER BY name COLLATE NOCASE, ws.exercise_id
            """,
            (session["id"],),
        )
        exercises = [dict(row) for row in cursor.fetchall()]
        return {
            "session_id": session["id"],
            "session_date": session["session_date"],
            "split_name": session["split_name"],
            "readiness_score": session["readiness_score"],
            "program_version": session["program_version"],
            "active_program_version_at_sync": session["active_program_version_at_sync"],
            "uploaded_at": session["uploaded_at"],
            "edited_at": session["edited_at"],
            "corrections": self.list_performed_date_corrections(session["id"]),
            "sets_count": sum(exercise["sets"] for exercise in exercises),
            "total_volume_kg": sum((exercise["volume_kg"] for exercise in exercises), 0.0),
            "exercises": exercises,
            "divergences": [
                {
                    "kind": row["kind"],
                    "exercise_id": row["exercise_id"],
                    "exercise_name": row["exercise_name"],
                }
                for row in self.list_session_divergences(session["id"])
            ],
        }

    def get_session_program_versions(self) -> dict[str, dict[str, Any]]:
        """Per-session program version and the active version at sync, keyed by session id (ADR 034).

        Kept separate from ``get_session_log`` so the ledger export shape is
        unchanged while the coach history can annotate version differences. The
        derived ``is_historical_program`` flag is computed in the service layer,
        not here.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, program_version, active_program_version_at_sync FROM workout_sessions")
        return {
            row["id"]: {
                "program_version": row["program_version"],
                "active_program_version_at_sync": row["active_program_version_at_sync"],
            }
            for row in cursor.fetchall()
        }

    def list_performed_dates(self) -> list[str]:
        """One local date per committed session, oldest-first, including duplicates.

        Two workouts on the same day are two performed dates so attendance can
        satisfy two expected days, one per workout (ADR 030).
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT session_date FROM workout_sessions ORDER BY session_date ASC")
        return [str(row[0]) for row in cursor.fetchall()]

    def get_session_log(self) -> list[dict[str, Any]]:
        """Chronological session→set rows (exercise names resolved) for ledger export.

        Returns a flat, one-row-per-set list; grouping/nesting happens in the service layer.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT s.id AS session_id, s.session_date, s.split_name, s.readiness_score,
                   s.session_notes, s.started_at, s.completed_at,
                   ws.exercise_id, COALESCE(e.name, ws.exercise_id) AS exercise_name,
                   ws.set_index, ws.weight_kg, ws.reps, ws.rpe, ws.is_warmup, ws.logged_at
            FROM workout_sets ws
            JOIN workout_sessions s ON ws.session_id = s.id
            LEFT JOIN catalog.exercises e ON e.id = ws.exercise_id
            ORDER BY s.session_date ASC, s.started_at ASC, s.rowid ASC, ws.rowid ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def record_session_divergences(
        self, session_id: str, divergences: list[dict[str, Any]], now_iso: str
    ) -> None:
        """Persists the prescribed-vs-performed differences for one session.

        Recording is factual history only and never touches the training program
        (ADR 018/028). An empty batch is accepted and writes nothing. A duplicate
        fact is the same fact, so conflicting inserts are ignored rather than
        failing.
        """
        if not divergences:
            return
        payload = [
            {
                "session_id": session_id,
                "exercise_id": str(divergence["exercise_id"]),
                "exercise_name": divergence["exercise_name"],
                "kind": divergence["kind"],
                "created_at": now_iso,
            }
            for divergence in divergences
        ]
        cursor = self.conn.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO session_divergences (
                session_id, exercise_id, exercise_name, kind, created_at
            ) VALUES (:session_id, :exercise_id, :exercise_name, :kind, :created_at)
        """,
            payload,
        )
        self._commit_ledger()

    def list_session_divergences(self, session_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT session_id, exercise_id, exercise_name, kind, created_at
            FROM session_divergences
            WHERE session_id = ?
            ORDER BY kind ASC, exercise_id ASC
        """,
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_divergences_by_session(self) -> dict[str, list[dict[str, Any]]]:
        """Every session's divergences keyed by session id, in a single query."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT session_id, exercise_id, exercise_name, kind
            FROM session_divergences
            ORDER BY kind ASC, exercise_id ASC
        """)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in cursor.fetchall():
            grouped.setdefault(row["session_id"], []).append(
                {
                    "kind": row["kind"],
                    "exercise_id": row["exercise_id"],
                    "exercise_name": row["exercise_name"],
                }
            )
        return grouped

    @staticmethod
    def _training_schedule_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "schedule_id": str(row["id"]),
            "trainee_id": str(row["trainee_id"]),
            "weekdays": json.loads(row["weekdays"]),
            "timezone": str(row["timezone"]),
            "effective_from": str(row["effective_from"]),
            "created_at": str(row["created_at"]),
        }

    def append_training_schedule(
        self,
        trainee_id: str,
        weekdays: list[int],
        timezone: str,
        effective_from: str,
        now_iso: str,
    ) -> dict[str, Any]:
        """Appends a new effective-dated schedule version; earlier versions are never rewritten."""
        schedule_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO training_schedules"
            " (id, trainee_id, weekdays, timezone, effective_from, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                schedule_id,
                str(trainee_id),
                json.dumps([int(day) for day in weekdays]),
                str(timezone),
                str(effective_from),
                now_iso,
            ),
        )
        self.conn.commit()
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM training_schedules WHERE id = ?", (schedule_id,))
        return self._training_schedule_from_row(cursor.fetchone())

    def _schedule_effective_on(self, trainee_id: str, on_date: str) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM training_schedules
            WHERE trainee_id = ? AND effective_from <= ?
            ORDER BY effective_from DESC, created_at DESC, rowid DESC
            LIMIT 1
        """,
            (str(trainee_id), str(on_date)),
        )
        return self._training_schedule_from_row(cursor.fetchone())

    def get_schedule_effective_on(self, trainee_id: str, on_date: str) -> dict[str, Any] | None:
        """Latest schedule effective on ``on_date`` — attendance for a past date uses it."""
        return self._schedule_effective_on(trainee_id, on_date)

    def list_training_schedules(self, trainee_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_schedules WHERE trainee_id = ?"
            " ORDER BY effective_from ASC, created_at ASC, rowid ASC",
            (str(trainee_id),),
        )
        return [self._training_schedule_from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def _training_pause_from_row(row: Any) -> dict[str, Any]:
        return {
            "pause_id": str(row["id"]),
            "trainee_id": str(row["trainee_id"]),
            "starts_on": str(row["starts_on"]),
            "ends_on": str(row["ends_on"]),
            "created_at": str(row["created_at"]),
        }

    def schedule_training_pause(
        self, trainee_id: str, starts_on: str, ends_on: str, now_iso: str
    ) -> dict[str, Any]:
        """Persists one prospective pause; overlap between pauses is allowed."""
        pause_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO training_pauses (id, trainee_id, starts_on, ends_on, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pause_id, str(trainee_id), str(starts_on), str(ends_on), now_iso),
        )
        self.conn.commit()
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM training_pauses WHERE id = ?", (pause_id,))
        return self._training_pause_from_row(cursor.fetchone())

    def list_training_pauses(self, trainee_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_pauses WHERE trainee_id = ?"
            " ORDER BY starts_on DESC, created_at DESC, rowid DESC",
            (str(trainee_id),),
        )
        return [self._training_pause_from_row(row) for row in cursor.fetchall()]

    def list_active_or_upcoming_training_pauses(
        self, trainee_id: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Pauses still covering or yet to cover ``on_date`` (``ends_on >= on_date``)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_pauses WHERE trainee_id = ? AND ends_on >= ?"
            " ORDER BY starts_on ASC, created_at ASC, rowid ASC",
            (str(trainee_id), str(on_date)),
        )
        return [self._training_pause_from_row(row) for row in cursor.fetchall()]

    def get_last_performance(self, exercise_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT s.id
            FROM workout_sessions s
            JOIN workout_sets ws ON ws.session_id = s.id
            WHERE ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY s.started_at DESC, s.ROWID DESC
            LIMIT 1
        """,
            (exercise_id,),
        )
        session_row = cursor.fetchone()
        if not session_row:
            return []

        cursor.execute(
            """
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe
            FROM workout_sets ws
            WHERE ws.session_id = ? AND ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY ws.set_index ASC
        """,
            (session_row[0], exercise_id),
        )
        return [dict(r) for r in cursor.fetchall()]

    BEST_SET_CONVENTION = "heaviest weight, then most reps, then earliest set_index"
    _SESSION_ORDER = "session_date DESC, started_at DESC, rowid DESC"

    @staticmethod
    def _session_metadata(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_date": row["session_date"],
            "started_at": row["started_at"],
            "split_name": row["split_name"],
            "readiness_score": row["readiness_score"],
            "session_notes": row["session_notes"],
        }

    @staticmethod
    def _aggregate_sets(sets: list[dict[str, Any]]) -> dict[str, Any]:
        if not sets:
            return {
                "sets": [],
                "sets_count": 0,
                "total_reps": 0,
                "volume_kg": 0.0,
                "best_set": None,
                "e1rm": None,
            }
        best = max(sets, key=lambda s: (s["weight_kg"], s["reps"], -s["set_index"]))
        e1rm = None
        if best["rpe"] is not None and best["weight_kg"] > 0:
            from agent.progression_engine import calculate_e1rm

            e1rm = calculate_e1rm(best["weight_kg"], best["reps"], best["rpe"])
        return {
            "sets": [
                {"set_index": s["set_index"], "weight_kg": s["weight_kg"], "reps": s["reps"], "rpe": s["rpe"]}
                for s in sets
            ],
            "sets_count": len(sets),
            "total_reps": sum(s["reps"] for s in sets),
            "volume_kg": sum(s["weight_kg"] * s["reps"] for s in sets),
            "best_set": {
                "set_index": best["set_index"],
                "weight_kg": best["weight_kg"],
                "reps": best["reps"],
                "rpe": best["rpe"],
            },
            "e1rm": e1rm,
        }

    @staticmethod
    def _deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        return {
            "load_kg": current["best_set"]["weight_kg"] - previous["best_set"]["weight_kg"],
            "reps": current["best_set"]["reps"] - previous["best_set"]["reps"],
            "sets": current["sets_count"] - previous["sets_count"],
            "volume_kg": current["volume_kg"] - previous["volume_kg"],
            "e1rm": (current["e1rm"] - previous["e1rm"]) if current["e1rm"] is not None and previous["e1rm"] is not None else None,
        }

    @staticmethod
    def _status(current: dict[str, Any], previous: dict[str, Any]) -> str:
        if current["best_set"]["rpe"] is None or previous["best_set"]["rpe"] is None:
            return "insufficient_data"
        deltas = DatabaseManager._deltas(current, previous)
        signs = {
            (delta > 0) - (delta < 0)
            for key in ("load_kg", "reps", "e1rm")
            if (delta := deltas[key]) is not None
        }
        signs.discard(0)
        if not signs:
            return "unchanged"
        if signs == {1}:
            return "improvement"
        if signs == {-1}:
            return "decline"
        return "mixed"

    def _fetch_session_sets(self, session_id: str, exercise_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe
            FROM workout_sets ws
            WHERE ws.session_id = ? AND ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY ws.set_index ASC
        """,
            (session_id, exercise_id),
        )
        return [dict(r) for r in cursor.fetchall()]

    def _fetch_previous_session_for_exercise(
        self, exercise_id: str, current_session: sqlite3.Row
    ) -> sqlite3.Row | None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT s.id, s.session_date, s.started_at, s.split_name,
                   s.readiness_score, s.session_notes
            FROM workout_sessions s
            WHERE (s.session_date, s.started_at, s.rowid) < (?, ?, ?)
              AND EXISTS (
                  SELECT 1 FROM workout_sets ws
                  WHERE ws.session_id = s.id AND ws.exercise_id = ? AND ws.is_warmup = 0
              )
            ORDER BY s.session_date DESC, s.started_at DESC, s.rowid DESC
            LIMIT 1
            """,
            (current_session["session_date"], current_session["started_at"], current_session["session_rowid"], exercise_id),
        )
        return cursor.fetchone()

    def get_session_comparison_context(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT id, session_date, started_at, split_name, readiness_score,
                   session_notes, rowid AS session_rowid
            FROM workout_sessions ORDER BY {self._SESSION_ORDER} LIMIT 2
        """)
        sessions = cursor.fetchall()
        if not sessions:
            return None
        latest = sessions[0]
        metadata = self._session_metadata(latest)
        prev_metadata = self._session_metadata(sessions[1]) if len(sessions) > 1 else None

        cursor.execute(
            """
            SELECT DISTINCT ws.exercise_id, COALESCE(e.name, ws.exercise_id) AS name
            FROM workout_sets ws
            LEFT JOIN catalog.exercises e ON e.id = ws.exercise_id
            WHERE ws.session_id = ? AND ws.is_warmup = 0
            ORDER BY name COLLATE NOCASE, ws.exercise_id
        """,
            (latest["id"],),
        )
        exercise_rows = cursor.fetchall()

        exercises = []
        for ex_row in exercise_rows:
            exercise_id, name = ex_row["exercise_id"], ex_row["name"]
            current = self._aggregate_sets(self._fetch_session_sets(latest["id"], exercise_id))
            previous_session = self._fetch_previous_session_for_exercise(exercise_id, latest)
            previous = None
            if previous_session is not None:
                previous = self._aggregate_sets(self._fetch_session_sets(previous_session["id"], exercise_id))
                previous["session"] = self._session_metadata(previous_session)

            if previous is None:
                deltas = {"load_kg": None, "reps": None, "sets": None, "volume_kg": None, "e1rm": None}
                status = "insufficient_data"
            else:
                deltas = self._deltas(current, previous)
                status = self._status(current, previous)

            exercises.append(
                {
                    "exercise_id": exercise_id,
                    "name": name,
                    "current": current,
                    "previous": previous,
                    "deltas": deltas,
                    "status": status,
                }
            )

        return {
            "best_set_convention": self.BEST_SET_CONVENTION,
            "session": metadata,
            "previous_session": prev_metadata,
            "exercises": exercises,
        }

    def update_user_persona(self, coach_tone: str, custom_instructions: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE user_profile
            SET coach_tone = ?, custom_instructions = ?, updated_at = ?
            WHERE id = 1
        """,
            (coach_tone.strip(), custom_instructions.strip(), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def swap_program_exercise(
        self, old_exercise_id: str, new_exercise_id: str, new_notes: str = "", day_id: str | None = None
    ) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")
        active_prog = cursor.fetchone()
        if not active_prog:
            return False

        prog_id = active_prog[0]
        if day_id:
            cursor.execute(
                """
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.day_id = ? AND pe.exercise_id = ? LIMIT 1
            """,
                (prog_id, day_id, old_exercise_id),
            )
        else:
            cursor.execute(
                """
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.exercise_id = ? LIMIT 1
            """,
                (prog_id, old_exercise_id),
            )

        row = cursor.fetchone()
        if not row:
            return False

        cursor.execute(
            "UPDATE program_exercises SET exercise_id = ?, notes = ? WHERE id = ?", (new_exercise_id, new_notes, row[0])
        )
        self.conn.commit()
        return True

    def save_session_debrief(self, session_id: str, debrief: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE workout_sessions SET coach_debrief = ? WHERE id = ?", (debrief.strip(), session_id))
        self._commit_ledger()

    def get_session_debrief(self, session_id: str) -> str | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT coach_debrief FROM workout_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def add_chat_message(self, role: str, content: str) -> str:
        cursor = self.conn.cursor()
        msg_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (msg_id, role, content, datetime.now(UTC).isoformat()),
        )
        self._commit_ledger()
        return msg_id

    def get_chat_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        if limit:
            cursor.execute(
                "SELECT id, role, content, created_at FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in reversed(cursor.fetchall())]
        cursor.execute("SELECT id, role, content, created_at FROM chat_history ORDER BY created_at ASC")
        return [dict(r) for r in cursor.fetchall()]

    def clear_chat_history(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM chat_history")
        self.conn.commit()

    def get_compact_telemetry(self) -> str:
        prof = self.get_user_profile() or {}
        gender = prof.get("gender", "male").capitalize()
        age = prof.get("age", "?")
        wt = prof.get("weight_kg", "?")
        ht = prof.get("height_cm", "?")
        props = prof.get("proportions", "balanced").replace("_", " ")
        goal = prof.get("current_goal", "Hypertrophy")
        rep_bias = prof.get("rep_preference", "balanced")

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT program_name, weekly_frequency, split_type
            FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
        """)
        prog_row = cursor.fetchone()
        prog_str = f"{prog_row[0]} ({prog_row[1]}d/wk {prog_row[2]})" if prog_row else "None"

        cursor.execute(
            "SELECT id, session_date, split_name, readiness_score FROM workout_sessions ORDER BY session_date DESC, started_at DESC LIMIT 1"
        )
        last_session = cursor.fetchone()
        if last_session:
            s_id, s_date, s_split, s_readiness = last_session
            cursor.execute(
                """
                SELECT e.name, ws.weight_kg, ws.reps, ws.rpe
                FROM workout_sets ws JOIN catalog.exercises e ON ws.exercise_id = e.id
                WHERE ws.session_id = ? AND ws.is_warmup = 0 ORDER BY ws.weight_kg DESC LIMIT 1
            """,
                (s_id,),
            )
            top_set = cursor.fetchone()
            top_str = f" | Top: {top_set[0]} {top_set[1]}kg x {top_set[2]} @ RPE {top_set[3]}" if top_set else ""
            last_str = f"{s_split} ({s_date}) | Readiness: {s_readiness}/5{top_str}"
        else:
            last_str = "No recorded sessions yet in ledger."

        from agent.progression_engine import (
            evaluate_systemic_fatigue,
            get_progression_signals,
        )

        fatigue_state = evaluate_systemic_fatigue(self)
        if fatigue_state["deload_recommended"]:
            fatigue_line = f"Systemic State: DELOAD RECOMMENDED ({fatigue_state['reason']} | Cap RPE at {fatigue_state['intensity_cap_rpe']})"
        else:
            fatigue_line = (
                f"Systemic State: Recovered (Rolling Readiness: {fatigue_state['recent_readiness_avg'] or 'N/A'}/5)"
            )

        return (
            "[TRAINEE TELEMETRY & SYSTEM STATE]\n"
            f"Trainee: {gender}, {age}yo | {wt}kg @ {ht}cm | Build: {props}\n"
            f"Goal: {goal} | Rep Bias: {rep_bias} | Routine: {prog_str}\n"
            f"Last Session: {last_str}\n"
            f"{get_progression_signals(self)}\n"
            f"{fatigue_line}"
        )

    def find_exercises_by_name(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Ranked catalog name matches: exact → punctuation-insensitive → substring → token-AND.

        Each tier short-circuits: weaker-tier matches are only returned when every stronger
        tier came up empty. The substitution resolver uses this so an explicitly named
        exercise either resolves by name or refuses — it never falls through to semantic
        (embedding) ranking and installs a lexical sibling.
        """
        clean = query.strip().lower()
        if not clean or limit <= 0:
            return []

        columns = "id, name, body_part, target_muscle, equipment"
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _collect(row: sqlite3.Row | tuple | None) -> None:
            if row is None:
                return
            match_id = str(row[0])
            if match_id in seen:
                return
            seen.add(match_id)
            matches.append(
                {
                    "id": match_id,
                    "name": row[1],
                    "body_part": row[2],
                    "target_muscle": row[3],
                    "equipment": row[4],
                }
            )

        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(f"SELECT {columns} FROM exercises WHERE LOWER(name) = ? LIMIT ?", (clean, limit))
            for row in cursor.fetchall():
                _collect(row)
            if matches:
                return matches

            normalized = _normalize_exercise_name(clean)
            if normalized:
                cursor.execute(f"SELECT {columns} FROM exercises")
                normalized_rows = [row for row in cursor.fetchall() if _normalize_exercise_name(row[1]) == normalized]
                normalized_rows.sort(key=lambda row: len(row[1] or ""))
                for row in normalized_rows[:limit]:
                    _collect(row)
                if matches:
                    return matches

            cursor.execute(
                f"SELECT {columns} FROM exercises WHERE LOWER(name) LIKE ? ORDER BY LENGTH(name) ASC LIMIT ?",
                (f"%{clean}%", limit),
            )
            for row in cursor.fetchall():
                _collect(row)
            if matches:
                return matches

            tokens = [t for t in re.split(r"\s+", clean) if len(t) > 2]
            if tokens:
                where_clauses = ["LOWER(name) LIKE ?" for _ in tokens]
                cursor.execute(
                    f"SELECT {columns} FROM exercises WHERE {' AND '.join(where_clauses)}"
                    " ORDER BY LENGTH(name) ASC LIMIT ?",
                    [*[f"%{t}%" for t in tokens], limit],
                )
                for row in cursor.fetchall():
                    _collect(row)

        return matches

    def find_exercise_by_name(self, query: str) -> dict[str, Any] | None:
        """Best catalog name match (exact → punctuation-insensitive → substring → token-AND)."""
        matches = self.find_exercises_by_name(query, limit=1)
        return matches[0] if matches else None
