"""Session ledger export: CSV/JSON formatters and service assembly."""

import json
from types import SimpleNamespace

from service.sessions import export_session_log
from utils.exporter import SESSION_CSV_COLUMNS, export_sessions_to_csv, export_sessions_to_json


def _raw_row(**overrides):
    row = {
        "session_id": "s1",
        "session_date": "2026-09-16",
        "split_name": "Upper 1",
        "readiness_score": 4,
        "session_notes": "Felt strong, smooth bar path",
        "started_at": "2026-09-16T10:00:00+00:00",
        "completed_at": "2026-09-16T11:00:00+00:00",
        "exercise_id": "673",
        "exercise_name": "reverse grip machine lat pulldown",
        "set_index": 1,
        "weight_kg": 100.0,
        "reps": 8,
        "rpe": 8.5,
        "is_warmup": 0,
        "logged_at": "2026-09-16T10:05:00+00:00",
    }
    row.update(overrides)
    return row


def _stub_db(rows):
    return SimpleNamespace(
        _sanitize_username=lambda name: name,
        active_user="alice",
        switch_user=lambda name: None,
        get_session_log=lambda: rows,
        get_session_debrief=lambda session_id: f"Debrief for {session_id}",
    )


def test_export_sessions_to_csv_header_quoting_and_values():
    rows = [
        {**_raw_row(), "e1rm_kg": 131.67, "volume_kg": 800.0},
        {**_raw_row(set_index=2, reps=6, weight_kg=110.0, rpe=9.0), "e1rm_kg": 143.0, "volume_kg": 660.0},
    ]
    text = export_sessions_to_csv(rows).decode("utf-8")
    lines = text.splitlines()
    assert lines[0] == ",".join(SESSION_CSV_COLUMNS)
    assert len(lines) == 3
    assert '"Felt strong, smooth bar path"' in text  # quoted because it contains a comma
    assert "131.67" in text and "800.0" in text
    assert "143.0" in text and "660.0" in text


def test_export_sessions_to_csv_empty_keeps_header_only():
    text = export_sessions_to_csv([]).decode("utf-8").strip()
    assert text == ",".join(SESSION_CSV_COLUMNS)


def test_export_sessions_to_json_schema_and_unicode():
    sessions = [
        {
            "session_id": "s1",
            "session_date": "2026-09-16",
            "split_name": "Upper 1",
            "readiness_score": 4,
            "session_notes": "",
            "coach_debrief": "Great work.",
            "exercises": [
                {
                    "exercise_id": "x",
                    "exercise_name": "Élévateur latéral",
                    "sets": [{"set_index": 1, "e1rm_kg": 131.67}],
                }
            ],
        }
    ]
    payload = export_sessions_to_json(sessions, "2026-09-20T00:00:00+00:00")
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded == {"schema_version": 1, "exported_at": "2026-09-20T00:00:00+00:00", "sessions": sessions}
    assert "Élévateur latéral" in payload.decode("utf-8")  # not ASCII-escaped


def test_export_session_log_builds_nested_payload_with_computed_metrics():
    filename, payload = export_session_log(_stub_db([_raw_row()]), "alice", "json")
    assert filename == "mayos_session_log.json"
    decoded = json.loads(payload.decode("utf-8"))
    session = decoded["sessions"][0]
    assert session["session_id"] == "s1"
    assert session["coach_debrief"] == "Debrief for s1"
    assert "_exercise_index" not in session
    exercise = session["exercises"][0]
    assert exercise["exercise_name"] == "reverse grip machine lat pulldown"
    entry = exercise["sets"][0]
    assert entry["e1rm_kg"] == 131.67  # 100 kg x 8 @ RPE 8.5
    assert entry["volume_kg"] == 800.0


def test_export_session_log_csv_filename_and_metrics():
    filename, payload = export_session_log(_stub_db([_raw_row()]), "alice", "csv")
    assert filename == "mayos_session_log.csv"
    text = payload.decode("utf-8")
    assert "131.67" in text and "800.0" in text
    assert "reverse grip machine lat pulldown" in text


def test_export_session_log_returns_none_when_empty():
    assert export_session_log(_stub_db([]), "alice", "csv") is None
