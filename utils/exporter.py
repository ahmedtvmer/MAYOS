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


def sanitize_sheet_title(title: str) -> str:
    r"""
    Strips Excel-illegal characters (\ / ? * : [ ]) and trims to 31 chars.
    """
    clean_title = re.sub(r"[\\/*?:\[\]]", "-", title)
    return clean_title.strip()[:31]


def export_program_to_excel(program: GeneratedProgramSchema) -> bytes:
    """
    Exports a GeneratedProgramSchema into an in-memory Excel workbook (.xlsx)
    with dedicated columns for 4 weeks of double progression tracking.
    """
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for day in program.days:
            rows = []
            for idx, ex in enumerate(day.exercises, start=1):
                reps_target = f"{ex.target_reps_min}-{ex.target_reps_max}"
                rows.append(
                    {
                        "Order": idx,
                        "Exercise": ex.exercise_name,
                        "Sets": ex.target_sets,
                        "Target Reps": reps_target,
                        "Target RPE": f"@{ex.target_rpe}",
                        "Rest": f"{ex.rest_seconds}s",
                        "Execution Cues": ex.notes or "",
                        "W1 Load (kg)": "",
                        "W1 Reps": "",
                        "W2 Load (kg)": "",
                        "W2 Reps": "",
                        "W3 Load (kg)": "",
                        "W3 Reps": "",
                        "W4 Load (kg)": "",
                        "W4 Reps": "",
                    }
                )

            df = pd.DataFrame(rows)
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
