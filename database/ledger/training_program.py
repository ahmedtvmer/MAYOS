"""LedgerTrainingProgramMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
import uuid
from datetime import UTC, datetime
from agent.ProgramState import GeneratedProgramSchema
from agent.ProgramState import ProgramDaySchema
from agent.ProgramState import ProgramExerciseSchema
from agent.ProgramState import WarmupExerciseSchema

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


class LedgerTrainingProgramMixin:
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
                    cursor.execute(
                        f"INSERT INTO program_exercises ({', '.join(exercise_values)}) "
                        f"VALUES ({', '.join(['?'] * len(exercise_values))})",
                        list(exercise_values.values()),
                    )

            self.conn.commit()
            return prog_id
        except Exception as e:
            self.conn.rollback()
            raise RuntimeError(f"Database error while saving program: {e}")

    def _load_program(self, where_sql: str, params: tuple = ()) -> GeneratedProgramSchema | None:
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

        days = []
        try:
            for day_row in days_rows:
                d_id, d_name, d_order = day_row[0], day_row[1], day_row[2]
                warmup_json = day_row[3] if "warmup_json" in day_cols else None
                cardio = day_row[4] if "cardio" in day_cols and len(day_row) > 4 else None

                select_cols = (
                    "pe.exercise_id, e.name, pe.target_sets, pe.target_reps_min, "
                    "pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes, "
                    "e.image_path, e.gif_path"
                )
                if has_slot_key:
                    select_cols += ", pe.slot_key"
                if has_warmup_sets:
                    select_cols += ", pe.warmup_sets"
                cursor.execute(
                    f"""
                    SELECT {select_cols}
                    FROM program_exercises pe
                    JOIN catalog.exercises e ON pe.exercise_id = e.id
                    WHERE pe.day_id = ?
                    ORDER BY pe.order_in_day ASC
                """,
                    (d_id,),
                )
                exercises = []
                for r in cursor.fetchall():
                    exercises.append(
                        ProgramExerciseSchema(
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
                            slot_key=r[10] if has_slot_key else None,
                            warmup_sets=int(r[11]) if has_warmup_sets and r[11] is not None else 0,
                        )
                    )

                warmup_exercises = []
                if warmup_json:
                    try:
                        warmup_exercises = [WarmupExerciseSchema(**item) for item in json.loads(warmup_json)]
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Skipping malformed warm-up block on day '{d_name}': {exc}")

                days.append(
                    ProgramDaySchema(
                        day_name=d_name,
                        day_order=d_order,
                        warmup_exercises=warmup_exercises,
                        exercises=exercises,
                        cardio=cardio,
                    )
                )

            return GeneratedProgramSchema(
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

    def get_active_program(self) -> GeneratedProgramSchema | None:
        return self._load_program("is_active = 1")

    def get_program_by_version(self, version: int) -> GeneratedProgramSchema | None:
        """The player's program with this stable version, active or historical (ADR 034).

        Publishing a new program only flips ``is_active``; older rows and their
        days/exercises are kept, so an offline draft captured against an older
        version resolves to the exact prescription it trained against.
        """
        return self._load_program("version = ?", (int(version),))

    def update_player_frequency(self, frequency: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET weekly_frequency = ?, updated_at = ? WHERE id = 1",
            (min(max(int(frequency), 1), 5), datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def swap_program_exercise(
        self, old_exercise_id: str, new_exercise_id: str, new_notes: str = "", day_id: str | None = None
    ) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")
        active_prog = cursor.fetchone()
        if not active_prog:
            return False

        prog_id = active_prog[0]
        if day_id:
            cursor.execute(
                """
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.day_id = ? AND pe.exercise_id = ? LIMIT 1
            """,
                (prog_id, day_id, old_exercise_id),
            )
        else:
            cursor.execute(
                """
                SELECT pe.id FROM program_exercises pe
                JOIN program_days pd ON pe.day_id = pd.id
                WHERE pd.program_id = ? AND pe.exercise_id = ? LIMIT 1
            """,
                (prog_id, old_exercise_id),
            )

        row = cursor.fetchone()
        if not row:
            return False

        cursor.execute(
            "UPDATE program_exercises SET exercise_id = ?, notes = ? WHERE id = ?", (new_exercise_id, new_notes, row[0])
        )
        self.conn.commit()
        return True
