import io
import json
import re
from typing import Any

import pandas as pd

from agent.ProgramState import GeneratedProgramSchema

SESSION_CSV_COLUMNS = [
    "session_date",
    "split_name",
    "readiness_score",
    "session_notes",
    "exercise_name",
    "set_index",
    "weight_kg",
    "reps",
    "rpe",
    "is_warmup",
    "e1rm_kg",
    "volume_kg",
    "logged_at",
    "session_id",
]

PROGRAM_COLUMNS = [
    "Day",
    "Exercise",
    "Warm-up Sets",
    "Working Sets",
    "Reps",
    "RPE",
    "Rest",
    "W1 Load (kg)",
    "W1 Reps",
    "W2 Load (kg)",
    "W2 Reps",
    "W3 Load (kg)",
    "W3 Reps",
    "W4 Load (kg)",
    "W4 Reps",
]


def format_rest(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds / 60:g} min"


def sanitize_sheet_title(title: str) -> str:
    r"""
    Strips Excel-illegal characters (\ / ? * : [ ]) and trims to 31 chars.
    """
    clean_title = re.sub(r"[\\/*?:\[\]]", "-", title)
    return clean_title.strip()[:31]


def export_program_to_excel(program: GeneratedProgramSchema) -> bytes:
    """
    Exports a GeneratedProgramSchema into an in-memory Excel workbook (.xlsx)
    with one sheet per training day: a warm-up block, followed by the movement
    table (warm-up sets, working sets, reps, RPE, rest) and 4-week load logging.
    """
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for day in program.days:
            rows: list[dict[str, Any]] = []
            for warmup in day.warmup_exercises:
                rows.append(
                    {
                        "Day": "WARM UPS",
                        "Exercise": warmup.exercise_name,
                        "Warm-up Sets": "-",
                        "Working Sets": warmup.sets,
                        "Reps": warmup.reps,
                        "RPE": "",
                        "Rest": format_rest(warmup.rest_seconds),
                    }
                )
            for ex in day.exercises:
                rows.append(
                    {
                        "Day": "",
                        "Exercise": ex.exercise_name,
                        "Warm-up Sets": ex.warmup_sets if ex.warmup_sets else "-",
                        "Working Sets": ex.target_sets,
                        "Reps": f"{ex.target_reps_min}~{ex.target_reps_max}",
                        "RPE": ex.target_rpe,
                        "Rest": format_rest(ex.rest_seconds),
                    }
                )
            if day.cardio:
                rows.append({"Day": "", "Exercise": day.cardio})

            df = pd.DataFrame(rows, columns=PROGRAM_COLUMNS).fillna("")
            raw_title = f"Day {day.day_order} - {day.day_name}"
            sheet_name = sanitize_sheet_title(raw_title)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    return output.getvalue()


def export_sessions_to_csv(rows: list[dict[str, Any]]) -> bytes:
    """Flattens set-level ledger rows into a UTF-8 CSV with a fixed column order."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=SESSION_CSV_COLUMNS)
    return frame[SESSION_CSV_COLUMNS].to_csv(index=False).encode("utf-8")


def export_sessions_to_json(sessions: list[dict[str, Any]], exported_at: str) -> bytes:
    """Serializes the nested session → exercise → set ledger with a versioned schema."""
    payload = {"schema_version": 1, "exported_at": exported_at, "sessions": sessions}
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
