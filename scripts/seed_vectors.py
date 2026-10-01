import sys
from pathlib import Path


from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
# pyrefly: ignore [missing-import]
from database.database_manager import DatabaseManager
from database.exercise_library.embeddings import sync_exercise_embeddings
from database.exercise_library.schema import EXERCISE_COLUMNS
from database.schema.definitions import EMBEDDING_DIM

# pyrefly: ignore [missing-import]
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def seed_exercise_embeddings():
    db = DatabaseManager()
    cursor = db.catalog_conn.cursor()

    cursor.execute(
        "SELECT id, name, body_part, target_muscle, equipment, image_path, gif_path, instructions "
        "FROM exercises"
    )
    rows = cursor.fetchall()
    logger.info(f"Generating {EMBEDDING_DIM}-d embeddings for {len(rows)} exercises...")
    cursor.execute("DELETE FROM vec_exercises")
    cursor.execute("DELETE FROM exercise_embedding_sources")
    sync_exercise_embeddings(
        cursor,
        [dict(zip(EXERCISE_COLUMNS, row, strict=True)) for row in rows],
    )
    db.catalog_conn.commit()
    logger.info("Successfully seeded vec_exercises.")


if __name__ == "__main__":
    seed_exercise_embeddings()
