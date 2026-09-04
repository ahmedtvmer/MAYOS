import sqlite3
import sqlite_vec
import pandas as pd
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone

# Resolve the absolute path to the project root (/mnt/work/MAYOS)
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
DEFAULT_DB_PATH = BASE_DIR / "db" / "myos.db"
DEFAULT_CSV_PATH = BASE_DIR / "data" / "processed_exercises.csv"
from utils.logger import MyosLogger

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
        self.conn.commit()

    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH):
        self.create_schema()

        cursor = self.conn.cursor()
        
        # 2. Check if exercises are already populated
        cursor.execute("SELECT COUNT(*) FROM exercises")
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Database already contains {count} exercises. Skipping CSV seed.")
            return

        # 3. Load CSV and populate tables
        logger.info("Seeding database from CSV...")

        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            logger.error(f"Error: {csv_path} not found. Run dataset_handler.py first.")
            return

        # 1. Seed Core Exercises (instructions are already clean)
        core_df = df[['id', 'name', 'bodyPart', 'target', 'equipment', 'image_path', 'gif_path', 'instructions']].copy()
        core_df.rename(columns={'bodyPart': 'body_part', 'target': 'target_muscle'}, inplace=True)
        core_df.to_sql('exercises', self.conn, if_exists='append', index=False)

        # 2. Process Secondary Muscles using Pandas melt
        muscle_cols = [c for c in df.columns if c.startswith('secondaryMuscles/')]
        muscles_df = df.melt(id_vars=['id'], value_vars=muscle_cols, value_name='muscle')
        
        muscles_df = muscles_df.dropna(subset=['muscle'])
        muscles_df = muscles_df[['id', 'muscle']].rename(columns={'id': 'exercise_id'})
        
        muscles_df.to_sql('exercise_secondary_muscles', self.conn, if_exists='append', index=False)

        self.conn.commit()
        logger.info("Myos database initialized and seeded successfully.")

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
        Inserts or updates the single-user profile using the validated schema dictionary.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.cursor()

        cursor.execute("DELETE FROM user_profile")

        cursor.execute("""
            INSERT INTO user_profile (
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
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_data.get("proportions", "balanced"),
            profile_data.get("age", 25),
            profile_data.get("weight_kg", 75.0),
            profile_data.get("height_cm", 175.0),
            profile_data.get("rep_preference", "balanced"),
            profile_data.get("current_goal", "hypertrophy"),
            profile_data.get("long_term_goal", "progressive overload"),
            min(max(profile_data.get("weekly_frequency", 4), 1), 5), # hard-clamped to max 5 for program generator
            profile_data.get("training_age_years", 1.0),
            profile_data.get("equipment_access", "commercial gym"),
            profile_data.get("injuries_or_limitations", "None"),
            profile_data.get("stress_and_sleep", "normal"),
            now
        ))
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
