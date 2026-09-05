import sqlite3
import sqlite_vec
import pandas as pd
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone
import re

# Resolve the absolute path to the project root (/mnt/work/MAYOS)
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
DEFAULT_DB_PATH = BASE_DIR / "db" / "myos.db"
DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"
from utils.logger import MyosLogger
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

logger = MyosLogger().get_logger(__name__)

class DatabaseManager:
    _instance = None
    EMBEDDING_DIM = 384

    def __new__(cls, db_path=DEFAULT_DB_PATH):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance.db_path = db_path
            
            # Ensure the db directory exists before connecting
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            
            cls._instance.conn = sqlite3.connect(db_path, check_same_thread=False)

            # Enable foreign key support
            cls._instance.conn.execute("PRAGMA foreign_keys = ON;")

            # Load sqlite-vec extension
            cls._instance.conn.enable_load_extension(True)
            sqlite_vec.load(cls._instance.conn)
            cls._instance.conn.enable_load_extension(False)

            
            logger.info("SQLite connection established with sqlite-vec extension loaded.")

        return cls._instance

    def get_connection(self):
        return self.conn

    def create_schema(self):
        cursor = self.conn.cursor()
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

        CREATE TABLE IF NOT EXISTS training_programs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            split_type TEXT NOT NULL,       -- 'Upper/Lower', 'PPL', 'Full Body'
            weekly_frequency INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1,    -- Only one active program at a time
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS program_days (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL,
            day_name TEXT NOT NULL,          -- 'Upper A', 'Lower A', 'Push', etc.
            day_order INTEGER NOT NULL,      -- 1, 2, 3, 4
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
            FOREIGN KEY(day_id) REFERENCES program_days(id) ON DELETE CASCADE,
            FOREIGN KEY(exercise_id) REFERENCES exercises(id)
        );

        CREATE INDEX IF NOT EXISTS idx_program_days_prog ON program_days(program_id);
        CREATE INDEX IF NOT EXISTS idx_program_ex_day ON program_exercises(day_id);

        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workout_sessions (
            id TEXT PRIMARY KEY,
            session_date TEXT NOT NULL,
            split_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            session_notes TEXT,
            readiness_score INTEGER CHECK(readiness_score BETWEEN 1 AND 5)
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
            FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(exercise_id) REFERENCES exercises(id)
        );

        CREATE INDEX IF NOT EXISTS idx_sets_session ON workout_sets(session_id);
        CREATE INDEX IF NOT EXISTS idx_sets_exercise ON workout_sets(exercise_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(session_date);
        """)

        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_exercises USING vec0(
                exercise_id INTEGER PRIMARY KEY,
                embedding float[{self.EMBEDDING_DIM}] distance_metric=cosine
        );
        """)
        
        # Safe column migrations for existing SQLite databases
        try:
            cursor.execute("ALTER TABLE user_profile ADD COLUMN gender TEXT DEFAULT 'male'")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE user_profile ADD COLUMN rep_preference TEXT DEFAULT 'balanced'")
        except Exception:
            pass

        self.conn.commit()

    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH):
        self.create_schema()

        cursor = self.conn.cursor()
        
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

        core_df.to_sql('exercises', self.conn, if_exists='append', index=False)

        # 2. Process Secondary Muscles using Pandas melt
        muscle_cols = [c for c in df.columns if c.startswith('secondaryMuscles/')]
        muscles_df = df.melt(id_vars=['id'], value_vars=muscle_cols, value_name='muscle')
        
        muscles_df = muscles_df.dropna(subset=['muscle'])
        muscles_df = muscles_df[['id', 'muscle']].rename(columns={'id': 'exercise_id'})
        
        muscles_df.to_sql('exercise_secondary_muscles', self.conn, if_exists='append', index=False)

        self.conn.commit()
        logger.info("Myos database initialized and seeded successfully with sanitized exercise names.")

    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict]:
        """
        Queries vec_exercises using cosine similarity and joins with 
        relational exercise details.
        """
        cursor = self.conn.cursor()
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

    def get_user_profile(self) -> dict | None:
        """Retrieves the single-user profile as a dictionary, or None if unseeded."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

    def upsert_user_profile(self, profile_data: dict) -> None:
        """
        Upserts the singleton user profile row (id = 1) using named parameters.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.cursor()

        # Ensure columns exist if working from an existing database file
        for col_def in [
            ("gender", "TEXT DEFAULT 'male'"),
            ("rep_preference", "TEXT DEFAULT 'balanced'")
        ]:
            try:
                cursor.execute(f"ALTER TABLE user_profile ADD COLUMN {col_def[0]} {col_def[1]}")
                self.conn.commit()
            except Exception:
                pass

        params = {
            "id": 1,
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

    def clear_user_profile(self) -> None:
        """Clears the singleton user profile row."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM user_profile WHERE id = 1")
        self.conn.commit()

    def save_training_program(self, program_data: dict) -> str:
        """
        Persists a generated program, its days, and its exercise prescriptions into SQLite.
        Deactivates any existing active program.
        """
        now = datetime.now(timezone.utc).isoformat()
        program_id = str(uuid.uuid4())
        cursor = self.conn.cursor()

        try:
            # Set prior programs as inactive
            cursor.execute("UPDATE training_programs SET is_active = 0 WHERE is_active = 1")

            # 1. Insert Master Program
            cursor.execute("""
                INSERT INTO training_programs (id, name, split_type, weekly_frequency, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (
                program_id,
                program_data["program_name"],
                program_data["split_type"],
                program_data["weekly_frequency"],
                now
            ))

            # 2. Insert Days & Exercises
            for day in program_data["days"]:
                day_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO program_days (id, program_id, day_name, day_order)
                    VALUES (?, ?, ?, ?)
                """, (day_id, program_id, day["day_name"], day["day_order"]))

                for idx, ex in enumerate(day["exercises"], start=1):
                    ex_entry_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO program_exercises (
                            id, day_id, exercise_id, order_in_day,
                            target_sets, target_reps_min, target_reps_max,
                            target_rpe, rest_seconds, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ex_entry_id, day_id, ex["exercise_id"], idx,
                        ex["target_sets"], ex["target_reps_min"], ex["target_reps_max"],
                        ex.get("target_rpe", 8.5), ex.get("rest_seconds", 120),
                        ex.get("notes", "")
                    ))

            self.conn.commit()
            return program_id
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")

    def get_active_program(self) -> GeneratedProgramSchema | None:
        """Hydrates the active training program directly from SQLite without LLM synthesis."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, split_type, weekly_frequency FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")
        prog_row = cursor.fetchone()
        if not prog_row:
            return None

        prog_id, name, split_type, weekly_freq = prog_row

        # Fetch days
        cursor.execute("SELECT id, day_name, day_order FROM program_days WHERE program_id = ? ORDER BY day_order ASC", (prog_id,))
        day_rows = cursor.fetchall()

        days = []
        for d_id, d_name, d_order in day_rows:
            cursor.execute("""
                SELECT pe.exercise_id, e.name, pe.target_sets, pe.target_reps_min, 
                       pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes, 
                       e.image_path, e.gif_path
                FROM program_exercises pe
                JOIN exercises e ON pe.exercise_id = e.id
                WHERE pe.day_id = ?
                ORDER BY pe.order_in_day ASC
            """, (d_id,))
            ex_rows = cursor.fetchall()

            exercises = [
                ProgramExerciseSchema(
                    exercise_id=str(r[0]),
                    exercise_name=r[1],
                    target_sets=r[2],
                    target_reps_min=r[3],
                    target_reps_max=r[4],
                    target_rpe=r[5] or 8.5,
                    rest_seconds=r[6] or 120,
                    notes=r[7],
                    image_path=r[8],
                    gif_path=r[9]
                )
                for r in ex_rows
            ]
            days.append(ProgramDaySchema(day_name=d_name, day_order=d_order, exercises=exercises))

        return GeneratedProgramSchema(
            program_name=name,
            split_type=split_type,
            weekly_frequency=weekly_freq,
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


