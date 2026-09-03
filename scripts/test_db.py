import sys
import os
import uuid
from datetime import datetime, timezone
import sqlite_vec
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROCESSED_PATH = BASE_DIR / "data" / "processed_exercises.csv"
DB_PATH = BASE_DIR / "db" / "myos.db"

from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

def run_tests():
    logger.info("Initializing DatabaseManager singleton...")
    db = DatabaseManager(db_path=DB_PATH)
    conn = db.get_connection()
    cursor = conn.cursor()

    # 1. Test sqlite-vec extension
    vec_version = cursor.execute("SELECT vec_version()").fetchone()[0]
    logger.info(f"sqlite-vec loaded successfully: version {vec_version}")

    # 2. Run schema initialization and dataset seeding
    logger.info("Running initialize_and_seed()...")
    db.initialize_and_seed(csv_path=DEFAULT_PROCESSED_PATH)

    # 3. Verify row counts in relational tables
    cursor.execute("SELECT COUNT(*) FROM exercises")
    exercise_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM exercise_secondary_muscles")
    muscles_count = cursor.fetchone()[0]

    assert exercise_count > 0, "Failed: exercises table is empty."
    assert muscles_count > 0, "Failed: exercise_secondary_muscles table is empty."
    logger.info(f"Verification passed: {exercise_count} exercises and {muscles_count} muscle mappings loaded.")

    # 4. Verify foreign keys and cascade delete
    logger.info("Testing foreign key constraints and cascade deletes...")
    test_session_id = str(uuid.uuid4())
    test_set_id = str(uuid.uuid4())
    sample_exercise_id = cursor.execute("SELECT id FROM exercises LIMIT 1").fetchone()[0]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert test session
    cursor.execute("""
        INSERT INTO workout_sessions (id, session_date, split_name, started_at)
        VALUES (?, '2026-09-03', 'Lower', ?)
    """, (test_session_id, now_iso))

    # Insert test set referencing the session and sample exercise
    cursor.execute("""
        INSERT INTO workout_sets (id, session_id, exercise_id, set_index, weight_kg, reps, logged_at)
        VALUES (?, ?, ?, 1, 100.0, 8, ?)
    """, (test_set_id, test_session_id, sample_exercise_id, now_iso))
    conn.commit()

    # Delete session and verify set is cascade-deleted
    cursor.execute("DELETE FROM workout_sessions WHERE id = ?", (test_session_id,))
    conn.commit()

    remaining_sets = cursor.execute("SELECT COUNT(*) FROM workout_sets WHERE id = ?", (test_set_id,)).fetchone()[0]
    assert remaining_sets == 0, "Failed: ON DELETE CASCADE failed. Foreign key enforcement is OFF."
    logger.info("Verification passed: Cascade deletes function properly.")

    # 5. Test vector insert and KNN search in vec_exercises
    logger.info("Testing dummy vector insert and KNN query...")
    dummy_vec = [0.05] * db.EMBEDDING_DIM
    serialized_vec = sqlite_vec.serialize_float32(dummy_vec)
    test_vec_id = 999999

    cursor.execute("INSERT OR REPLACE INTO vec_exercises (exercise_id, embedding) VALUES (?, ?)", (test_vec_id, serialized_vec))
    conn.commit()

    # Query closest match
    result = cursor.execute("""
        SELECT exercise_id, distance 
        FROM vec_exercises 
        WHERE embedding MATCH ? 
        ORDER BY distance 
        LIMIT 1
    """, (serialized_vec,)).fetchone()

    assert result is not None and result[0] == test_vec_id, "Failed: Vector KNN query failed."
    cursor.execute("DELETE FROM vec_exercises WHERE exercise_id = ?", (test_vec_id,))
    conn.commit()
    logger.info("Verification passed: sqlite-vec inserted and queried dense vector correctly.")

    logger.info("All DatabaseManager checks passed successfully.")

if __name__ == "__main__":
    run_tests()