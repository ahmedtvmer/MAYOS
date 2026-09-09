import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import sqlite3
import pandas as pd
import sqlite_vec

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

DEFAULT_CATALOG_PATH = BASE_DIR / "db" / "catalog.db"
DEFAULT_USERS_DIR = BASE_DIR / "db" / "users"
DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"

from utils.logger import MyosLogger
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

logger = MyosLogger().get_logger(__name__)

class DatabaseManager:
    _instance = None
    EMBEDDING_DIM = 384
    _lock: threading.Lock = threading.Lock()
    _local: threading.local = threading.local()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self, 
        catalog_path=DEFAULT_CATALOG_PATH, 
        users_dir=DEFAULT_USERS_DIR, 
        active_user: Optional[str] = None
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

            self.catalog_path = Path(catalog_path)
            self.users_dir = Path(users_dir)
            self._default_user = self._sanitize_username(active_user) if active_user else "default"
            self._catalog_lock = threading.Lock()

            os.makedirs(self.catalog_path.parent, exist_ok=True)
            os.makedirs(self.users_dir, exist_ok=True)

            self.catalog_conn = sqlite3.connect(self.catalog_path, check_same_thread=False)
            self.catalog_conn.execute("PRAGMA foreign_keys = ON;")
            self.catalog_conn.enable_load_extension(True)
            sqlite_vec.load(self.catalog_conn)
            self.catalog_conn.enable_load_extension(False)

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
    def user_conn(self) -> Optional[sqlite3.Connection]:
        return getattr(self._local, "user_conn", None)

    @user_conn.setter
    def user_conn(self, val: Optional[sqlite3.Connection]):
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

        escaped_path = str(self.catalog_path.resolve()).replace("'", "''")
        new_conn.execute(f"ATTACH DATABASE '{escaped_path}' AS catalog;")
        new_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercises AS SELECT * FROM catalog.exercises;")
        new_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercise_secondary_muscles AS SELECT * FROM catalog.exercise_secondary_muscles;")

        self.user_conn = new_conn
        self.create_user_schema()
        return True
    
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
            CREATE TABLE IF NOT EXISTS training_programs (
                id TEXT PRIMARY KEY,
                program_name TEXT NOT NULL,
                name TEXT NOT NULL,
                split_type TEXT NOT NULL,
                weekly_frequency INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS program_days (
                id TEXT PRIMARY KEY,
                program_id TEXT NOT NULL,
                day_name TEXT NOT NULL,
                day_order INTEGER NOT NULL,
                FOREIGN KEY(program_id) REFERENCES training_programs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS program_exercises (
                id TEXT PRIMARY KEY,
                day_id TEXT NOT NULL,
                exercise_id TEXT NOT NULL,
                order_in_day INTEGER NOT NULL,
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
                coach_debrief TEXT
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
            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                role TEXT CHECK(role IN ('user', 'assistant', 'system')) NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_history(created_at);
            CREATE INDEX IF NOT EXISTS idx_sets_session ON workout_sets(session_id);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(session_date);

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
        """)
        self.conn.commit()

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

            core_df = df[['id', 'name', 'bodyPart', 'target', 'equipment', 'image_path', 'gif_path', 'instructions']].copy()
            core_df.rename(columns={'bodyPart': 'body_part', 'target': 'target_muscle'}, inplace=True)
            core_df['name'] = (
                core_df['name']
                .astype(str)
                .str.replace(r"^lever\s+", "machine ", regex=True, flags=re.IGNORECASE)
                .str.replace(r"\s+v\.\s*\d+", "", regex=True, flags=re.IGNORECASE)
                .str.strip()
            )
            core_df.to_sql('exercises', self.catalog_conn, if_exists='append', index=False)

            muscle_cols = [c for c in df.columns if c.startswith('secondaryMuscles/')]
            muscles_df = df.melt(id_vars=['id'], value_vars=muscle_cols, value_name='muscle').dropna(subset=['muscle'])
            muscles_df = muscles_df[['id', 'muscle']].rename(columns={'id': 'exercise_id'})
            muscles_df.to_sql('exercise_secondary_muscles', self.catalog_conn, if_exists='append', index=False)
            self.catalog_conn.commit()

    EXCLUDED_BIOMECHANICAL_PATTERNS = ("behind neck", "behind the neck", "upright row")

    def search_similar_exercises(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
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

    def get_user_profile(self, user_id: int = 1) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def upsert_user_profile(self, profile_data: dict, user_id: int = 1) -> None:
        now = datetime.now(timezone.utc).isoformat()
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
            "updated_at": now
        }
        cursor.execute("""
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
        """, params)
        self.conn.commit()

    def clear_user_profile(self, user_id: int = 1) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM user_profile WHERE id = ?", (user_id,))
        self.conn.commit()

    def save_training_program(self, program_data: dict) -> str:
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE training_programs SET is_active = 0")
            prog_id = program_data.get("id") or str(uuid.uuid4())
            created_at = program_data.get("created_at") or datetime.now(timezone.utc).isoformat()
            prog_name = program_data.get("program_name") or program_data.get("name", "Custom Program")

            cursor.execute("PRAGMA table_info(training_programs)")
            existing_cols = {col[1] for col in cursor.fetchall()}

            cols = ["id", "weekly_frequency", "split_type", "is_active", "created_at"]
            vals = [prog_id, program_data.get("weekly_frequency", 4), program_data.get("split_type", "custom"), 1, created_at]

            if "name" in existing_cols:
                cols.append("name")
                vals.append(prog_name)
            if "program_name" in existing_cols:
                cols.append("program_name")
                vals.append(prog_name)

            cursor.execute(
                f"INSERT INTO training_programs ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(vals))})",
                vals
            )

            for day in program_data.get("days", []):
                day_id = day.get("id") or str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO program_days (id, program_id, day_name, day_order) VALUES (?, ?, ?, ?)",
                    (day_id, prog_id, day["day_name"], day["day_order"])
                )

                for order_idx, ex in enumerate(day.get("exercises", []), start=1):
                    pe_id = ex.get("id") or str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO program_exercises (
                            id, day_id, exercise_id, order_in_day, target_sets,
                            target_reps_min, target_reps_max, target_rpe, rest_seconds, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pe_id, day_id, str(ex["exercise_id"]), order_idx,
                        ex.get("target_sets", 3), ex.get("target_reps_min", 8),
                        ex.get("target_reps_max", 12), ex.get("target_rpe", 8.5),
                        ex.get("rest_seconds", 120), ex.get("notes", "")
                    ))

            self.conn.commit()
            return prog_id
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")

    def get_active_program(self) -> Optional[GeneratedProgramSchema]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, COALESCE(program_name, name), weekly_frequency, split_type 
            FROM training_programs 
            WHERE is_active = 1 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None

        prog_id, prog_name, freq, split_type = row
        cursor.execute("SELECT id, day_name, day_order FROM program_days WHERE program_id = ? ORDER BY day_order ASC", (prog_id,))
        days_rows = cursor.fetchall()

        days = []
        for d_id, d_name, d_order in days_rows:
            cursor.execute("""
                SELECT pe.exercise_id, e.name, pe.target_sets, pe.target_reps_min, 
                       pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes,
                       e.image_path, e.gif_path
                FROM program_exercises pe
                JOIN catalog.exercises e ON pe.exercise_id = e.id
                WHERE pe.day_id = ?
                ORDER BY pe.order_in_day ASC
            """, (d_id,))
            exercises = [
                ProgramExerciseSchema(
                    exercise_id=str(r[0]),
                    exercise_name=r[1],
                    target_sets=int(r[2]),
                    target_reps_min=int(r[3]),
                    target_reps_max=int(r[4]),
                    target_rpe=float(r[5]) if r[5] is not None else 8.5,
                    rest_seconds=int(r[6]) if r[6] is not None else 120,
                    notes=r[7] or "",
                    image_path=r[8],
                    gif_path=r[9]
                ) for r in cursor.fetchall()
            ]
            days.append(ProgramDaySchema(day_name=d_name, day_order=d_order, exercises=exercises))

        return GeneratedProgramSchema(
            program_name=prog_name,
            weekly_frequency=int(freq),
            split_type=split_type or "custom",
            days=days
        )

    def update_user_frequency(self, frequency: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET weekly_frequency = ?, updated_at = ? WHERE id = 1",
            (min(max(int(frequency), 1), 5), datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()

    def log_workout_session(
        self, session_id: str, session_date: str, split_name: str,
        started_at: str, completed_at: str, readiness_score: int = 4, notes: str = ""
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO workout_sessions (
                id, session_date, split_name, started_at, completed_at, session_notes, readiness_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, session_date, split_name, started_at, completed_at, notes, readiness_score))
        self.conn.commit()

    def log_workout_set(
        self, set_id: str, session_id: str, exercise_id: str,
        set_index: int, weight_kg: float, reps: int, rpe: float, is_warmup: int = 0
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (set_id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def log_workout_sets_batch(self, sets_payload: List[Dict[str, Any]]) -> None:
        """Persists all session sets in a single atomic transaction."""
        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (:id, :session_id, :exercise_id, :set_index, :weight_kg, :reps, :rpe, :is_warmup, :logged_at)
        """, sets_payload)
        self.conn.commit()

    def get_last_performance(self, exercise_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT s.id
            FROM workout_sessions s
            JOIN workout_sets ws ON ws.session_id = s.id
            WHERE ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY s.started_at DESC, s.ROWID DESC
            LIMIT 1
        """, (exercise_id,))
        session_row = cursor.fetchone()
        if not session_row:
            return []

        cursor.execute("""
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe
            FROM workout_sets ws
            WHERE ws.session_id = ? AND ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY ws.set_index ASC
        """, (session_row[0], exercise_id))
        return [dict(r) for r in cursor.fetchall()]

    def update_user_persona(self, coach_tone: str, custom_instructions: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE user_profile 
            SET coach_tone = ?, custom_instructions = ?, updated_at = ?
            WHERE id = 1
        """, (coach_tone.strip(), custom_instructions.strip(), datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def swap_program_exercise(
        self, old_exercise_id: str, new_exercise_id: str, new_notes: str = "", day_id: Optional[str] = None
    ) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")
        active_prog = cursor.fetchone()
        if not active_prog:
            return False

        prog_id = active_prog[0]
        if day_id:
            cursor.execute("""
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.day_id = ? AND pe.exercise_id = ? LIMIT 1
            """, (prog_id, day_id, old_exercise_id))
        else:
            cursor.execute("""
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.exercise_id = ? LIMIT 1
            """, (prog_id, old_exercise_id))

        row = cursor.fetchone()
        if not row:
            return False

        cursor.execute("UPDATE program_exercises SET exercise_id = ?, notes = ? WHERE id = ?", (new_exercise_id, new_notes, row[0]))
        self.conn.commit()
        return True

    def save_session_debrief(self, session_id: str, debrief: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE workout_sessions SET coach_debrief = ? WHERE id = ?", (debrief.strip(), session_id))
        self.conn.commit()

    def get_session_debrief(self, session_id: str) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT coach_debrief FROM workout_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def add_chat_message(self, role: str, content: str) -> str:
        cursor = self.conn.cursor()
        msg_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (msg_id, role, content, datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()
        return msg_id

    def get_chat_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        if limit:
            cursor.execute("SELECT id, role, content, created_at FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,))
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

        cursor.execute("SELECT id, session_date, split_name, readiness_score FROM workout_sessions ORDER BY session_date DESC, started_at DESC LIMIT 1")
        last_session = cursor.fetchone()
        if last_session:
            s_id, s_date, s_split, s_readiness = last_session
            cursor.execute("""
                SELECT e.name, ws.weight_kg, ws.reps, ws.rpe
                FROM workout_sets ws JOIN catalog.exercises e ON ws.exercise_id = e.id
                WHERE ws.session_id = ? AND ws.is_warmup = 0 ORDER BY ws.weight_kg DESC LIMIT 1
            """, (s_id,))
            top_set = cursor.fetchone()
            top_str = f" | Top: {top_set[0]} {top_set[1]}kg x {top_set[2]} @ RPE {top_set[3]}" if top_set else ""
            last_str = f"{s_split} ({s_date}) | Readiness: {s_readiness}/5{top_str}"
        else:
            last_str = "No recorded sessions yet in ledger."

        from agent.progression_engine import evaluate_systemic_fatigue, get_progression_signals
        fatigue_state = evaluate_systemic_fatigue(self)
        if fatigue_state["deload_recommended"]:
            fatigue_line = f"Systemic State: DELOAD RECOMMENDED ({fatigue_state['reason']} | Cap RPE at {fatigue_state['intensity_cap_rpe']})"
        else:
            fatigue_line = f"Systemic State: Recovered (Rolling Readiness: {fatigue_state['recent_readiness_avg'] or 'N/A'}/5)"

        return (
            "[TRAINEE TELEMETRY & SYSTEM STATE]\n"
            f"Trainee: {gender}, {age}yo | {wt}kg @ {ht}cm | Build: {props}\n"
            f"Goal: {goal} | Rep Bias: {rep_bias} | Routine: {prog_str}\n"
            f"Last Session: {last_str}\n"
            f"{get_progression_signals(self)}\n"
            f"{fatigue_line}"
        )

    def find_exercise_by_name(self, query: str) -> Optional[Dict[str, Any]]:
        clean = query.strip().lower()
        if not clean:
            return None

        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT id, name, body_part, target_muscle, equipment FROM exercises WHERE LOWER(name) = ? LIMIT 1", (clean,))
            row = cursor.fetchone()
            if row:
                return {"id": str(row[0]), "name": row[1], "body_part": row[2], "target_muscle": row[3], "equipment": row[4]}

            cursor.execute("SELECT id, name, body_part, target_muscle, equipment FROM exercises WHERE LOWER(name) LIKE ? ORDER BY LENGTH(name) ASC LIMIT 1", (f"%{clean}%",))
            row = cursor.fetchone()
            if row:
                return {"id": str(row[0]), "name": row[1], "body_part": row[2], "target_muscle": row[3], "equipment": row[4]}

            tokens = [t for t in re.split(r"\s+", clean) if len(t) > 2]
            if tokens:
                where_clauses = ["LOWER(name) LIKE ?" for _ in tokens]
                cursor.execute(
                    f"SELECT id, name, body_part, target_muscle, equipment FROM exercises WHERE {' AND '.join(where_clauses)} ORDER BY LENGTH(name) ASC LIMIT 1",
                    [f"%{t}%" for t in tokens]
                )
                row = cursor.fetchone()
                if row:
                    return {"id": str(row[0]), "name": row[1], "body_part": row[2], "target_muscle": row[3], "equipment": row[4]}

            return None