"""Coach drill-down reads of an assigned player's training history (ticket #25).

Every read is gated by the catalog before the player's ledger is opened: the
assignment must belong to the authenticated coach and be active (ADR 014/015/025).
An unknown, revoked, or other coach's assignment is denied with one generic error,
so its existence is never revealed. Player-assistant chats are never read here.
"""

from typing import Any

from service import analytics as analytics_service
from service import coach_analytics
from service import dashboard as dashboard_service
from service.assignments import (  # noqa: F401  (DENIED_ERROR re-exported for routers)
    DENIED_ERROR,
    authorized_player_ledger,
)
from service.exercise_labels import ExerciseLabels, exercise_labels
from service.schedule import current_schedule
from service.workouts import is_historical_program

DEFAULT_RECENT_SESSIONS = 10


def schedule_and_pauses(db: Any, ledger: Any, ledger_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The player's current expected schedule and their upcoming/active pauses.

    Only the underlying ledger rows are read; the caller has already passed the
    assignment gate, so no new authorization is introduced here.
    """
    current, today = current_schedule(db, ledger_id, ledger=ledger)
    schedule = None
    if current is not None:
        schedule = {"weekdays": current["weekdays"], "timezone": current["timezone"]}
    pauses = [
        {"starts_on": pause["starts_on"], "ends_on": pause["ends_on"]}
        for pause in ledger.list_active_or_upcoming_training_pauses(ledger_id, today.isoformat())
    ]
    return schedule, pauses


def active_program(db: Any, coach_account_id: str, assignment_id: Any) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        program = ledger.get_active_program()
        has_draft = ledger.get_program_draft(str(assignment_id)) is not None
    return _active_program_response(
        db, program, has_draft, context["assignment"]["coach_account_id"]
    )


def _active_program_response(
    db: Any, program: Any, has_draft: bool, assignment_coach_id: str
) -> dict[str, Any]:
    if program is None:
        return {"program": None, "has_draft": has_draft}
    content = program.model_dump(
        exclude={"published_by_coach_account_id", "created_at"}
    )
    _enrich_program_exercises(db, content)
    content["provenance"] = (
        "coach"
        if program.published_by_coach_account_id == assignment_coach_id
        else "automatic"
    )
    content["active_since"] = program.created_at
    return {"program": content, "has_draft": has_draft}


def _enrich_program_exercises(db: Any, program_content: dict[str, Any]) -> None:
    exercises = [
        exercise
        for day in program_content["days"]
        for exercise in day["exercises"]
    ]
    labels_by_id = exercise_labels(
        db,
        (exercise["exercise_id"] for exercise in exercises),
    )
    for exercise in exercises:
        labels = labels_by_id.get(exercise["exercise_id"]) or ExerciseLabels()
        exercise.update(
            {
                "primary_muscle": labels.primary_muscle,
                "primary_action": labels.primary_action,
                "equipment_category": labels.equipment_category,
                "load_type": labels.load_type,
                "coach_equipment": labels.coach_equipment,
            }
        )


def _add_session_working_set(exercises: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    exercise_id = str(row["exercise_id"])
    exercise = exercises.get(exercise_id)
    if exercise is None:
        exercise = {
            "exercise_id": exercise_id,
            "name": row["exercise_name"],
            "sets": 0,
            "reps": 0,
            "volume_kg": 0.0,
        }
        exercises[exercise_id] = exercise
    exercise["sets"] += 1
    exercise["reps"] += int(row["reps"])
    exercise["volume_kg"] += float(row["weight_kg"]) * int(row["reps"])


def _group_session_exercises(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group working sets by session and exercise for coach history responses."""
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        exercises = grouped.setdefault(str(row["session_id"]), {})
        if not row["is_warmup"]:
            _add_session_working_set(exercises, row)
    return {
        session_id: sorted(
            exercises.values(),
            key=lambda exercise: (str(exercise["name"]).casefold(), exercise["exercise_id"]),
        )
        for session_id, exercises in grouped.items()
    }


def _apply_session_exercise_labels(db: Any, exercises: list[dict[str, Any]]) -> None:
    labels_by_id = exercise_labels(db, (exercise["exercise_id"] for exercise in exercises))
    for exercise in exercises:
        labels = labels_by_id.get(exercise["exercise_id"])
        exercise.update(
            {
                "image_path": labels.image_path if labels else None,
                "primary_muscle": labels.primary_muscle if labels else None,
                "primary_action": labels.primary_action if labels else None,
            }
        )


def _enrich_session_exercises(
    db: Any,
    latest_session: dict[str, Any] | None,
    sessions: list[dict[str, Any]],
) -> None:
    exercises = []
    if latest_session:
        exercises.extend(latest_session.get("exercises", []))
    for session in sessions:
        exercises.extend(session.get("exercises", []))
    _apply_session_exercise_labels(db, exercises)


def recent_sessions(
    ledger: Any,
    limit: int,
    *,
    session_rows: list[dict[str, Any]] | None = None,
    exercises_by_session: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Newest-first working-set summaries grouped from the ledger session log."""
    if session_rows is None:
        session_rows = ledger.get_session_log()
    if exercises_by_session is None:
        exercises_by_session = _group_session_exercises(session_rows)
    divergences_by_session = ledger.list_divergences_by_session()
    warmup_movements_by_session = ledger.list_warmup_movements_by_session()
    cardio_by_session = ledger.list_session_cardio_by_session()
    version_by_session = ledger.get_session_program_versions()
    audit_by_session = ledger.get_session_audit_metadata()
    sessions: dict[str, dict[str, Any]] = {}
    for row in session_rows:
        summary = sessions.get(row["session_id"])
        if summary is None:
            version_info = version_by_session.get(row["session_id"], {})
            audit = audit_by_session.get(row["session_id"], {})
            summary = {
                "session_id": row["session_id"],
                "session_date": row["session_date"],
                "split_name": row["split_name"],
                "readiness_score": row["readiness_score"],
                "program_version": version_info.get("program_version"),
                "active_program_version_at_sync": version_info.get("active_program_version_at_sync"),
                "is_historical_program": is_historical_program(
                    version_info.get("program_version"),
                    version_info.get("active_program_version_at_sync"),
                ),
                "uploaded_at": audit.get("uploaded_at"),
                "edited_at": audit.get("edited_at"),
                "corrections": audit.get("corrections", []),
                "exercises": exercises_by_session.get(row["session_id"], []),
                "sets_count": 0,
                "total_volume_kg": 0.0,
                "divergences": divergences_by_session.get(row["session_id"], []),
                "warmup_movements": warmup_movements_by_session.get(row["session_id"], []),
                "cardio": cardio_by_session.get(row["session_id"]),
            }
            sessions[row["session_id"]] = summary
        if not row["is_warmup"]:
            summary["sets_count"] += 1
            summary["total_volume_kg"] += float(row["weight_kg"]) * int(row["reps"])
    ordered = list(sessions.values())
    ordered.reverse()
    return ordered[: max(1, limit)]


def player_summary(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    days_lookback: int = 7,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> dict[str, Any] | None:
    """Identity, volume, latest session, and recent sessions for an assigned player."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        ledger_id = context["player"]["ledger_id"]
        schedule, pauses = schedule_and_pauses(db, ledger, ledger_id)
        session_rows = ledger.get_session_log()
        exercises_by_session = _group_session_exercises(session_rows)
        latest_session = ledger.get_latest_session_summary()
        if latest_session is not None:
            latest_session["is_historical_program"] = is_historical_program(
                latest_session.get("program_version"),
                latest_session.get("active_program_version_at_sync"),
            )
            latest_session["exercises"] = exercises_by_session.get(
                str(latest_session["session_id"]), []
            )
        recent = recent_sessions(
            ledger,
            DEFAULT_RECENT_SESSIONS,
            session_rows=session_rows,
            exercises_by_session=exercises_by_session,
        )
        _enrich_session_exercises(db, latest_session, recent)
        summary = {
            "player_username": context["player"]["username"],
            "started_at": context["assignment"]["started_at"],
            "status": context["assignment"]["status"],
            "volume": dashboard_service.volume_attribution(
                db, ledger_id, days_lookback=days_lookback, ledger=ledger
            ),
            "latest_session": latest_session,
            "recent_sessions": recent,
            "schedule": schedule,
            "pauses": pauses,
        }
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(
            coach_account_id, str(assignment_id), client=client
        ),
    )
    return summary


def player_personal_records(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    limit: int = 20,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> list[dict[str, Any]] | None:
    """The assigned player's most recent personal records, newest-first."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        records = dashboard_service.recent_personal_records(
            db, context["player"]["ledger_id"], limit=limit, ledger=ledger
        )
    labels_by_id = exercise_labels(db, (record["exercise_id"] for record in records))
    for record in records:
        labels = labels_by_id.get(record["exercise_id"])
        record.update(
            {
                "image_path": labels.image_path if labels else None,
                "primary_muscle": labels.primary_muscle if labels else None,
            }
        )
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(
            coach_account_id, str(assignment_id), client=client
        ),
    )
    return records


def player_exercises(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> list[dict[str, Any]] | None:
    """The distinct exercises the assigned player has logged."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        exercises = dashboard_service.logged_exercises(
            db, context["player"]["ledger_id"], ledger=ledger
        )
    labels_by_id = exercise_labels(db, (exercise["id"] for exercise in exercises))
    for exercise in exercises:
        labels = labels_by_id.get(exercise["id"])
        exercise.update(
            {
                "image_path": labels.image_path if labels else None,
                "primary_muscle": labels.primary_muscle if labels else None,
            }
        )
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(
            coach_account_id, str(assignment_id), client=client
        ),
    )
    return exercises


def player_exercise_history(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    exercise_id: str,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> dict[str, Any] | None:
    """Progression history, latest caption, and records for one logged exercise."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        ledger_id = context["player"]["ledger_id"]
        history = dashboard_service.exercise_history(db, ledger_id, exercise_id, ledger=ledger)
        history_payload = {
            "history": history,
            "caption": dashboard_service.latest_record_caption(history),
            "records": dashboard_service.exercise_records(db, ledger_id, exercise_id, ledger=ledger),
            "equipment": dashboard_service.exercise_equipment(db, exercise_id),
        }
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(
            coach_account_id, str(assignment_id), client=client
        ),
    )
    return history_payload
