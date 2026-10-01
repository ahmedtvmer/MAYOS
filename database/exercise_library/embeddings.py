"""Semantic index maintenance for Exercise library rows."""

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlite_vec
from database.schema.definitions import EMBEDDING_DIM

MAYOS_EXERCISE_ID_PREFIX = "mayos:"
MAYOS_VECTOR_ID_SIGN = -1


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
    match = re.fullmatch(rf"{re.escape(MAYOS_EXERCISE_ID_PREFIX)}(\d+)", exercise_id)
    if match:
        return MAYOS_VECTOR_ID_SIGN * int(match.group(1))
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


def exercise_id_for_vector_sql(vector_id_sql: str) -> str:
    """SQL counterpart to vector_id, sharing the MAYOS prefix and sign rule."""
    return (
        f"CASE WHEN {vector_id_sql} * {MAYOS_VECTOR_ID_SIGN} > 0 "
        f"THEN '{MAYOS_EXERCISE_ID_PREFIX}' || CAST({vector_id_sql} * "
        f"{MAYOS_VECTOR_ID_SIGN} AS TEXT) ELSE CAST({vector_id_sql} AS TEXT) END"
    )


def sync_exercise_embeddings(
    cursor, exercise_rows: Sequence[Mapping[str, Any]]
) -> None:
    """Compute vectors only for new or semantically changed Exercise library rows."""
    changed: list[tuple[str, int, str]] = []
    backfill: list[tuple[str, str]] = []
    existing_vector_ids = {
        int(row[0]) for row in cursor.execute("SELECT exercise_id FROM vec_exercises")
    }
    for exercise in exercise_rows:
        exercise_id = str(exercise["id"])
        text = semantic_text(
            exercise["name"], exercise["target_muscle"], exercise["equipment"],
            exercise["instructions"],
        )
        previous = cursor.execute(
            "SELECT semantic_text FROM exercise_embedding_sources WHERE exercise_id = ?",
            (exercise_id,),
        ).fetchone()
        index_id = vector_id(exercise_id)
        if index_id is None:
            backfill.append((exercise_id, text))
            continue
        if previous is None:
            if index_id in existing_vector_ids:
                backfill.append((exercise_id, text))
            else:
                changed.append((exercise_id, index_id, text))
        elif previous[0] != text:
            changed.append((exercise_id, index_id, text))
    cursor.executemany(
        "INSERT INTO exercise_embedding_sources (exercise_id, semantic_text) VALUES (?, ?) "
        "ON CONFLICT(exercise_id) DO UPDATE SET semantic_text = excluded.semantic_text",
        backfill,
    )
    if not changed:
        return

    model = _load_embedding_model()
    for exercise_id, index_id, text in changed:
        vector = model.embed_query(text)
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(f"Exercise embeddings must contain {EMBEDDING_DIM} values.")
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
