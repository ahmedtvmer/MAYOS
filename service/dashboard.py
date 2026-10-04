"""Dashboard telemetry queries."""

from datetime import UTC, datetime, date, timedelta
from typing import Any

from agent.progression_engine import get_exercise_progression_history, get_weekly_muscle_volume
from core.effort import rir_label
from database.exercise_resolution import exercise_display_join, exercise_display_name_sql
from database.exercise_resolution import resolve_exercise_display_row
from service._base import ledger_scope


def volume_attribution(db: Any, ledger_id: str, days_lookback: int = 7, ledger: Any | None = None) -> dict[str, float]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        return get_weekly_muscle_volume(ledger, days_lookback=days_lookback)


def working_set_volume(
    db: Any, ledger_id: str, days_lookback: tuple[int, ...] = (7, 28), ledger: Any | None = None
) -> dict[int, float]:
    """Working-set tonnage (kg) per lookback window, from one query pass.

    Each window starts at ``now - days_lookback`` (the same cutoff rule
    ``get_weekly_muscle_volume`` uses), so ``working_set_volume(..., (7,))[7]``
    is this week's tonnage. One pass over the sets keeps the coach-AI context
    from querying the same ledger twice for two windows.
    """
    windows = tuple(sorted({int(days) for days in days_lookback}))
    now = datetime.now(UTC)
    cutoffs = {days: (now - timedelta(days=days)).date() for days in windows}
    earliest = min(cutoffs.values()).isoformat()
    with ledger_scope(db, ledger, ledger_id) as open_ledger:
        cursor = open_ledger.conn.cursor()
        cursor.execute(
            """
            SELECT s.session_date, ws.weight_kg, ws.reps
            FROM workout_sets ws
            JOIN workout_sessions s ON ws.session_id = s.id
            WHERE ws.is_warmup = 0 AND s.session_date >= ?
        """,
            (earliest,),
        )
        rows = cursor.fetchall()
    totals = {days: 0.0 for days in windows}
    for session_date, weight_kg, reps in rows:
        performed = date.fromisoformat(str(session_date))
        tonnage = float(weight_kg) * int(reps)
        for days, cutoff in cutoffs.items():
            if performed >= cutoff:
                totals[days] += tonnage
    return totals


def logged_exercises(db: Any, ledger_id: str, ledger: Any | None = None) -> list[dict[str, str]]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        cursor = ledger.conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT ws.exercise_id AS id,
                   {exercise_display_name_sql('ws.exercise_id')} AS name
            FROM workout_sets ws
            {exercise_display_join('ws.exercise_id')}
            ORDER BY name ASC
        """)
        return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]


def exercise_history(
    db: Any, ledger_id: str, exercise_id: str, ledger: Any | None = None
) -> list[dict[str, Any]]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        return get_exercise_progression_history(ledger, exercise_id)


def exercise_equipment(db: Any, exercise_id: str) -> str | None:
    """The resolved exercise equipment for a history payload, when available."""
    exercise = resolve_exercise_display_row(db, exercise_id)
    return exercise.get("equipment") if exercise is not None else None


def latest_record_caption(history: list[dict[str, Any]]) -> str | None:
    if not history:
        return None
    last = history[-1]
    return (
        f"Latest Recorded: **{last['weight_kg']} kg × {last['reps']} reps"
        f" @ RIR {rir_label(last.get('rpe'))}** (e1RM: {last['e1rm']} kg)"
    )


def recent_personal_records(
    db: Any, ledger_id: str, limit: int = 20, ledger: Any | None = None
) -> list[dict[str, Any]]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        cursor = ledger.conn.cursor()
        cursor.execute(
            f"""
            SELECT pr.exercise_id, {exercise_display_name_sql('pr.exercise_id')} AS name, pr.record_type,
                   pr.reps, pr.value, pr.prev_value, pr.achieved_at, pr.session_id
            FROM personal_records pr
            {exercise_display_join('pr.exercise_id')}
            ORDER BY pr.achieved_at DESC, pr.rowid DESC
            LIMIT ?
        """,
            (max(1, limit),),
        )
        return [dict(row) for row in cursor.fetchall()]


def exercise_records(
    db: Any, ledger_id: str, exercise_id: str, ledger: Any | None = None
) -> list[dict[str, Any]]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        cursor = ledger.conn.cursor()
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
