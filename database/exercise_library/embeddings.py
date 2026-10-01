"""Semantic index maintenance for Exercise library rows."""

import os
import re
from typing import Any

import sqlite_vec


def _load_embedding_model():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        model_kwargs={"device": os.getenv("MODEL_DEVICE", "cpu")},
        encode_kwargs={"normalize_embeddings": True},
    )


def semantic_text(name: str, target: str, equipment: str, instructions: str | None) -> str:
    return (
        f"Exercise: {name}. Target: {target}. Equipment: {equipment}. "
        f"Instructions: {instructions or ''}"
    )


def vector_id(exercise_id: str) -> int | None:
    """Map ExerciseDB positive ids and MAYOS negative ids into vec0's integer key."""
    match = re.fullmatch(r"mayos:(\d+)", exercise_id)
    if match:
        return -int(match.group(1))
    try:
        numeric_id = int(exercise_id)
    except ValueError:
        # Some tests and imported historical rows have opaque IDs. They remain
        # available to name search and detail, while vec0 indexes its numeric ID
        # domains (ExerciseDB and MAYOS) only.
        return None
    if numeric_id <= 0:
        raise ValueError(f"ExerciseDB id must be positive: {exercise_id}")
    return numeric_id


def sync_exercise_embeddings(cursor, exercise_rows: list[tuple[Any, ...]]) -> None:
    """Compute vectors only for new or semantically changed Exercise library rows."""
    changed: list[tuple[str, int, str]] = []
    for row in exercise_rows:
        exercise_id, name, _body_part, target, equipment, _image, _gif, instructions = row
        text = semantic_text(name, target, equipment, instructions)
        previous = cursor.execute(
            "SELECT semantic_text FROM exercise_embedding_sources WHERE exercise_id = ?",
            (exercise_id,),
        ).fetchone()
        index_id = vector_id(exercise_id)
        if index_id is None:
            cursor.execute(
                "INSERT INTO exercise_embedding_sources (exercise_id, semantic_text) "
                "VALUES (?, ?) ON CONFLICT(exercise_id) DO UPDATE SET semantic_text = excluded.semantic_text",
                (exercise_id, text),
            )
            continue
        if previous is None:
            changed.append((exercise_id, index_id, text))
        elif previous[0] != text:
            changed.append((exercise_id, index_id, text))
    if not changed:
        return

    model = _load_embedding_model()
    for exercise_id, index_id, text in changed:
        vector = model.embed_query(text)
        if len(vector) != 384:
            raise ValueError("Exercise embeddings must contain 384 values.")
        cursor.execute("DELETE FROM vec_exercises WHERE exercise_id = ?", (index_id,))
        cursor.execute(
            "INSERT INTO vec_exercises (exercise_id, embedding) VALUES (?, ?)",
            (index_id, sqlite_vec.serialize_float32(vector)),
        )
        cursor.execute(
            "INSERT INTO exercise_embedding_sources (exercise_id, semantic_text) VALUES (?, ?) "
            "ON CONFLICT(exercise_id) DO UPDATE SET semantic_text = excluded.semantic_text",
            (exercise_id, text),
        )
