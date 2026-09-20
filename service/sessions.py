"""Session ledger export assembly (CSV/JSON)."""

from datetime import UTC, datetime
from typing import Any

from agent.progression_engine import calculate_e1rm
from service._base import bind_user
from utils.exporter import export_sessions_to_csv, export_sessions_to_json

EXPORT_FILENAMES = {"csv": "mayos_session_log.csv", "json": "mayos_session_log.json"}


def export_session_log(db: Any, trainee_id: str, fmt: str) -> tuple[str, bytes] | None:
    """Returns (filename, payload) for the trainee's full ledger, or None when it is empty."""
    bind_user(db, trainee_id)
    rows = db.get_session_log()
    if not rows:
        return None

    csv_rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    session_index: dict[str, dict[str, Any]] = {}

    for row in rows:
        rpe = float(row["rpe"]) if row["rpe"] is not None else 8.5
        e1rm = round(calculate_e1rm(float(row["weight_kg"]), int(row["reps"]), rpe), 2)
        volume = round(float(row["weight_kg"]) * int(row["reps"]), 2)
        csv_rows.append({**row, "e1rm_kg": e1rm, "volume_kg": volume})

        session = session_index.get(row["session_id"])
        if session is None:
            session = {
                "session_id": row["session_id"],
                "session_date": row["session_date"],
                "split_name": row["split_name"],
                "readiness_score": row["readiness_score"],
                "session_notes": row["session_notes"],
                "coach_debrief": db.get_session_debrief(row["session_id"]),
                "exercises": [],
                "_exercise_index": {},
            }
            session_index[row["session_id"]] = session
            sessions.append(session)

        exercise = session["_exercise_index"].get(row["exercise_id"])
        if exercise is None:
            exercise = {"exercise_id": row["exercise_id"], "exercise_name": row["exercise_name"], "sets": []}
            session["_exercise_index"][row["exercise_id"]] = exercise
            session["exercises"].append(exercise)
        exercise["sets"].append(
            {
                "set_index": row["set_index"],
                "weight_kg": row["weight_kg"],
                "reps": row["reps"],
                "rpe": row["rpe"],
                "is_warmup": row["is_warmup"],
                "e1rm_kg": e1rm,
                "volume_kg": volume,
                "logged_at": row["logged_at"],
            }
        )

    for session in sessions:
        session.pop("_exercise_index", None)

    if fmt == "csv":
        payload = export_sessions_to_csv(csv_rows)
    else:
        payload = export_sessions_to_json(sessions, datetime.now(UTC).isoformat())
    return EXPORT_FILENAMES[fmt], payload
