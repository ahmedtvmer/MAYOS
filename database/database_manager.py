import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import sqlite3
import sqlite_vec
from typing import Optional
import threading

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

DEFAULT_CATALOG_PATH = BASE_DIR / "db" / "catalog.db"
DEFAULT_USERS_DIR = BASE_DIR / "db" / "users"
DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"

from utils.logger import MyosLogger
from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema
)

logger = MyosLogger().get_logger(__name__)

class DatabaseManager:
    _instance = None
    EMBEDDING_DIM = 384

    _lock: threading.Lock = threading.Lock()

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
        # Handle secondary calls across modules: switch user if explicitly requested
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
            
            # Initial user resolution
            initial_user = self._sanitize_username(active_user) if active_user else "default"
            self.active_user = initial_user or "default"

            os.makedirs(self.catalog_path.parent, exist_ok=True)
            os.makedirs(self.users_dir, exist_ok=True)

            # 1. Shared Vector Catalog Connection
            self.catalog_conn = sqlite3.connect(self.catalog_path, check_same_thread=False)
            self.catalog_conn.execute("PRAGMA foreign_keys = ON;")
            self.catalog_conn.enable_load_extension(True)
            sqlite_vec.load(self.catalog_conn)
            self.catalog_conn.enable_load_extension(False)

            # 2. Mount Active User Database
            self.user_conn: Optional[sqlite3.Connection] = None
            self.switch_user(self.active_user)

            self._initialized = True
            logger.info(f"DatabaseManager initialized with catalog and user ledger ({self.active_user}).")

    @property
    def conn(self) -> sqlite3.Connection:
        """Dynamic alias ensuring queries always hit the current active user ledger."""
        if self.user_conn is None:
            raise RuntimeError(f"No active database connection mounted for user '{self.active_user}'.")
        return self.user_conn
    @staticmethod
    def _sanitize_username(username: str) -> str:
        clean = re.sub(r"[^\w\-]", "", str(username).strip().lower())
        return clean or "default"

    def switch_user(self, username: str) -> bool:
        """Swaps the active user database and attaches the shared catalog."""
        sanitized = self._sanitize_username(username)
        if not sanitized:
            return False

        # 1. Idempotency Guard: Avoid tearing down healthy connections on Streamlit reruns
        if self.user_conn is not None and self.active_user == sanitized:
            return True

        # 2. Commit and safely terminate prior user connection
        if self.user_conn:
            try:
                self.user_conn.commit()
                self.user_conn.close()
            except Exception as e:
                logger.warning(f"Error closing active connection for {self.active_user}: {e}")

        self.active_user = sanitized
        user_db_path = self.users_dir / f"{sanitized}.db"

        # 3. Establish connection with WAL mode and foreign key enforcement
        self.user_conn = sqlite3.connect(user_db_path, check_same_thread=False)
        self.user_conn.row_factory = sqlite3.Row
        self.user_conn.execute("PRAGMA foreign_keys = ON;")
        self.user_conn.execute("PRAGMA journal_mode = WAL;")

        # 4. Load sqlite-vec extension directly into user connection for vector joins
        try:
            self.user_conn.enable_load_extension(True)
            sqlite_vec.load(self.user_conn)
            self.user_conn.enable_load_extension(False)
        except Exception as e:
            logger.warning(f"Failed to load sqlite_vec into user connection: {e}")

        # 5. Attach shared catalog as a read-only database
        escaped_catalog_path = str(self.catalog_path.resolve()).replace("'", "''")
        self.user_conn.execute(f"ATTACH DATABASE '{escaped_catalog_path}' AS catalog;")
        self.user_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercises AS SELECT * FROM catalog.exercises;")
        self.user_conn.execute("CREATE TEMP VIEW IF NOT EXISTS exercise_secondary_muscles AS SELECT * FROM catalog.exercise_secondary_muscles;")

        self.create_user_schema()
        logger.info(f"Active user context switched to: {sanitized}")
        return True
    
    def user_exists(self, username: str) -> bool:
        sanitized = self._sanitize_username(username)
        if not sanitized:
            return False
        return (self.users_dir / f"{sanitized}.db").is_file()
    
    def get_connection(self):
        return self.conn

    def create_catalog_schema(self) -> None:
        """Initializes the master catalog tables and vector index."""
        cursor = self.catalog_conn.cursor()
        cursor.executescript("""
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
        """)

        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_exercises USING vec0(
                exercise_id INTEGER PRIMARY KEY,
                embedding float[{self.EMBEDDING_DIM}] distance_metric=cosine
            );
        """)
        self.catalog_conn.commit()

    def create_user_schema(self) -> None:
        """Initializes trainee-specific tables inside the active user database."""
        cursor = self.user_conn.cursor()
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

            CREATE INDEX IF NOT EXISTS idx_sets_session ON workout_sets(session_id);
            CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(session_date);
        """)
        self.user_conn.commit()
    
    def create_schema(self) -> None:
        """Backward-compatible wrapper to initialize both catalog and user schemas."""
        self.create_catalog_schema()
        self.create_user_schema()
        
    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH):
        self.create_schema()

        cursor = self.catalog_conn.cursor()
        
        # Check if exercises are already populated
        cursor.execute("SELECT COUNT(*) FROM exercises")
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Database already contains {count} exercises. Skipping CSV seed.")
            return

        # Load CSV and populate tables
        logger.info("Seeding database from CSV...")

        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            logger.error(f"Error: {csv_path} not found. Run dataset_handler.py first.")
            return

        # 1. Clean and Seed Core Exercises
        core_df = df[['id', 'name', 'bodyPart', 'target', 'equipment', 'image_path', 'gif_path', 'instructions']].copy()
        core_df.rename(columns={'bodyPart': 'body_part', 'target': 'target_muscle'}, inplace=True)
        
        # Clean naming artifacts: replace leading 'lever ' with 'machine ' and drop 'v. 2'
        core_df['name'] = (
            core_df['name']
            .astype(str)
            .str.replace(r"^lever\s+", "machine ", regex=True, flags=re.IGNORECASE)
            .str.replace(r"\s+v\.\s*\d+", "", regex=True, flags=re.IGNORECASE)
            .str.strip()
        )

        # WRITE TO catalog_conn (NOT self.conn / user_conn)
        core_df.to_sql('exercises', self.catalog_conn, if_exists='append', index=False)

        # 2. Process Secondary Muscles using Pandas melt
        muscle_cols = [c for c in df.columns if c.startswith('secondaryMuscles/')]
        muscles_df = df.melt(id_vars=['id'], value_vars=muscle_cols, value_name='muscle')
        
        muscles_df = muscles_df.dropna(subset=['muscle'])
        muscles_df = muscles_df[['id', 'muscle']].rename(columns={'id': 'exercise_id'})
        
        # WRITE TO catalog_conn (NOT self.conn / user_conn)
        muscles_df.to_sql('exercise_secondary_muscles', self.catalog_conn, if_exists='append', index=False)

        self.catalog_conn.commit()
        logger.info("Myos database initialized and seeded successfully with sanitized exercise names.")

    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict]:
        """
        Queries vec_exercises using cosine similarity and joins with 
        relational exercise details.
        """
        cursor = self.catalog_conn.cursor()
        serialized_vector = sqlite_vec.serialize_float32(query_vector)

        query = """
            WITH knn_matches AS (
                SELECT exercise_id, distance
                FROM vec_exercises
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT 
                e.id,
                e.name,
                e.body_part,
                e.target_muscle,
                e.equipment,
                e.instructions,
                m.distance
            FROM knn_matches m
            JOIN exercises e ON CAST(e.id AS INTEGER) = m.exercise_id
            ORDER BY m.distance ASC;
        """
        
        cursor.execute(query, (serialized_vector, limit))
        rows = cursor.fetchall()

        # Return clean dictionaries ready for the agent to reason over
        columns = ["id", "name", "body_part", "target_muscle", "equipment", "instructions", "distance"]
        return [dict(zip(columns, row)) for row in rows]

    def get_user_profile(self, user_id: int = 1) -> dict | None:
        """
        Retrieves a user profile by user_id as a dictionary, 
        or None if unseeded.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

    def upsert_user_profile(self, profile_data: dict, user_id: int = 1) -> None:
        """
        Upserts a user profile row identified by user_id using named parameters.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.cursor()

        # Check for column presence
        for col_def in [
            ("gender", "TEXT DEFAULT 'male'"),
            ("rep_preference", "TEXT DEFAULT 'balanced'")
        ]:
            try:
                cursor.execute(f"ALTER TABLE user_profile ADD COLUMN {col_def[0]} {col_def[1]}")
                self.conn.commit()
            except Exception:
                pass

        target_user_id = int(profile_data.get("id", user_id))

        params = {
            "id": target_user_id,
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
                id,
                gender,
                proportions,
                age,
                weight_kg,
                height_cm,
                rep_preference,
                current_goal,
                long_term_goal,
                weekly_frequency,
                training_age_years,
                equipment_access,
                injuries_or_limitations,
                stress_and_sleep,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :gender,
                :proportions,
                :age,
                :weight_kg,
                :height_cm,
                :rep_preference,
                :current_goal,
                :long_term_goal,
                :weekly_frequency,
                :training_age_years,
                :equipment_access,
                :injuries_or_limitations,
                :stress_and_sleep,
                :created_at,
                :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                gender = excluded.gender,
                proportions = excluded.proportions,
                age = excluded.age,
                weight_kg = excluded.weight_kg,
                height_cm = excluded.height_cm,
                rep_preference = excluded.rep_preference,
                current_goal = excluded.current_goal,
                long_term_goal = excluded.long_term_goal,
                weekly_frequency = excluded.weekly_frequency,
                training_age_years = excluded.training_age_years,
                equipment_access = excluded.equipment_access,
                injuries_or_limitations = excluded.injuries_or_limitations,
                stress_and_sleep = excluded.stress_and_sleep,
                updated_at = excluded.updated_at
        """, params)

        self.conn.commit()

    def clear_user_profile(self, user_id: int = 1) -> None:
        """
        Clears the user profile row for a given user_id.
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM user_profile WHERE id = ?", (user_id,))
        self.conn.commit()

    def save_training_program(self, program_data: dict) -> str:
        """Deactivates all previous programs and commits the newest routine to SQLite."""
        cursor = self.conn.cursor()
        try:
            # 1. Deactivate prior programs
            cursor.execute("UPDATE training_programs SET is_active = 0")

            prog_id = program_data.get("id") or str(uuid.uuid4())
            created_at = program_data.get("created_at") or datetime.now(timezone.utc).isoformat()
            prog_name = program_data.get("program_name") or program_data.get("name", "Custom Program")

            # 2. Inspect table columns to satisfy legacy 'name' NOT NULL constraints
            cursor.execute("PRAGMA table_info(training_programs)")
            existing_cols = {col[1] for col in cursor.fetchall()}

            cols = ["id", "weekly_frequency", "split_type", "is_active", "created_at"]
            vals = [
                prog_id,
                program_data.get("weekly_frequency", 4),
                program_data.get("split_type", "custom"),
                1,
                created_at
            ]

            # Populate both legacy 'name' and new 'program_name' columns if present
            if "name" in existing_cols:
                cols.append("name")
                vals.append(prog_name)
            if "program_name" in existing_cols:
                cols.append("program_name")
                vals.append(prog_name)

            col_clause = ", ".join(cols)
            val_placeholders = ", ".join(["?"] * len(vals))

            cursor.execute(
                f"INSERT INTO training_programs ({col_clause}) VALUES ({val_placeholders})",
                vals
            )

            # 3. Commit Program Days and Program Exercises
            for day in program_data.get("days", []):
                day_id = day.get("id") or str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO program_days (id, program_id, day_name, day_order)
                    VALUES (?, ?, ?, ?)
                """, (
                    day_id,
                    prog_id,
                    day["day_name"],
                    day["day_order"]
                ))

                for order_idx, ex in enumerate(day.get("exercises", []), start=1):
                    pe_id = ex.get("id") or str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO program_exercises (
                            id, day_id, exercise_id, order_in_day,
                            target_sets, target_reps_min, target_reps_max,
                            target_rpe, rest_seconds, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pe_id,
                        day_id,
                        str(ex["exercise_id"]),
                        order_idx,
                        ex.get("target_sets", 3),
                        ex.get("target_reps_min", 8),
                        ex.get("target_reps_max", 12),
                        ex.get("target_rpe", 8.5),
                        ex.get("rest_seconds", 120),
                        ex.get("notes", "")
                    ))

            self.conn.commit()
            return prog_id

        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")
    
    def get_active_program(self) -> Optional[GeneratedProgramSchema]:
        """Retrieves the newest active training program with backwards-compatible column selection."""
        cursor = self.conn.cursor()

        # Check existing columns to safely select name
        cursor.execute("PRAGMA table_info(training_programs)")
        existing_cols = {col[1] for col in cursor.fetchall()}
        
        if "program_name" in existing_cols and "name" in existing_cols:
            name_selector = "COALESCE(program_name, name)"
        elif "program_name" in existing_cols:
            name_selector = "program_name"
        else:
            name_selector = "name"

        cursor.execute(f"""
            SELECT id, {name_selector}, weekly_frequency, split_type 
            FROM training_programs 
            WHERE is_active = 1 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None

        prog_id, prog_name, freq, split_type = row

        cursor.execute("""
            SELECT id, day_name, day_order 
            FROM program_days 
            WHERE program_id = ? 
            ORDER BY day_order ASC
        """, (prog_id,))
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
            ex_rows = cursor.fetchall()

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
                ) for r in ex_rows
            ]

            days.append(ProgramDaySchema(
                day_name=d_name,
                day_order=d_order,
                exercises=exercises
            ))

        return GeneratedProgramSchema(
            program_name=prog_name,
            weekly_frequency=int(freq),
            split_type=split_type or "custom",
            days=days
        )
    
    def update_user_frequency(self, frequency: int) -> None:
        """Updates the active user's weekly training frequency in SQLite."""
        clamped = min(max(int(frequency), 1), 5)
        cursor = self.conn.cursor()
        cursor.execute("UPDATE user_profile SET weekly_frequency = ?, updated_at = ? WHERE id = 1", 
                       (clamped, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def log_workout_session(
        self,
        session_id: str,
        session_date: str,
        split_name: str,
        started_at: str,
        completed_at: str,
        readiness_score: int = 4,
        notes: str = ""
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO workout_sessions (
                id, session_date, split_name, started_at, completed_at, session_notes, readiness_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, session_date, split_name, started_at, completed_at, notes, readiness_score))
        self.conn.commit()

    def log_workout_set(
        self,
        set_id: str,
        session_id: str,
        exercise_id: str,
        set_index: int,
        weight_kg: float,
        reps: int,
        rpe: float,
        is_warmup: int = 0
    ) -> None:
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (set_id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, now))
        self.conn.commit()

    def get_last_performance(self, exercise_id: str) -> list[dict]:
        """Fetches sets from the most recent session for this exercise."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ws.set_index, ws.weight_kg, ws.reps, ws.rpe, ws.is_warmup, s.session_date
            FROM workout_sets ws
            JOIN workout_sessions s ON ws.session_id = s.id
            WHERE ws.exercise_id = ? AND ws.is_warmup = 0
            ORDER BY s.session_date DESC, ws.set_index ASC
            LIMIT 10
        """, (exercise_id,))
        rows = cursor.fetchall()
        if not rows:
            return []
        
        last_date = rows[0][5]
        return [
            {"set_index": r[0], "weight_kg": r[1], "reps": r[2], "rpe": r[3]}
            for r in rows if r[5] == last_date
        ]

    def update_user_persona(self, coach_tone: str, custom_instructions: str) -> None:
        """Updates the trainee's customized agent behavioral directives."""
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            UPDATE user_profile 
            SET coach_tone = ?, custom_instructions = ?, updated_at = ?
            WHERE id = 1
        """, (coach_tone.strip(), custom_instructions.strip(), now))
        self.conn.commit()

    def swap_program_exercise(
        self, 
        old_exercise_id: str, 
        new_exercise_id: str, 
        new_notes: str = "",
        day_id: str | None = None
    ) -> bool:
        """
        Swaps an exercise in the active program without regenerating the split.
        If day_id is None, swaps the first occurrence found in the active routine.
        """
        cursor = self.conn.cursor()
        
        # 1. Verify the active program exists
        cursor.execute("""
            SELECT id FROM training_programs 
            WHERE is_active = 1 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        active_prog = cursor.fetchone()
        if not active_prog:
            return False
            
        prog_id = active_prog[0]

        # 2. Locate matching program_exercises record
        if day_id:
            cursor.execute("""
                SELECT pe.id 
                FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.day_id = ? AND pe.exercise_id = ?
                LIMIT 1
            """, (prog_id, day_id, old_exercise_id))
        else:
            cursor.execute("""
                SELECT pe.id 
                FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.exercise_id = ?
                LIMIT 1
            """, (prog_id, old_exercise_id))

        row = cursor.fetchone()
        if not row:
            return False

        pe_id = row[0]

        # 3. Update the record in place
        cursor.execute("""
            UPDATE program_exercises 
            SET exercise_id = ?, notes = ?
            WHERE id = ?
        """, (new_exercise_id, new_notes, pe_id))
        
        self.conn.commit()
        return True

    def save_session_debrief(self, session_id: str, debrief: str) -> None:
        """Persists the post-session coach debrief to the workout_sessions record."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE workout_sessions 
            SET coach_debrief = ? 
            WHERE id = ?
        """, (debrief.strip(), session_id))
        self.conn.commit()

    def get_session_debrief(self, session_id: str) -> str | None:
        """Retrieves a previously stored debrief for a session."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT coach_debrief FROM workout_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return row[0] if row else None

