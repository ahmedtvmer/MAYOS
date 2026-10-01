"""LedgerProfileMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from datetime import UTC, datetime
from typing import Any
from core.deload_choices import DELOAD_CHOICES
from utils.equipment_access import map_equipment_access

from agent.prompts import DEFAULT_ASSISTANT_STYLE


class LedgerProfileMixin:
    def get_deload_choice(self) -> str | None:
        row = self.conn.execute("SELECT choice FROM deload_choices WHERE id = 1").fetchone()
        return str(row[0]) if row else None

    def set_deload_choice(self, choice: str) -> None:
        if choice not in DELOAD_CHOICES:
            raise ValueError("Deload choice must be undo or apply")
        self.conn.execute(
            "INSERT INTO deload_choices (id, choice) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET choice = excluded.choice",
            (choice,),
        )
        self._commit_ledger()

    def consume_deload_choice(self) -> str | None:
        choice = self.get_deload_choice()
        self.conn.execute("DELETE FROM deload_choices WHERE id = 1")
        self._commit_ledger()
        return choice

    def get_player_profile(self, user_id: int = 1) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_assistant_memory(self) -> dict[str, str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM assistant_memory WHERE key = ?", ("preferred_name",))
        return dict(cursor.fetchall())

    def set_assistant_memory(self, key: str, value: str) -> None:
        if key != "preferred_name":
            raise ValueError("Unsupported assistant memory key")
        if not isinstance(value, str) or not 1 <= len(value) <= 60 or not value.strip() or not value.isprintable():
            raise ValueError("Preferred name must be a nonempty printable string of at most 60 characters")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO assistant_memory (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def upsert_player_profile(self, profile_data: dict, user_id: int = 1) -> None:
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.cursor()
        params = {
            "id": int(profile_data.get("id", user_id)),
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
            "equipment_access": map_equipment_access(profile_data.get("equipment_access")),
            "injuries_or_limitations": str(profile_data.get("injuries_or_limitations", "None")),
            "stress_and_sleep": str(profile_data.get("stress_and_sleep", "normal")),
            "coach_tone": str(profile_data.get("coach_tone", DEFAULT_ASSISTANT_STYLE)),
            "custom_instructions": str(profile_data.get("custom_instructions", "")),
            "created_at": now,
            "updated_at": now,
        }
        cursor.execute(
            """
            INSERT INTO user_profile (
                id, gender, proportions, age, weight_kg, height_cm, rep_preference,
                current_goal, long_term_goal, weekly_frequency, training_age_years,
                equipment_access, injuries_or_limitations, stress_and_sleep, coach_tone,
                custom_instructions, created_at, updated_at
            ) VALUES (
                :id, :gender, :proportions, :age, :weight_kg, :height_cm, :rep_preference,
                :current_goal, :long_term_goal, :weekly_frequency, :training_age_years,
                :equipment_access, :injuries_or_limitations, :stress_and_sleep, :coach_tone,
                :custom_instructions, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                gender = excluded.gender, proportions = excluded.proportions, age = excluded.age,
                weight_kg = excluded.weight_kg, height_cm = excluded.height_cm,
                rep_preference = excluded.rep_preference, current_goal = excluded.current_goal,
                long_term_goal = excluded.long_term_goal, weekly_frequency = excluded.weekly_frequency,
                training_age_years = excluded.training_age_years, equipment_access = excluded.equipment_access,
                injuries_or_limitations = excluded.injuries_or_limitations, stress_and_sleep = excluded.stress_and_sleep,
                updated_at = excluded.updated_at
        """,
            params,
        )
        self.conn.commit()

    def update_player_persona(self, coach_tone: str, custom_instructions: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE user_profile
            SET coach_tone = ?, custom_instructions = ?, updated_at = ?
            WHERE id = 1
        """,
            (coach_tone.strip(), custom_instructions.strip(), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
