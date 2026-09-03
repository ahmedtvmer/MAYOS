import sys
import os
import struct
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv
from pathlib import Path
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

Embedding = os.getenv("EMBEDDING_MODEL")

logger = MyosLogger().get_logger(__name__)

def serialize_f32(vector: list[float]) -> bytes:
    """sqlite-vec requires embeddings serialized as raw f32 bytes."""
    return struct.pack(f"{len(vector)}f", *vector)

def seed_exercise_embeddings():
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()

    logger.info("Loading embedding model...")
    embeddings = HuggingFaceEmbeddings(
        model_name=Embedding,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True} 
    )

    cursor.execute("SELECT id, name, target_muscle, equipment, instructions FROM exercises")
    rows = cursor.fetchall()
    logger.info(f"Generating 384-d embeddings for {len(rows)} exercises...")

    batch_data = []
    for ex_id, name, target, equipment, instructions in rows:
        # BGE models perform best when instructions/descriptions are structured clearly
        semantic_text = (
            f"Exercise: {name}. Target: {target}. "
            f"Equipment: {equipment}. Instructions: {instructions}"
        )
        vector = embeddings.embed_query(semantic_text)
        batch_data.append((int(ex_id), serialize_f32(vector)))

    cursor.execute("DELETE FROM vec_exercises")
    cursor.executemany(
        "INSERT INTO vec_exercises (exercise_id, embedding) VALUES (?, ?)",
        batch_data
    )
    conn.commit()
    logger.info("Successfully seeded vec_exercises.")

if __name__ == "__main__":
    seed_exercise_embeddings()