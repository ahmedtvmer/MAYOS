"""LedgerTrainingProgramMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from agent.ProgramState import PersistedProgramDaySchema
from agent.ProgramState import PersistedProgramExerciseSchema
from agent.ProgramState import PersistedProgramSchema
from agent.ProgramState import WarmupExerciseSchema
from database.exercise_resolution import EXERCISE_DISPLAY_EQUIPMENT_SQL
from database.exercise_resolution import exercise_display_join, exercise_display_name_sql

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def _with_current_name(movement: Any, current_names: dict[str, str]) -> Any:
    """Copy of a stored substitute or warm-up movement carrying its current name, when known."""
    name = current_names.get(str(movement.exercise_id))
    return movement.model_copy(update={"exercise_name": name}) if name else movement


class LedgerTrainingProgramMixin:
    def has_program_published_by_coach_since(self, coach_account_id: str, started_at: str) -> bool:
        """Whether this coach has already published in the active Assignment."""
        row = self.conn.execute(
            "SELECT 1 FROM training_programs"
            " WHERE published_by_coach_account_id = ? AND created_at >= ? LIMIT 1",
            (coach_account_id, started_at),
        ).fetchone()
        return row is not None

    def has_exercise_in_program_history(self, exercise_id: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM program_exercises pe "
            "JOIN program_days pd ON pd.id = pe.day_id "
            "JOIN training_programs tp ON tp.id = pd.program_id "
            "WHERE pe.exercise_id = ? LIMIT 1",
            (str(exercise_id),),
        )
        return cursor.fetchone() is not None

    def save_training_program(
        self, program_data: dict, published_by_coach_account_id: str | None = None
    ) -> str:
        """Persists a new active program, stamping a stable version and provenance.

        ``published_by_coach_account_id`` is ``None`` for player self-service and the
        assigning coach's account id for a coach publication (ADR 026).
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE training_programs SET is_active = 0")
            prog_id = program_data.get("id") or str(uuid.uuid4())
            created_at = program_data.get("created_at") or datetime.now(UTC).isoformat()
            prog_name = program_data.get("program_name") or program_data.get("name", "Custom Program")

            cursor.execute("PRAGMA table_info(training_programs)")
            existing_cols = {col[1] for col in cursor.fetchall()}

            cols = ["id", "weekly_frequency", "split_type", "is_active", "created_at"]
            vals = [
                prog_id,
                program_data.get("weekly_frequency", 4),
                program_data.get("split_type", "custom"),
                1,
                created_at,
            ]

            if "name" in existing_cols:
                cols.append("name")
                vals.append(prog_name)
            if "program_name" in existing_cols:
                cols.append("program_name")
                vals.append(prog_name)
            if "instructions" in existing_cols:
                cols.append("instructions")
                vals.append(program_data.get("instructions", ""))
            if "version" in existing_cols:
                cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM training_programs")
                cols.append("version")
                vals.append(int(cursor.fetchone()[0]))
            if "published_by_coach_account_id" in existing_cols:
                cols.append("published_by_coach_account_id")
                vals.append(published_by_coach_account_id)

            cursor.execute(
                f"INSERT INTO training_programs ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(vals))})", vals
            )

            cursor.execute("PRAGMA table_info(program_days)")
            day_cols = {col[1] for col in cursor.fetchall()}
            cursor.execute("PRAGMA table_info(program_exercises)")
            exercise_cols = {col[1] for col in cursor.fetchall()}

            for day in program_data.get("days", []):
                day_id = day.get("id") or str(uuid.uuid4())
                day_values = {
                    "id": day_id,
                    "program_id": prog_id,
                    "day_name": day["day_name"],
                    "day_order": day["day_order"],
                }
                if "warmup_json" in day_cols:
                    day_values["warmup_json"] = json.dumps(day.get("warmup_exercises", []), ensure_ascii=False)
                if "cardio" in day_cols:
                    day_values["cardio"] = day.get("cardio")
                cursor.execute(
                    f"INSERT INTO program_days ({', '.join(day_values)}) VALUES ({', '.join(['?'] * len(day_values))})",
                    list(day_values.values()),
                )

                for order_idx, ex in enumerate(day.get("exercises", []), start=1):
                    pe_id = ex.get("id") or str(uuid.uuid4())
                    exercise_values = {
                        "id": pe_id,
                        "day_id": day_id,
                        "exercise_id": str(ex["exercise_id"]),
                        "order_in_day": order_idx,
                        "target_sets": ex.get("target_sets", 2),
                        "target_reps_min": ex.get("target_reps_min", 8),
                        "target_reps_max": ex.get("target_reps_max", 12),
                        "target_rpe": ex.get("target_rpe", 8.5),
                        "rest_seconds": ex.get("rest_seconds", 180),
                        "notes": ex.get("notes", ""),
                    }
                    if "slot_key" in exercise_cols:
                        exercise_values["slot_key"] = ex.get("slot_key")
                    if "warmup_sets" in exercise_cols:
                        exercise_values["warmup_sets"] = ex.get("warmup_sets", 0)
                    if "suggested_substitutes_json" in exercise_cols:
                        exercise_values["suggested_substitutes_json"] = json.dumps(
                            ex.get("suggested_substitutes", []), ensure_ascii=False
                        )
                    if "tempo" in exercise_cols:
                        exercise_values["tempo"] = ex.get("tempo")
                    cursor.execute(
                        f"INSERT INTO program_exercises ({', '.join(exercise_values)}) "
                        f"VALUES ({', '.join(['?'] * len(exercise_values))})",
                        list(exercise_values.values()),
                    )

            self._commit_ledger()
            return prog_id
        except Exception as e:
            if getattr(self._local, "ledger_tx_depth", 0) == 0:
                self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")

    def _current_exercise_names(self, exercise_ids: list[str]) -> dict[str, str]:
        """Current display names for library or Coach exercise ids; unknown ids are omitted."""
        ids = sorted({str(exercise_id) for exercise_id in exercise_ids if exercise_id})
        if not ids:
            return {}
        rows = self.conn.execute(
            f"SELECT ids.id, COALESCE(e.name, ce.name) FROM "
            f"(SELECT value AS id FROM json_each(?)) ids {exercise_display_join('ids.id')} "
            "WHERE COALESCE(e.name, ce.name) IS NOT NULL",
            (json.dumps(ids),),
        ).fetchall()
        return {str(row[0]): row[1] for row in rows}

    def _load_program(self, where_sql: str, params: tuple = ()) -> PersistedProgramSchema | None:
        """Loads one stored program, its days and exercises, by an arbitrary predicate.

        Shared by ``get_active_program`` and ``get_program_by_version`` so the
        historical-program path can never drift from the active one (ADR 034).
        """
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(training_programs)")
        program_cols = {col[1] for col in cursor.fetchall()}
        instructions_expr = "instructions" if "instructions" in program_cols else "'' AS instructions"
        version_expr = "version" if "version" in program_cols else "NULL AS version"
        provenance_expr = (
            "published_by_coach_account_id"
            if "published_by_coach_account_id" in program_cols
            else "NULL AS published_by_coach_account_id"
        )
        created_at_expr = "created_at" if "created_at" in program_cols else "NULL AS created_at"
        cursor.execute(f"""
            SELECT id, COALESCE(program_name, name), weekly_frequency, split_type, {instructions_expr},
                   {version_expr}, {provenance_expr}, {created_at_expr}
            FROM training_programs
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT 1
        """, params)
        row = cursor.fetchone()
        if not row:
            return None

        prog_id, prog_name, freq, split_type, instructions, version, published_by, created_at = row

        cursor.execute("PRAGMA table_info(program_days)")
        day_cols = {col[1] for col in cursor.fetchall()}
        day_extras = ""
        if "warmup_json" in day_cols:
            day_extras += ", warmup_json"
        if "cardio" in day_cols:
            day_extras += ", cardio"
        cursor.execute(
            f"SELECT id, day_name, day_order{day_extras} FROM program_days WHERE program_id = ? ORDER BY day_order ASC",
            (prog_id,),
        )
        days_rows = cursor.fetchall()
        if not days_rows:
            return None

        cursor.execute("PRAGMA table_info(program_exercises)")
        exercise_cols = {col[1] for col in cursor.fetchall()}
        has_slot_key = "slot_key" in exercise_cols
        has_warmup_sets = "warmup_sets" in exercise_cols
        has_suggested_substitutes = "suggested_substitutes_json" in exercise_cols
        has_tempo = "tempo" in exercise_cols

        days = []
        try:
            for day_row in days_rows:
                d_id, d_name, d_order = day_row[0], day_row[1], day_row[2]
                warmup_json = day_row[3] if "warmup_json" in day_cols else None
                cardio = day_row[4] if "cardio" in day_cols and len(day_row) > 4 else None

                select_cols = (
                    f"pe.exercise_id, {exercise_display_name_sql('pe.exercise_id')} AS name, "
                    "pe.target_sets, pe.target_reps_min, "
                    "pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes, "
                    "e.image_path, e.gif_path"
                )
                if has_slot_key:
                    select_cols += ", pe.slot_key"
                if has_warmup_sets:
                    select_cols += ", pe.warmup_sets"
                if has_suggested_substitutes:
                    select_cols += ", pe.suggested_substitutes_json"
                if has_tempo:
                    select_cols += ", pe.tempo"
                select_cols += (
                    f", {EXERCISE_DISPLAY_EQUIPMENT_SQL} AS equipment"
                    ", ce.body_part AS body_part"
                    ", ce.note AS note, ce.video_url AS video_url"
                    ", (ce.id IS NOT NULL) AS is_coach_exercise"
                )
                cursor.execute(
                    f"""
                    SELECT {select_cols}
                    FROM program_exercises pe
                    {exercise_display_join('pe.exercise_id')}
                    WHERE pe.day_id = ?
                    ORDER BY pe.order_in_day ASC
                """,
                    (d_id,),
                )
                selected_column_names = [column[0] for column in cursor.description]
                exercises = []
                for r in cursor.fetchall():
                    suggested_substitutes = []
                    row_by_column = dict(zip(selected_column_names, r))
                    if "suggested_substitutes_json" in row_by_column:
                        try:
                            suggested_substitutes = json.loads(
                                row_by_column["suggested_substitutes_json"] or "[]"
                            )
                        except (TypeError, ValueError):
                            logger.warning("Skipping malformed Staple substitute list on %s", r[1])
                    exercises.append(
                        PersistedProgramExerciseSchema(
                            exercise_id=str(r[0]),
                            exercise_name=r[1],
                            target_sets=int(r[2]),
                            target_reps_min=int(r[3]),
                            target_reps_max=int(r[4]),
                            target_rpe=float(r[5]) if r[5] is not None else 8.5,
                            rest_seconds=int(r[6]) if r[6] is not None else 180,
                            notes=r[7] or "",
                            image_path=r[8],
                            gif_path=r[9],
                            equipment=row_by_column.get("equipment"),
                            slot_key=r[10] if has_slot_key else None,
                            warmup_sets=int(r[11]) if has_warmup_sets and r[11] is not None else 0,
                            suggested_substitutes=suggested_substitutes,
                            tempo=row_by_column.get("tempo"),
                            body_part=row_by_column.get("body_part"),
                            note=row_by_column.get("note"),
                            video_url=row_by_column.get("video_url"),
                            is_coach_exercise=bool(row_by_column.get("is_coach_exercise")),
                        )
                    )

                warmup_exercises = []
                if warmup_json:
                    try:
                        warmup_exercises = [WarmupExerciseSchema(**item) for item in json.loads(warmup_json)]
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Skipping malformed warm-up block on day '{d_name}': {exc}")
                # Substitute and warm-up names are stored snapshots; show the current
                # library or Coach exercise name, like the exercises themselves.
                current_names = self._current_exercise_names(
                    [sub.exercise_id for ex in exercises for sub in ex.suggested_substitutes]
                    + [warmup.exercise_id for warmup in warmup_exercises if warmup.exercise_id]
                )
                exercises = [
                    ex.model_copy(update={"suggested_substitutes": [
                        _with_current_name(sub, current_names) for sub in ex.suggested_substitutes
                    ]})
                    for ex in exercises
                ]
                warmup_exercises = [
                    _with_current_name(warmup, current_names) for warmup in warmup_exercises
                ]

                days.append(
                    PersistedProgramDaySchema(
                        day_name=d_name,
                        day_order=d_order,
                        warmup_exercises=warmup_exercises,
                        exercises=exercises,
                        cardio=cardio,
                    )
                )

            return PersistedProgramSchema(
                program_name=prog_name,
                weekly_frequency=int(freq),
                split_type=split_type or "custom",
                instructions=instructions or "",
                days=days,
                version=int(version) if version is not None else None,
                published_by_coach_account_id=published_by,
                created_at=created_at,
            )
        except Exception as exc:
            logger.warning(f"Program '{prog_id}' is malformed or incomplete: {exc}")
            return None

    def active_program_name(self) -> str | None:
        """The active program's display name, or ``None`` while there is none.

        A name-only read (#120): the roster's program cache never needs the
        days and exercises ``get_active_program`` loads.
        """
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(training_programs)")
        columns = {col[1] for col in cursor.fetchall()}
        if "program_name" in columns:
            name_expr = "COALESCE(program_name, name)" if "name" in columns else "program_name"
        elif "name" in columns:
            name_expr = "name"
        else:
            return None
        cursor.execute(
            f"SELECT {name_expr} FROM training_programs"
            " WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return str(row[0]) if row and row[0] else None

    def get_active_program(self) -> PersistedProgramSchema | None:
        return self._load_program("is_active = 1")

    def get_program_by_version(self, version: int) -> PersistedProgramSchema | None:
        """The player's program with this stable version, active or historical (ADR 034).

        Publishing a new program only flips ``is_active``; older rows and their
        days/exercises are kept, so an offline draft captured against an older
        version resolves to the exact prescription it trained against.
        """
        return self._load_program("version = ?", (int(version),))

    def get_program_draft(self, assignment_id: str) -> dict | None:
        cursor = self.conn.execute(
            "SELECT draft_json, created_at, updated_at FROM program_drafts WHERE assignment_id = ?",
            (str(assignment_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "assignment_id": str(assignment_id),
            "draft": json.loads(row[0]),
            "created_at": str(row[1]),
            "updated_at": str(row[2]),
        }

    def create_program_draft(self, assignment_id: str, draft: dict) -> dict | None:
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO program_drafts (assignment_id, draft_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (str(assignment_id), json.dumps(draft, ensure_ascii=False), now, now),
        )
        self._commit_ledger()
        if cursor.rowcount != 1:
            return None
        return self.get_program_draft(assignment_id)

    def replace_program_draft(self, assignment_id: str, draft: dict) -> dict | None:
        self.conn.execute(
            "UPDATE program_drafts SET draft_json = ?, updated_at = ? WHERE assignment_id = ?",
            (json.dumps(draft, ensure_ascii=False), datetime.now(UTC).isoformat(), str(assignment_id)),
        )
        self._commit_ledger()
        return self.get_program_draft(assignment_id)

    def discard_program_draft(self, assignment_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM program_drafts WHERE assignment_id = ?", (str(assignment_id),)
        )
        self._commit_ledger()
        return cursor.rowcount == 1

    def update_player_frequency(self, frequency: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET weekly_frequency = ?, updated_at = ? WHERE id = 1",
            (min(max(int(frequency), 1), 5), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
