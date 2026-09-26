"""Pure attendance evaluation tests (ticket #31, ADR 030).

Exercises ``service.attendance.evaluate_attendance`` without any database: grace
boundaries, timezone-local days at one UTC instant, pauses, effective-dated
schedule versions, one-workout-per-day matching, the earliest eligible day, and
the evaluation window.
"""

from datetime import UTC, date, datetime

from service.attendance import evaluate_attendance
from service.schedule import local_date_in


def _version(weekdays, timezone="UTC", effective_from="2026-01-01", created_at="2026-01-01T00:00:00+00:00"):
    return {
        "schedule_id": f"v-{effective_from}-{created_at}",
        "weekdays": weekdays,
        "timezone": timezone,
        "effective_from": effective_from,
        "created_at": created_at,
    }


def _now(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


MONDAY = date(2026, 9, 7)
THURSDAY = date(2026, 9, 10)


def test_performed_next_local_day_satisfies_due_expected_day():
    result = evaluate_attendance(
        versions=[_version([THURSDAY.isoweekday()], effective_from=THURSDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 11)],
        window_start=THURSDAY,
        now=_now(date(2026, 9, 12)),
    )
    assert result.satisfied_days == (THURSDAY,)
    assert result.missed_days == ()
    assert result.trailing_streak_length == 0


def test_performed_two_local_days_later_does_not_satisfy():
    result = evaluate_attendance(
        versions=[_version([THURSDAY.isoweekday()], effective_from=THURSDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 12)],
        window_start=THURSDAY,
        now=_now(date(2026, 9, 12)),
    )
    assert result.satisfied_days == ()
    assert result.missed_days == (THURSDAY,)
    assert result.trailing_streak_length == 1


def test_expected_day_is_not_due_before_grace_ends():
    result = evaluate_attendance(
        versions=[_version([THURSDAY.isoweekday()], effective_from=THURSDAY.isoformat())],
        pauses=[],
        performed_dates=[],
        window_start=THURSDAY,
        now=_now(date(2026, 9, 11)),
    )
    assert result.local_today == date(2026, 9, 11)
    assert result.missed_days == ()
    assert result.trailing_streak_length == 0


def test_local_date_in_utc_plus_fourteen_rolls_to_next_day():
    # 2026-09-20T12:00Z is still the 20th in UTC but the 21st in UTC+14.
    instant = datetime(2026, 9, 20, 12, tzinfo=UTC)
    assert local_date_in(instant, "Pacific/Kiritimati") == date(2026, 9, 21)


def test_timezone_changes_local_today_at_the_same_utc_instant():
    instant = datetime(2026, 9, 20, 12, tzinfo=UTC)
    common = {
        "pauses": [],
        "performed_dates": [],
        "window_start": date(2026, 9, 1),
        "now": instant,
    }
    east = evaluate_attendance(
        versions=[_version([1, 2, 3, 4, 5, 6, 7], timezone="Pacific/Kiritimati")],
        **common,
    )
    west = evaluate_attendance(
        versions=[_version([1, 2, 3, 4, 5, 6, 7], timezone="Pacific/Honolulu")],
        **common,
    )
    assert east.local_today == date(2026, 9, 21)
    assert west.local_today == date(2026, 9, 20)
    assert east.trailing_streak_last == date(2026, 9, 19)
    assert west.trailing_streak_last == date(2026, 9, 18)
    assert east.trailing_streak_length == 19
    assert west.trailing_streak_length == 18


def test_pause_removes_expected_days_from_the_streak():
    without_pause = evaluate_attendance(
        versions=[_version([1, 2, 3, 4, 5, 6, 7], effective_from=MONDAY.isoformat())],
        pauses=[],
        performed_dates=[],
        window_start=MONDAY,
        now=_now(date(2026, 9, 10)),
    )
    with_pause = evaluate_attendance(
        versions=[_version([1, 2, 3, 4, 5, 6, 7], effective_from=MONDAY.isoformat())],
        pauses=[{"starts_on": MONDAY.isoformat(), "ends_on": MONDAY.isoformat()}],
        performed_dates=[],
        window_start=MONDAY,
        now=_now(date(2026, 9, 10)),
    )
    assert without_pause.trailing_streak_length == 2
    assert without_pause.trailing_streak_start == MONDAY
    assert MONDAY not in with_pause.expected_days
    assert with_pause.trailing_streak_length == 1
    assert with_pause.trailing_streak_start == date(2026, 9, 8)


def test_schedule_version_change_uses_the_then_effective_weekdays():
    later = date(2026, 9, 14)
    result = evaluate_attendance(
        versions=[
            _version([1], effective_from=MONDAY.isoformat(), created_at="2026-09-01T00:00:00+00:00"),
            _version([2], effective_from=later.isoformat(), created_at="2026-09-01T00:01:00+00:00"),
        ],
        pauses=[],
        performed_dates=[],
        window_start=MONDAY,
        now=_now(date(2026, 9, 23)),
    )
    assert MONDAY in result.expected_days
    assert later not in result.expected_days
    assert date(2026, 9, 15) in result.expected_days
    assert result.trailing_streak_start == MONDAY
    assert result.trailing_streak_last == date(2026, 9, 15)
    assert result.trailing_streak_length == 2


def test_one_workout_satisfies_only_the_earliest_eligible_day():
    result = evaluate_attendance(
        versions=[_version([1, 2], effective_from=MONDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 8)],
        window_start=MONDAY,
        now=_now(date(2026, 9, 10)),
    )
    assert result.satisfied_days == (MONDAY,)
    assert len(result.satisfied_days) == 1
    assert date(2026, 9, 8) in result.missed_days


def test_a_second_workout_satisfies_the_next_eligible_day():
    result = evaluate_attendance(
        versions=[_version([1, 2], effective_from=MONDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 7), date(2026, 9, 8)],
        window_start=MONDAY,
        now=_now(date(2026, 9, 9)),
    )
    assert result.satisfied_days == (MONDAY, date(2026, 9, 8))
    assert result.missed_days == ()


def test_days_before_the_window_start_are_ignored():
    result = evaluate_attendance(
        versions=[_version([1, 2, 3, 4, 5, 6, 7], effective_from=THURSDAY.isoformat())],
        pauses=[],
        performed_dates=[],
        window_start=THURSDAY,
        now=_now(date(2026, 9, 13)),
    )
    assert result.expected_days[0] == THURSDAY
    assert date(2026, 9, 9) not in result.expected_days
    assert result.trailing_streak_start == THURSDAY
    assert result.trailing_streak_length == 2


def test_two_workouts_on_one_local_day_satisfy_two_expected_days():
    # Monday and Tuesday are both expected; two workouts on Tuesday satisfy one
    # expected day each (the first takes Monday, the second Tuesday).
    result = evaluate_attendance(
        versions=[_version([1, 2], effective_from=MONDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 8), date(2026, 9, 8)],
        window_start=MONDAY,
        now=_now(date(2026, 9, 10)),
    )
    assert result.satisfied_days == (MONDAY, date(2026, 9, 8))
    assert result.missed_days == ()
    assert result.trailing_streak_length == 0


def test_a_satisfied_not_yet_due_day_breaks_the_trailing_missed_streak():
    # Today is Thursday: Monday and Tuesday are due and missed. A Thursday workout
    # satisfies Wednesday (not yet due) and must break the streak immediately.
    result = evaluate_attendance(
        versions=[_version([1, 2, 3], effective_from=MONDAY.isoformat())],
        pauses=[],
        performed_dates=[date(2026, 9, 10)],
        window_start=MONDAY,
        now=_now(date(2026, 9, 10)),
    )
    assert result.satisfied_days == (date(2026, 9, 9),)
    assert result.missed_days == (MONDAY, date(2026, 9, 8))
    assert result.trailing_streak_start is None
    assert result.trailing_streak_length == 0
