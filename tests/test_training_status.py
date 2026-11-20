"""Pure Weekly streak and Checkpoint calculations (#220; streak redefined in #743)."""

from datetime import date

import pytest

from service.attendance import is_expected_day
from service.training_status import (
    compute_training_status,
    mayos_workout_count,
    next_checkpoint_for,
    TrainingStatusFacts,
)


def _version(weekdays, effective_from="2026-09-26", timezone="UTC", created_at="2026-09-01"):
    return {
        "schedule_id": f"schedule-{effective_from}-{created_at}",
        "weekdays": weekdays,
        "timezone": timezone,
        "effective_from": effective_from,
        "created_at": created_at,
    }


def _status(*, today, performed=(), versions=(), pauses=(), frequency=3, mayos=0):
    return compute_training_status(
        TrainingStatusFacts(
            versions=list(versions),
            pauses=list(pauses),
            performed_dates=list(performed),
            weekly_frequency=frequency,
            local_today=today,
            mayos_workouts=mayos,
        )
    )


def test_saturday_starts_the_week():
    result = _status(today=date(2026, 9, 26), frequency=2)
    assert result.week_start == date(2026, 9, 26)
    assert result.week_target == 2


def test_is_expected_day_uses_the_shared_schedule_and_pause_rule():
    versions = [
        _version([2], effective_from="2026-09-29"),
        _version([3], effective_from="2026-09-30", created_at="2026-09-30"),
    ]
    assert is_expected_day(versions, [], date(2026, 9, 29))
    assert not is_expected_day(
        versions,
        [{"starts_on": "2026-09-29", "ends_on": "2026-09-29"}],
        date(2026, 9, 29),
    )
    assert not is_expected_day(versions, [], date(2026, 9, 28))


def test_full_week_pause_is_skipped_without_breaking_the_streak():
    result = _status(
        today=date(2026, 10, 9),
        performed=[date(2026, 9, day) for day in range(26, 31)]
        + [date(2026, 10, day) for day in (1, 2)],
        versions=[_version([1, 2, 3, 4, 5, 6, 7])],
        pauses=[{"starts_on": "2026-10-03", "ends_on": "2026-10-09"}],
    )
    assert result.week_target == 0
    assert result.weekly_streak == 1


def test_partial_pause_lowers_the_schedule_target():
    result = _status(
        today=date(2026, 10, 2),
        versions=[_version([6, 1, 3])],
        pauses=[{"starts_on": "2026-09-28", "ends_on": "2026-09-29"}],
    )
    assert result.week_target == 2


def test_schedule_change_midweek_changes_expected_days_for_later_dates():
    result = _status(
        today=date(2026, 10, 9),
        versions=[
            _version([6, 1], effective_from="2026-09-26", created_at="2026-09-01"),
            _version([3, 5], effective_from="2026-09-30", created_at="2026-09-30"),
        ],
        performed=[
            date(2026, 9, 26), date(2026, 9, 28), date(2026, 9, 30), date(2026, 10, 2),
            date(2026, 10, 7), date(2026, 10, 9),
        ],
    )
    assert result.week_target == 2
    assert result.week_done == 2
    assert result.weekly_streak == 2


def test_no_schedule_uses_program_frequency_for_every_week():
    result = _status(
        today=date(2026, 10, 2),
        performed=[date(2026, 9, 26), date(2026, 9, 28), date(2026, 9, 30)],
        frequency=3,
    )
    assert result.week_target == 3
    assert result.week_done == 3
    assert result.weekly_streak == 1


def test_one_workout_keeps_a_week_and_the_week_in_progress_never_breaks_it():
    # Since #743 a week counts with at least one workout, whatever the target.
    one_this_week = _status(
        today=date(2026, 9, 30),
        performed=[date(2026, 9, 19), date(2026, 9, 22), date(2026, 9, 26)],
        frequency=2,
    )
    none_yet = _status(
        today=date(2026, 9, 30),
        performed=[date(2026, 9, 19)],
        frequency=2,
    )
    assert (one_this_week.week_done, one_this_week.weekly_streak) == (1, 2)
    assert one_this_week.this_week_done is True
    assert (none_yet.weekly_streak, none_yet.this_week_done) == (1, False)


def test_a_finished_week_without_a_workout_breaks_the_streak():
    result = _status(
        today=date(2026, 10, 9),
        performed=[date(2026, 9, 19), date(2026, 10, 3)],
        frequency=2,
    )
    # The week of 26 Sep had no workout: only the current week counts.
    assert result.weekly_streak == 1
    assert result.longest_streak == 1


def test_longest_streak_survives_a_break():
    result = _status(
        today=date(2026, 10, 23),
        performed=[
            date(2026, 9, 5), date(2026, 9, 12), date(2026, 9, 19),
            date(2026, 10, 3), date(2026, 10, 17),
        ],
    )
    assert result.weekly_streak == 1
    assert result.longest_streak == 3


def test_a_fully_paused_current_week_is_reported_and_skipped():
    result = _status(
        today=date(2026, 10, 5),
        performed=[date(2026, 9, 26)],
        pauses=[{"starts_on": "2026-10-03", "ends_on": "2026-10-09"}],
    )
    assert result.week_paused is True
    assert result.weekly_streak == 1


def test_a_fully_paused_week_between_workouts_neither_breaks_nor_extends():
    result = _status(
        today=date(2026, 10, 12),
        performed=[date(2026, 9, 26), date(2026, 10, 10)],
        pauses=[{"starts_on": "2026-10-03", "ends_on": "2026-10-09"}],
    )
    assert result.weekly_streak == 2
    assert result.longest_streak == 2


def test_extra_workouts_count_toward_done():
    result = _status(
        today=date(2026, 10, 2),
        performed=[date(2026, 9, 26)] * 4,
        frequency=3,
    )
    assert result.week_done == 4
    assert result.weekly_streak == 1


def test_imported_workouts_are_subtracted_and_clamped_at_zero():
    assert mayos_workout_count(12, 9) == 3
    assert mayos_workout_count(4, 9) == 0
    assert mayos_workout_count(4, 0) == 4


@pytest.mark.parametrize(
    ("workouts", "expected"),
    [(0, 10), (10, 25), (99, 100), (100, 200), (250, 300)],
)
def test_checkpoint_sequence(workouts, expected):
    assert next_checkpoint_for(workouts) == expected
