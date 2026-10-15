"""LedgerProfileMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from datetime import UTC, datetime
import json
from typing import Any
import uuid
from core.deload_choices import DELOAD_CHOICES
from utils.equipment_access import map_equipment_access

from agent.prompts import DEFAULT_ASSISTANT_STYLE
from utils.preferred_name import validate_preferred_name


PLAYER_PROFILE_STORAGE_DEFAULTS = {
    "gender": "male",
    "proportions": "balanced",
    "age": 25,
    "weight_kg": 75.0,
    "target_weight_kg": None,
    "height_cm": 175.0,
    "rep_preference": "balanced",
    "current_goal": "hypertrophy",
    "long_term_goal": "progressive overload",
    "weekly_frequency": 4,
    "training_age_years": 1.0,
    "equipment_access": map_equipment_access(None),
    "injuries_or_limitations": "None",
    "stress_and_sleep": "normal",
}

INJURY_RECORD_COLUMNS = (
    "id, body_area, description, reported_at, status, clarification_pending, "
    "physician_followup_asked_at, physician_followup_pending, resolution_pending, "
    "pending_exercise_id, pending_exercise_name, exercise_followup_asked_count"
)


class LedgerProfileMixin:
    def list_injury_records(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records "
            "ORDER BY reported_at DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_injury_record(self, injury_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records WHERE id = ?",
            (str(injury_id),),
        ).fetchone()
        return dict(row) if row else None

    def get_pending_injury_clarification(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records "
            "WHERE body_area IS NULL AND clarification_pending = 1 "
            "AND status != 'resolved' ORDER BY reported_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def create_injury_record(
        self,
        body_area: str | None,
        description: str,
        *,
        status: str = "reported",
        clarification_pending: bool = False,
        source_event_key: str | None = None,
        reported_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        injury_id = uuid.uuid4().hex
        with self.ledger_transaction():
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO injury_records "
                "(id, body_area, description, reported_at, status, source_event_key, clarification_pending) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    injury_id,
                    body_area,
                    str(description).strip()[:2000],
                    reported_at or datetime.now(UTC).isoformat(),
                    status,
                    source_event_key,
                    1 if clarification_pending else 0,
                ),
            )
            if source_event_key:
                row = self.conn.execute(
                    f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records WHERE source_event_key = ?",
                    (source_event_key,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records WHERE id = ?",
                    (injury_id,),
                ).fetchone()
        result = dict(row) if row else {}
        return result, bool(result and inserted.rowcount == 1)

    def update_injury_record(
        self,
        injury_id: str,
        *,
        body_area: str | None = None,
        update_body_area: bool = False,
        description: str | None = None,
        status: str | None = None,
        clarification_pending: bool | None = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if body_area is not None or update_body_area:
            updates["body_area"] = body_area
            updates["clarification_pending"] = 0
        if description is not None:
            updates["description"] = str(description).strip()[:2000]
        if status is not None:
            updates["status"] = status
        if clarification_pending is not None:
            updates["clarification_pending"] = 1 if clarification_pending else 0
        if updates:
            assignments = ", ".join(f"{field} = ?" for field in updates)
            self.conn.execute(
                f"UPDATE injury_records SET {assignments} WHERE id = ?",
                (*updates.values(), str(injury_id)),
            )
            self._commit_ledger()
        return self.get_injury_record(injury_id)

    def mark_physician_followup_asked(self, injury_id: str, asked_at: str) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET physician_followup_asked_at = ?, "
            "physician_followup_pending = 1 WHERE id = ?",
            (asked_at, str(injury_id)),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def set_physician_followup_pending(
        self, injury_id: str, pending: bool
    ) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET physician_followup_pending = ? WHERE id = ?",
            (1 if pending else 0, str(injury_id)),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def set_resolution_pending(self, injury_id: str, pending: bool) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET resolution_pending = ? WHERE id = ?",
            (1 if pending else 0, str(injury_id)),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def set_pending_exercise_followup(
        self, injury_id: str, exercise_id: str, exercise_name: str
    ) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET pending_exercise_id = ?, pending_exercise_name = ?, "
            "exercise_followup_asked_count = exercise_followup_asked_count + 1 "
            "WHERE id = ?",
            (str(exercise_id), exercise_name, str(injury_id)),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def reset_exercise_followup_asked_count(self, injury_id: str) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET exercise_followup_asked_count = 0 WHERE id = ?",
            (str(injury_id),),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def clear_pending_exercise_followup(self, injury_id: str) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE injury_records SET pending_exercise_id = NULL, pending_exercise_name = NULL "
            "WHERE id = ?",
            (str(injury_id),),
        )
        self._commit_ledger()
        return self.get_injury_record(injury_id)

    def list_exercise_clearances(self, injury_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, injury_id, exercise_id, exercise_name, original_wording, verdict, "
            "note, recorded_at, source FROM exercise_clearances "
            "WHERE injury_id = ? ORDER BY recorded_at DESC, id DESC",
            (str(injury_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_exercise_clearance(self, clearance_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, injury_id, exercise_id, exercise_name, original_wording, verdict, "
            "note, recorded_at, source FROM exercise_clearances WHERE id = ?",
            (str(clearance_id),),
        ).fetchone()
        return dict(row) if row else None

    def create_exercise_clearance(
        self,
        *,
        injury_id: str,
        exercise_id: str | None,
        exercise_name: str,
        original_wording: str,
        verdict: str,
        note: str | None = None,
        source_event_key: str | None = None,
        recorded_at: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        clearance_id = uuid.uuid4().hex
        with self.ledger_transaction():
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO exercise_clearances "
                "(id, injury_id, exercise_id, exercise_name, original_wording, verdict, note, recorded_at, source_event_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clearance_id, str(injury_id), exercise_id, str(exercise_name)[:200],
                    str(original_wording)[:2000], verdict, note, recorded_at or datetime.now(UTC).isoformat(),
                    source_event_key,
                ),
            )
            if source_event_key:
                row = self.conn.execute(
                    "SELECT id, injury_id, exercise_id, exercise_name, original_wording, verdict, "
                    "note, recorded_at, source FROM exercise_clearances WHERE source_event_key = ?",
                    (source_event_key,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT id, injury_id, exercise_id, exercise_name, original_wording, verdict, "
                    "note, recorded_at, source FROM exercise_clearances WHERE id = ?",
                    (clearance_id,),
                ).fetchone()
        return (dict(row) if row else None), bool(row and inserted.rowcount == 1)

    def update_exercise_clearance(
        self, clearance_id: str, *, exercise_name: str, original_wording: str,
        verdict: str, note: str | None,
    ) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE exercise_clearances SET exercise_name = ?, original_wording = ?, "
            "verdict = ?, note = ?, recorded_at = ? WHERE id = ?",
            (str(exercise_name)[:200], str(original_wording)[:2000], verdict, note,
             datetime.now(UTC).isoformat(), str(clearance_id)),
        )
        self._commit_ledger()
        return self.get_exercise_clearance(clearance_id)

    def delete_exercise_clearance(self, clearance_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM exercise_clearances WHERE id = ?", (str(clearance_id),)
        )
        self._commit_ledger()
        return cursor.rowcount == 1

    def get_pending_exercise_clearance(self, injury_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT injury_id, original_wording, verdict, note, candidates_json "
            "FROM pending_exercise_clearances WHERE injury_id = ?", (str(injury_id),)
        ).fetchone()
        if not row:
            return None
        return {**dict(row), "candidates": json.loads(row["candidates_json"])}

    def set_pending_exercise_clearance(
        self, injury_id: str, *, original_wording: str, verdict: str,
        note: str | None, candidates: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            "INSERT INTO pending_exercise_clearances "
            "(injury_id, original_wording, verdict, note, candidates_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(injury_id) DO UPDATE SET "
            "original_wording = excluded.original_wording, verdict = excluded.verdict, "
            "note = excluded.note, candidates_json = excluded.candidates_json, updated_at = excluded.updated_at",
            (str(injury_id), original_wording[:2000], verdict, note,
             json.dumps(candidates, ensure_ascii=False), datetime.now(UTC).isoformat()),
        )
        self._commit_ledger()

    def clear_pending_exercise_clearance(self, injury_id: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_exercise_clearances WHERE injury_id = ?", (str(injury_id),)
        )
        self._commit_ledger()

    def get_latest_active_injury(self, body_area: str | None = None) -> dict[str, Any] | None:
        area_clause = " AND body_area = ?" if body_area is not None else ""
        params = (body_area,) if body_area is not None else ()
        row = self.conn.execute(
            f"SELECT {INJURY_RECORD_COLUMNS} FROM injury_records "
            f"WHERE status != 'resolved'{area_clause} "
            "ORDER BY reported_at DESC, id DESC LIMIT 1",
            params,
        ).fetchone()
        return dict(row) if row else None

    def sync_legacy_injuries_projection(self) -> None:
        """Refreshes the legacy profile field from active structured injuries."""
        with self.ledger_transaction():
            rows = self.conn.execute(
                "SELECT description FROM injury_records WHERE status != 'resolved' "
                "ORDER BY reported_at DESC, id DESC"
            ).fetchall()
            projection = "; ".join(str(row[0]) for row in rows) or "None"
            self.conn.execute(
                "UPDATE user_profile SET injuries_or_limitations = ?, updated_at = ? WHERE id = 1",
                (projection[:2000], datetime.now(UTC).isoformat()),
            )

    def upsert_player_profile_with_weight_history(self, profile_data: dict, entry_date: str) -> None:
        """Writes an explicit profile weight together with its dated ledger entry."""
        with self.ledger_transaction():
            self.upsert_player_profile(profile_data)
            if "weight_kg" in profile_data:
                self.upsert_weight_history_entry(entry_date, float(profile_data["weight_kg"]))

    def upsert_weight_history_entry(self, entry_date: str, weight_kg: float) -> None:
        """Keeps one weight value for a calendar day in this Training ledger."""
        self.conn.execute(
            "INSERT INTO weight_history (entry_date, weight_kg) VALUES (?, ?) "
            "ON CONFLICT(entry_date) DO UPDATE SET weight_kg = excluded.weight_kg",
            (str(entry_date), float(weight_kg)),
        )
        self._commit_ledger()

    def list_weight_history(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Returns dated weight entries in ascending calendar-day order."""
        rows = self.conn.execute(
            "SELECT entry_date, weight_kg FROM weight_history "
            "WHERE entry_date >= ? AND entry_date <= ? ORDER BY entry_date ASC",
            (str(start_date), str(end_date)),
        ).fetchall()
        return [{"entry_date": str(row[0]), "weight_kg": float(row[1])} for row in rows]

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
        validate_preferred_name(value)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO assistant_memory (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def clear_preferred_name(self) -> None:
        self.conn.execute(
            "DELETE FROM assistant_memory WHERE key = ?", ("preferred_name",)
        )
        self.conn.commit()

    def upsert_player_profile(self, profile_data: dict, user_id: int = 1) -> None:
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.cursor()
        params = {
            "id": int(profile_data.get("id", user_id)),
            "gender": str(
                profile_data.get("gender", PLAYER_PROFILE_STORAGE_DEFAULTS["gender"])
            ).lower(),
            "proportions": str(
                profile_data.get("proportions", PLAYER_PROFILE_STORAGE_DEFAULTS["proportions"])
            ),
            "age": int(
                profile_data.get("age", PLAYER_PROFILE_STORAGE_DEFAULTS["age"])
            ),
            "weight_kg": float(
                profile_data.get("weight_kg", PLAYER_PROFILE_STORAGE_DEFAULTS["weight_kg"])
            ),
            "target_weight_kg": (
                float(profile_data["target_weight_kg"])
                if profile_data.get("target_weight_kg") is not None
                else None
            ),
            "target_weight_present": int("target_weight_kg" in profile_data),
            "height_cm": float(
                profile_data.get("height_cm", PLAYER_PROFILE_STORAGE_DEFAULTS["height_cm"])
            ),
            "rep_preference": str(
                profile_data.get("rep_preference", PLAYER_PROFILE_STORAGE_DEFAULTS["rep_preference"])
            ),
            "current_goal": str(
                profile_data.get("current_goal", PLAYER_PROFILE_STORAGE_DEFAULTS["current_goal"])
            ),
            "long_term_goal": str(
                profile_data.get("long_term_goal", PLAYER_PROFILE_STORAGE_DEFAULTS["long_term_goal"])
            ),
            "weekly_frequency": min(
                max(
                    int(
                        profile_data.get(
                            "weekly_frequency",
                            PLAYER_PROFILE_STORAGE_DEFAULTS["weekly_frequency"],
                        )
                    ),
                    1,
                ),
                5,
            ),
            "training_age_years": float(
                profile_data.get(
                    "training_age_years",
                    PLAYER_PROFILE_STORAGE_DEFAULTS["training_age_years"],
                )
            ),
            "equipment_access": map_equipment_access(
                profile_data.get(
                    "equipment_access", PLAYER_PROFILE_STORAGE_DEFAULTS["equipment_access"]
                )
            ),
            "injuries_or_limitations": str(
                profile_data.get(
                    "injuries_or_limitations",
                    PLAYER_PROFILE_STORAGE_DEFAULTS["injuries_or_limitations"],
                )
            ),
            "stress_and_sleep": str(
                profile_data.get(
                    "stress_and_sleep",
                    PLAYER_PROFILE_STORAGE_DEFAULTS["stress_and_sleep"],
                )
            ),
            "coach_tone": str(profile_data.get("coach_tone", DEFAULT_ASSISTANT_STYLE)),
            "custom_instructions": str(profile_data.get("custom_instructions", "")),
            "created_at": now,
            "updated_at": now,
        }
        cursor.execute(
            """
            INSERT INTO user_profile (
                id, gender, proportions, age, weight_kg, target_weight_kg, height_cm, rep_preference,
                current_goal, long_term_goal, weekly_frequency, training_age_years,
                equipment_access, injuries_or_limitations, stress_and_sleep, coach_tone,
                custom_instructions, created_at, updated_at
            ) VALUES (
                :id, :gender, :proportions, :age, :weight_kg, :target_weight_kg, :height_cm, :rep_preference,
                :current_goal, :long_term_goal, :weekly_frequency, :training_age_years,
                :equipment_access, :injuries_or_limitations, :stress_and_sleep, :coach_tone,
                :custom_instructions, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                gender = excluded.gender, proportions = excluded.proportions, age = excluded.age,
                weight_kg = excluded.weight_kg,
                target_weight_kg = CASE WHEN :target_weight_present = 1
                    THEN excluded.target_weight_kg ELSE user_profile.target_weight_kg END,
                height_cm = excluded.height_cm,
                rep_preference = excluded.rep_preference, current_goal = excluded.current_goal,
                long_term_goal = excluded.long_term_goal, weekly_frequency = excluded.weekly_frequency,
                training_age_years = excluded.training_age_years, equipment_access = excluded.equipment_access,
                injuries_or_limitations = excluded.injuries_or_limitations, stress_and_sleep = excluded.stress_and_sleep,
                updated_at = excluded.updated_at
        """,
            params,
        )
        self._commit_ledger()

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
