"""Exercise library upserts and curated names (ADR 053, #225)."""

import re

import pandas as pd
from database.shared import DEFAULT_CSV_PATH
from database.exercise_library.names import apply_curated_exercise_names
from database.exercise_library.schema import EXERCISE_COLUMNS

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


class ExerciseSeedingMixin:
    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH) -> None:
        # The catalog schema only: any per-ledger schema is created by
        # ``open_ledger`` when a handle is actually opened (ADR 041).
        self.create_catalog_schema()
        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            logger.error(f"Error: {csv_path} not found.")
            return

        logger.info("Upserting exercise library from CSV...")
        exercise_rows, muscle_rows = _exercise_seed_rows(df)
        with self._catalog_lock, self.catalog_conn:
            cursor = self.catalog_conn.cursor()
            _upsert_exercise_rows(cursor, exercise_rows)
            _replace_secondary_muscles(cursor, exercise_rows, muscle_rows)
            apply_curated_exercise_names(cursor)

    EXCLUDED_BIOMECHANICAL_PATTERNS = ("behind neck", "behind the neck", "upright row")


def _sqlite_value(value, *, column: str | None = None):
    if pd.isna(value):
        return None
    value = value.item() if hasattr(value, "item") else value
    return str(value) if column == "id" else value


def _exercise_seed_rows(df):
    exercises = df[
        ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
    ].copy()
    exercises.rename(columns={"bodyPart": "body_part", "target": "target_muscle"}, inplace=True)
    exercises["name"] = (
        exercises["name"]
        .astype(str)
        .str.replace(r"^lever\s+", "machine ", regex=True, flags=re.IGNORECASE)
        .str.replace(r"\s+v\.\s*\d+", "", regex=True, flags=re.IGNORECASE)
        .str.strip()
    )
    exercise_rows = [
        tuple(_sqlite_value(row[column], column=column) for column in EXERCISE_COLUMNS)
        for row in exercises.to_dict(orient="records")
    ]
    muscle_cols = [column for column in df.columns if column.startswith("secondaryMuscles/")]
    return exercise_rows, _secondary_muscle_rows(df, muscle_cols)


def _upsert_exercise_rows(cursor, exercise_rows):
    placeholders = ", ".join("?" for _ in EXERCISE_COLUMNS)
    updates = ", ".join(f"{column} = excluded.{column}" for column in EXERCISE_COLUMNS[1:])
    cursor.executemany(
        f"INSERT INTO exercises ({', '.join(EXERCISE_COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        exercise_rows,
    )


def _replace_secondary_muscles(cursor, exercise_rows, muscle_rows):
    exercise_ids = {row[0] for row in exercise_rows}
    cursor.executemany(
        "DELETE FROM exercise_secondary_muscles WHERE exercise_id = ?",
        [(exercise_id,) for exercise_id in exercise_ids],
    )
    cursor.executemany(
        "INSERT INTO exercise_secondary_muscles (exercise_id, muscle) VALUES (?, ?)",
        muscle_rows,
    )


def _secondary_muscle_rows(df, muscle_cols):
    if not muscle_cols:
        return []
    muscles_df = df.melt(id_vars=["id"], value_vars=muscle_cols, value_name="muscle")
    muscles_df = muscles_df.dropna(subset=["muscle"])
    muscles_df["muscle"] = muscles_df["muscle"].astype(str).str.strip().str.lower()
    muscles_df = muscles_df[~muscles_df["muscle"].isin(["", "nan", "none", "null"])]
    muscles_df = muscles_df[["id", "muscle"]].drop_duplicates()
    return [
        (_sqlite_value(row["id"], column="id"), row["muscle"])
        for row in muscles_df.to_dict(orient="records")
    ]
