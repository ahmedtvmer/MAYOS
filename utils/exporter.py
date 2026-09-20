import io
import json
import re
from typing import Any

import pandas as pd

from agent.program_blueprints import WARMUP_PROTOCOL_AR
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

PROGRAM_COLUMNS_AR = [
    "اليوم",
    "التمرين",
    "مجاميع التسخين",
    "المجاميع الفعلية",
    "العدات",
    "RPE",
    "الراحة",
    "ملحوظات",
    "أسبوع 1 وزن",
    "أسبوع 1 عدات",
    "أسبوع 2 وزن",
    "أسبوع 2 عدات",
    "أسبوع 3 وزن",
    "أسبوع 3 عدات",
    "أسبوع 4 وزن",
    "أسبوع 4 عدات",
]


def format_rest_ar(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} ثانيه"
    return f"{seconds / 60:g} دقايق"


def sanitize_sheet_title(title: str) -> str:
    r"""
    Strips Excel-illegal characters (\ / ? * : [ ]) and trims to 31 chars.
    """
    clean_title = re.sub(r"[\\/*?:\[\]]", "-", title)
    return clean_title.strip()[:31]


def export_program_to_excel(program: GeneratedProgramSchema) -> bytes:
    """
    Exports a GeneratedProgramSchema into an in-memory Excel workbook (.xlsx)
    using the Belghamdi sheet layout: Arabic instructions, a warm-up block per
    day and a movement table with warm-up sets, working sets, reps and rest.
    """
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        instruction_lines = [["تعليمات البرنامج"], ["",], *[[line] for line in (program.instructions or "").splitlines() if line]]
        instruction_lines.append(["",])
        instruction_lines.extend([[line] for line in WARMUP_PROTOCOL_AR.splitlines() if line])
        pd.DataFrame(instruction_lines).to_excel(writer, sheet_name="التعليمات", header=False, index=False)

        for day in program.days:
            rows: list[dict[str, Any]] = []
            for warmup in day.warmup_exercises:
                rows.append(
                    {
                        "اليوم": "WARM UPS",
                        "التمرين": warmup.exercise_name,
                        "مجاميع التسخين": "-",
                        "المجاميع الفعلية": warmup.sets,
                        "العدات": warmup.reps,
                        "RPE": "",
                        "الراحة": format_rest_ar(warmup.rest_seconds),
                        "ملحوظات": warmup.notes or "",
                    }
                )
            for ex in day.exercises:
                rows.append(
                    {
                        "اليوم": "",
                        "التمرين": ex.exercise_name,
                        "مجاميع التسخين": ex.warmup_sets if ex.warmup_sets else "-",
                        "المجاميع الفعلية": ex.target_sets,
                        "العدات": f"{ex.target_reps_min}~{ex.target_reps_max}",
                        "RPE": ex.target_rpe,
                        "الراحة": format_rest_ar(ex.rest_seconds),
                        "ملحوظات": ex.notes or "",
                    }
                )
                if day.cardio:
                    rows.append({"اليوم": "", "التمرين": day.cardio})

            df = pd.DataFrame(rows, columns=PROGRAM_COLUMNS_AR).fillna("")
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
