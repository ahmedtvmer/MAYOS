"""ExerciseSeedingMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import re
import pandas as pd
from database.shared import DEFAULT_CSV_PATH

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


class ExerciseSeedingMixin:
    def initialize_and_seed(self, csv_path=DEFAULT_CSV_PATH) -> None:
        # The catalog schema only: any per-ledger schema is created by
        # ``open_ledger`` when a handle is actually opened (ADR 041).
        self.create_catalog_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM exercises")
            if cursor.fetchone()[0] > 0:
                logger.info("Database already populated. Skipping CSV seed.")
                return

            logger.info("Seeding database from CSV...")
            try:
                df = pd.read_csv(csv_path)
            except FileNotFoundError:
                logger.error(f"Error: {csv_path} not found.")
                return

            core_df = df[
                ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
            ].copy()
            core_df.rename(columns={"bodyPart": "body_part", "target": "target_muscle"}, inplace=True)
            core_df["name"] = (
                core_df["name"]
                .astype(str)
                .str.replace(r"^lever\s+", "machine ", regex=True, flags=re.IGNORECASE)
                .str.replace(r"\s+v\.\s*\d+", "", regex=True, flags=re.IGNORECASE)
                .str.strip()
            )
            core_df.to_sql("exercises", self.catalog_conn, if_exists="append", index=False)

            muscle_cols = [c for c in df.columns if c.startswith("secondaryMuscles/")]

            if muscle_cols:
                muscles_df = (
                    df.melt(id_vars=["id"], value_vars=muscle_cols, value_name="muscle")
                    .dropna(subset=["muscle"])
                )
                # Clean whitespace and case
                muscles_df["muscle"] = muscles_df["muscle"].astype(str).str.strip().str.lower()
                
                # Filter out empty strings and stringified nulls
                muscles_df = muscles_df[
                    ~muscles_df["muscle"].isin(["", "nan", "none", "null"])
                ]
                
                # Rename and drop duplicate pairs
                muscles_df = (
                    muscles_df[["id", "muscle"]]
                    .rename(columns={"id": "exercise_id"})
                    .drop_duplicates()
                )

                if not muscles_df.empty:
                    muscles_df.to_sql(
                        "exercise_secondary_muscles",
                        self.catalog_conn,
                        if_exists="append",
                        index=False
                    )
                    self.catalog_conn.commit()

    EXCLUDED_BIOMECHANICAL_PATTERNS = ("behind neck", "behind the neck", "upright row")
