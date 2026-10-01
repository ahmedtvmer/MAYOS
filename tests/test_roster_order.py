"""Roster urgency order unit tests (ticket #118, CONTEXT.md "Roster urgency order").

Each key is asserted on its own plus its tie-break into the next one, so the
strict ordering (no weights) is pinned: lapsing alerts, other new alerts plus
pending requests, missed streak, follow-up bucket, last workout, username.
"""

from datetime import date

from service.roster_order import roster_urgency_key

TODAY = date(2026, 9, 28)


def _entry(**overrides):
    entry = {
        "assignment_id": "a1",
        "player_username": "p1",
        "alerts_new": 0,
        "alerts_new_lapsing": 0,
        "pending_requests": 0,
        "current_missed_streak": 0,
        "next_follow_up_on": None,
        "last_workout_on": None,
    }
    entry.update(overrides)
    return entry


def test_lapsing_then_other_alerts_and_pending_requests_rank_highest_first():
    lapsing = roster_urgency_key(_entry(alerts_new=1, alerts_new_lapsing=1), TODAY)
    other_alerts = roster_urgency_key(_entry(alerts_new=2), TODAY)
    assert lapsing < other_alerts

    both = roster_urgency_key(_entry(alerts_new=2, pending_requests=2), TODAY)
    alerts_only = roster_urgency_key(_entry(alerts_new=3), TODAY)
    requests_only = roster_urgency_key(_entry(pending_requests=3), TODAY)
    quiet = roster_urgency_key(_entry(), TODAY)

    # The sum is one key: three alerts and three requests rank equally.
    assert alerts_only == requests_only
    assert both < alerts_only
    assert quiet > requests_only


def test_other_alerts_plus_requests_break_equal_lapsing_count():
    fewer_other = roster_urgency_key(_entry(alerts_new=2, alerts_new_lapsing=1), TODAY)
    more_other = roster_urgency_key(
        _entry(alerts_new=3, alerts_new_lapsing=1, pending_requests=1), TODAY
    )
    assert more_other < fewer_other


def test_acknowledged_alerts_never_count():
    acknowledged = roster_urgency_key(_entry(alerts_new=0, alerts_acknowledged=9), TODAY)
    assert acknowledged == roster_urgency_key(_entry(), TODAY)


def test_missed_streak_breaks_the_alert_and_request_tie():
    long_streak = roster_urgency_key(_entry(alerts_new=1, current_missed_streak=4), TODAY)
    short_streak = roster_urgency_key(_entry(alerts_new=1, current_missed_streak=2), TODAY)
    no_streak = roster_urgency_key(_entry(alerts_new=1), TODAY)

    # A longer streak sorts first (its key is smaller).
    assert long_streak < short_streak < no_streak


def test_follow_up_buckets_are_overdue_then_today_then_not_due():
    overdue = roster_urgency_key(_entry(next_follow_up_on="2026-09-20"), TODAY)
    due_today = roster_urgency_key(_entry(next_follow_up_on="2026-09-28"), TODAY)
    future = roster_urgency_key(_entry(next_follow_up_on="2026-10-05"), TODAY)
    unscheduled = roster_urgency_key(_entry(next_follow_up_on=None), TODAY)

    assert overdue < due_today < future
    # No follow-up due yet and none scheduled share the last bucket; the
    # username key decides between them.
    assert future[3] == unscheduled[3] == 2


def test_earliest_overdue_follow_up_comes_first():
    earlier = roster_urgency_key(_entry(next_follow_up_on="2026-09-20"), TODAY)
    later = roster_urgency_key(_entry(next_follow_up_on="2026-09-27"), TODAY)
    assert earlier < later


def test_today_parameter_decides_overdue_due_and_not_due():
    entry = _entry(next_follow_up_on="2026-09-28")
    assert roster_urgency_key(entry, date(2026, 9, 27))[3] == 2
    assert roster_urgency_key(entry, TODAY)[3] == 1
    assert roster_urgency_key(entry, date(2026, 9, 29))[3] == 0


def test_follow_up_key_outranks_last_workout():
    overdue_recent = roster_urgency_key(
        _entry(next_follow_up_on="2026-09-20", last_workout_on="2026-09-27"), TODAY
    )
    not_due_ancient = roster_urgency_key(
        _entry(next_follow_up_on=None, last_workout_on="2020-01-01"), TODAY
    )
    assert overdue_recent < not_due_ancient


def test_last_workout_oldest_first_and_never_trained_before_any_date():
    never_trained = roster_urgency_key(_entry(last_workout_on=None), TODAY)
    oldest = roster_urgency_key(_entry(last_workout_on="2026-01-01"), TODAY)
    newest = roster_urgency_key(_entry(last_workout_on="2026-09-27"), TODAY)

    assert never_trained < oldest < newest


def test_username_breaks_the_final_tie():
    anna = roster_urgency_key(_entry(player_username="anna"), TODAY)
    bob = roster_urgency_key(_entry(player_username="bob"), TODAY)
    assert anna < bob
    # Nothing but the username differs.
    assert anna[0:6] == bob[0:6]


def test_every_key_only_breaks_ties_in_the_previous_one():
    """A better score on an earlier key wins outright, whatever the later keys say."""
    urgent = _entry(player_username="zzz", alerts_new=1, last_workout_on=None)
    calm = _entry(player_username="aaa", alerts_new=0, last_workout_on="2020-01-01")
    assert roster_urgency_key(urgent, TODAY) < roster_urgency_key(calm, TODAY)

    streaked = _entry(player_username="zzz", current_missed_streak=1)
    fresh = _entry(player_username="aaa", current_missed_streak=0, last_workout_on="2020-01-01")
    assert roster_urgency_key(streaked, TODAY) < roster_urgency_key(fresh, TODAY)


def test_sorting_rows_applies_the_whole_order():
    rows = [
        _entry(player_username="carol", last_workout_on="2026-09-01"),
        _entry(player_username="dave", next_follow_up_on="2026-09-20"),
        _entry(player_username="erin", alerts_new=2, pending_requests=1),
        _entry(player_username="bob", last_workout_on=None),
        _entry(player_username="alice", current_missed_streak=3),
    ]

    ordered = sorted(rows, key=lambda row: roster_urgency_key(row, TODAY))

    assert [row["player_username"] for row in ordered] == ["erin", "alice", "dave", "bob", "carol"]
