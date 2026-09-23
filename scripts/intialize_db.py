import argparse
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_USERS_DIR,
    DatabaseManager,
)
from utils.logger import MyosLogger  # noqa: E402

DEFAULT_PROCESSED_PATH = BASE_DIR / "data" / "processed_exercises.csv"

logger = MyosLogger().get_logger(__name__)


def resolve_csv_path() -> Path:
    """Resolve the catalog seed CSV.

    Defaults to the real processed catalog CSV the operator supplies to the
    build. ``SEED_CSV_PATH`` is the only override and exists for deliberate
    input; there is no silent fallback to a test fixture.
    """
    override = os.getenv("SEED_CSV_PATH", "").strip()
    return Path(override) if override else DEFAULT_PROCESSED_PATH


def require_csv_path() -> Path:
    """Resolve the seed CSV and fail clearly before any database work."""
    csv_path = resolve_csv_path()
    if not csv_path.is_file():
        raise SystemExit(
            f"error: catalog seed CSV not found at '{csv_path}'.\n"
            "Provide the real processed exercise catalog at that path, or set "
            "SEED_CSV_PATH deliberately for a local self-test. There is no silent "
            "fallback to any test fixture."
        )
    return csv_path


def seed_only(csv_path: Path) -> None:
    """Seed schema + relational catalog data onto the configured data root.

    This is the production one-time path: it honors ``MAYOS_DATA_DIR`` (via the
    ``DEFAULT_*`` paths) and writes no test ledgers or throwaway rows.
    """
    logger.info("Seeding catalog on data root '%s' from '%s'...", DEFAULT_CATALOG_PATH.parent, csv_path)
    db = DatabaseManager(
        catalog_path=DEFAULT_CATALOG_PATH,
        users_dir=DEFAULT_USERS_DIR,
        backups_dir=DEFAULT_BACKUPS_DIR,
    )
    try:
        db.initialize_and_seed(csv_path=csv_path)
        exercise_count = db.catalog_conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
        muscles_count = db.catalog_conn.execute("SELECT COUNT(*) FROM exercise_secondary_muscles").fetchone()[0]
        if exercise_count <= 0:
            raise SystemExit("error: catalog seed produced zero exercises; check SEED_CSV_PATH.")
        logger.info("Catalog seed complete: %s exercises, %s muscle mappings.", exercise_count, muscles_count)
        print(f"Catalog seed complete: {exercise_count} exercises, {muscles_count} muscle mappings.")
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def run_tests(csv_path: Path) -> None:
    logger.info("Initializing DatabaseManager singleton...")
    db = DatabaseManager(catalog_path=DEFAULT_CATALOG_PATH, users_dir=DEFAULT_USERS_DIR, active_user="test_user")

    cat_cursor = db.catalog_conn.cursor()
    user_cursor = db.user_conn.cursor()

    # 1. Test sqlite-vec extension on catalog_conn
    vec_version = cat_cursor.execute("SELECT vec_version()").fetchone()[0]
    logger.info(f"sqlite-vec loaded successfully: version {vec_version}")

    # 2. Run schema initialization and dataset seeding
    logger.info("Running initialize_and_seed()...")
    db.initialize_and_seed(csv_path=csv_path)

    # 3. Verify row counts in catalog tables
    cat_cursor.execute("SELECT COUNT(*) FROM exercises")
    exercise_count = cat_cursor.fetchone()[0]
    cat_cursor.execute("SELECT COUNT(*) FROM exercise_secondary_muscles")
    muscles_count = cat_cursor.fetchone()[0]

    assert exercise_count > 0, "Failed: exercises table is empty."
    assert muscles_count > 0, "Failed: exercise_secondary_muscles table is empty."
    logger.info(f"Verification passed: {exercise_count} exercises and {muscles_count} muscle mappings loaded.")

    # 4. Verify foreign keys and cascade delete in user_conn
    logger.info("Testing foreign key constraints and cascade deletes on user ledger...")
    test_session_id = str(uuid.uuid4())
    test_set_id = str(uuid.uuid4())

    # Query sample exercise ID via transparent view on user_conn
    sample_exercise_id = user_cursor.execute("SELECT id FROM exercises LIMIT 1").fetchone()[0]
    now_iso = datetime.now(UTC).isoformat()

    # Insert test session into user ledger
    user_cursor.execute(
        """
        INSERT INTO workout_sessions (id, session_date, split_name, started_at)
        VALUES (?, '2026-09-03', 'Lower', ?)
    """,
        (test_session_id, now_iso),
    )

    # Insert test set referencing the session and sample exercise
    user_cursor.execute(
        """
        INSERT INTO workout_sets (id, session_id, exercise_id, set_index, weight_kg, reps, logged_at)
        VALUES (?, ?, ?, 1, 100.0, 8, ?)
    """,
        (test_set_id, test_session_id, sample_exercise_id, now_iso),
    )
    db.user_conn.commit()

    # Delete session and verify set is cascade-deleted
    user_cursor.execute("DELETE FROM workout_sessions WHERE id = ?", (test_session_id,))
    db.user_conn.commit()

    remaining_sets = user_cursor.execute("SELECT COUNT(*) FROM workout_sets WHERE id = ?", (test_set_id,)).fetchone()[0]
    assert remaining_sets == 0, "Failed: ON DELETE CASCADE failed. Foreign key enforcement is OFF."
    logger.info("Verification passed: Cascade deletes function properly on user ledger.")

    # 5. Test vector insert and KNN search in vec_exercises
    logger.info("Testing dummy vector insert and KNN query on catalog...")
    dummy_vec = [0.05] * db.EMBEDDING_DIM
    serialized_vec = sqlite_vec.serialize_float32(dummy_vec)
    test_vec_id = 999999

    cat_cursor.execute(
        "INSERT OR REPLACE INTO vec_exercises (exercise_id, embedding) VALUES (?, ?)", (test_vec_id, serialized_vec)
    )
    db.catalog_conn.commit()

    result = cat_cursor.execute(
        """
        SELECT exercise_id, distance
        FROM vec_exercises
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT 1
    """,
        (serialized_vec,),
    ).fetchone()

    assert result is not None and result[0] == test_vec_id, "Failed: Vector KNN query failed."
    cat_cursor.execute("DELETE FROM vec_exercises WHERE exercise_id = ?", (test_vec_id,))
    db.catalog_conn.commit()
    logger.info("Verification passed: sqlite-vec inserted and queried dense vector correctly.")

    logger.info("All DatabaseManager checks passed successfully.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize/seed the MAYOS catalog on the configured data root.")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Production seed: schema + CSV data only, without the local self-test writes.",
    )
    args = parser.parse_args(argv)

    csv_path = require_csv_path()
    if args.seed_only:
        seed_only(csv_path)
    else:
        run_tests(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
