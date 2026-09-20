"""Dashboard telemetry queries."""

from typing import Any

from agent.progression_engine import get_exercise_progression_history, get_weekly_muscle_volume
from service._base import bind_user


def volume_attribution(db: Any, trainee_id: str, days_lookback: int = 7) -> dict[str, float]:
    bind_user(db, trainee_id)
    return get_weekly_muscle_volume(db, days_lookback=days_lookback)


def logged_exercises(db: Any, trainee_id: str) -> list[dict[str, str]]:
    bind_user(db, trainee_id)
    cursor = db.user_conn.cursor()
    cursor.execute("""
        SELECT DISTINCT e.id, e.name
        FROM workout_sets ws
        JOIN catalog.exercises e ON ws.exercise_id = e.id
        ORDER BY e.name ASC
    """)
    return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]


def exercise_history(db: Any, trainee_id: str, exercise_id: str) -> list[dict[str, Any]]:
    bind_user(db, trainee_id)
    return get_exercise_progression_history(db, exercise_id)


def latest_record_caption(history: list[dict[str, Any]]) -> str | None:
    if not history:
        return None
    last = history[-1]
    return (
        f"Latest Recorded: **{last['weight_kg']} kg × {last['reps']} reps @ RPE {last['rpe']}** "
        f"(e1RM: {last['e1rm']} kg)"
    )


def recent_personal_records(db: Any, trainee_id: str, limit: int = 20) -> list[dict[str, Any]]:
    bind_user(db, trainee_id)
    cursor = db.user_conn.cursor()
    cursor.execute(
        """
        SELECT pr.exercise_id, COALESCE(e.name, pr.exercise_id) AS name, pr.record_type,
               pr.reps, pr.value, pr.prev_value, pr.achieved_at, pr.session_id
        FROM personal_records pr
        LEFT JOIN catalog.exercises e ON e.id = pr.exercise_id
        ORDER BY pr.achieved_at DESC, pr.rowid DESC
        LIMIT ?
    """,
        (max(1, limit),),
    )
    return [dict(row) for row in cursor.fetchall()]


def exercise_records(db: Any, trainee_id: str, exercise_id: str) -> list[dict[str, Any]]:
    bind_user(db, trainee_id)
    cursor = db.user_conn.cursor()
    cursor.execute(
        """
        SELECT record_type, reps, value, prev_value, achieved_at, session_id
        FROM personal_records
        WHERE exercise_id = ?
        ORDER BY achieved_at DESC, rowid DESC
    """,
        (exercise_id,),
    )
    return [dict(row) for row in cursor.fetchall()]
