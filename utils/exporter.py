import json
from typing import Any

import pandas as pd


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
