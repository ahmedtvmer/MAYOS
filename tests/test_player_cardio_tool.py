"""Player assistant Cardio reads use only the bound Player ledger."""

import json
from datetime import date, timedelta

import pytest

from agent.player_tools import MAX_TOOL_RESULT_BYTES, build_player_read_tools
from tests.test_player_chat_privacy import api, _register  # noqa: F401


def _cardio_tool(ledger):
    tools, _definitions = build_player_read_tools(ledger)
    return next(tool for tool in tools if tool.name == "get_player_cardio")


def _log_cardio(ledger, session_id, session_date, machine, minutes, **settings):
    ledger.log_workout_session(
        session_id, session_date, "Cardio", f"{session_date}T12:00:00Z",
        f"{session_date}T12:30:00Z",
    )
    ledger.log_session_cardio(session_id, [{
        "machine": machine, "minutes": minutes, **settings,
    }], f"{session_date}T12:30:00Z")


def test_player_cardio_tool_returns_week_and_recent_totals_read_only(api, monkeypatch):
    client, db = api
    username = "assistant-cardio-reader"
    _register(client, username)
    monkeypatch.setattr("agent.player_tools.player_local_date", lambda *_args: date(2026, 11, 15))

    with db.open_ledger(username) as ledger:
        _log_cardio(ledger, "cardio-this-week", "2026-11-14", "treadmill", 25,
                    speed_kmh=5.5, incline_pct=4.0, calories_kcal=140,
                    calories_are_estimate=True)
        _log_cardio(ledger, "cardio-last-week", "2026-11-13", "bike", 15,
                    level=6, watts=120, distance_m=4200)
        _log_cardio(ledger, "cardio-too-old", "2026-10-31", "rower", 60,
                    watts=180)
        changes = ledger.conn.total_changes
        ledger.conn.execute("PRAGMA query_only=ON")
        response = json.loads(_cardio_tool(ledger).invoke({}))
        assert ledger.conn.total_changes == changes

    assert response["status"] == "ok"
    assert response["this_week"] == {
        "start_date": "2026-11-14", "minutes": 25, "sessions": 1,
    }
    assert response["last_7_days"] == {
        "start_date": "2026-11-09", "minutes": 40, "sessions": 2,
    }
    assert response["last_14_days"] == {
        "start_date": "2026-11-02", "minutes": 40, "sessions": 2,
    }
    assert response["sessions"][0]["calories_kcal"] == 140
    assert response["sessions"][0]["calories_are_estimate"] is True
    assert [(session["date"], session["entries"][0]["machine"],
             session["entries"][0]["minutes"]) for session in response["sessions"]] == [
        ("2026-11-14", "treadmill", 25), ("2026-11-13", "bike", 15),
    ]
    treadmill = response["sessions"][0]["entries"][0]
    assert treadmill["speed_kmh"] == 5.5 and treadmill["incline_pct"] == 4.0
    assert treadmill["calories_kcal"] == 140 and treadmill["calories_are_estimate"] is True
    bike = response["sessions"][1]["entries"][0]
    assert bike["level"] == 6 and bike["watts"] == 120 and bike["distance_m"] == 4200
    assert response["next_offset"] is None


def test_player_cardio_tool_reports_empty_window_and_never_reads_another_player(api, monkeypatch):
    client, db = api
    own_username, other_username = "assistant-cardio-empty", "assistant-cardio-private"
    _register(client, own_username)
    _register(client, other_username)
    monkeypatch.setattr("agent.player_tools.player_local_date", lambda *_args: date(2026, 11, 15))

    with db.open_ledger(other_username) as other_ledger:
        _log_cardio(other_ledger, "other-private-cardio", "2026-11-15",
                    "bike", 90)
    with db.open_ledger(own_username) as own_ledger:
        own_ledger.conn.execute("PRAGMA query_only=ON")
        response = json.loads(_cardio_tool(own_ledger).invoke({}))

    assert response["status"] == "no_data"
    assert response["this_week"]["minutes"] == 0
    assert response["last_7_days"]["minutes"] == 0
    assert response["last_14_days"]["minutes"] == 0
    assert response["session_count"] == 0
    assert response["sessions"] == []


@pytest.mark.parametrize(("requested", "expected"), [
    ("today", "2026-11-16"), ("yesterday", "2026-11-15"),
    ("2026-11-14", "2026-11-14"), ("2026-11-03", "2026-11-03"),
    ("2026-11-02", None), ("2026-11-17", None), ("2026-02-30", None),
])
def test_cardio_day_scope_excludes_other_dates_and_validates_recent_window(
    api, monkeypatch, requested, expected,
):
    client, db = api
    username = "cardio-day-scope"
    _register(client, username)
    monkeypatch.setattr("agent.player_tools.player_local_date", lambda *_: date(2026, 11, 16))
    with db.open_ledger(username) as ledger:
        for day in ("2026-11-03", "2026-11-14", "2026-11-15", "2026-11-16"):
            _log_cardio(ledger, f"day-{day}", day, "bike", 17)
        ledger.conn.execute("PRAGMA query_only=ON")
        payload = _cardio_tool(ledger).invoke({"day": requested})
    result = json.loads(payload)
    assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
    if expected is None:
        assert result["status"] == "invalid_date" and result["next_offset"] is None
    else:
        assert result["window"] == {"start_date": expected, "end_date": expected,
                                    "minutes": 17, "sessions": 1}
        assert [session["date"] for session in result["sessions"]] == [expected]
        assert result["session_count"] == 1
        assert not {"this_week", "last_7_days", "last_14_days"}.intersection(result)


# Empty, small, byte boundary, oversized first/later sessions, multiple pages.
@pytest.mark.parametrize("entry_counts", [
    [], [1], [8], [20], [1, 20], [20, 1], [8, 8], [8, 8, 8, 8],
    [1] * 20, [20] * 3,
    [2] * 15, [3] * 8, [4] * 8, [10] * 3, [12] * 4,
    [1, 8, 20], [8, 1, 20], [20, 1, 8], [8, 20, 8], [20, 8, 20],
])
def test_cardio_pages_advance_or_explicitly_terminate_when_session_exceeds_cap(
    api, monkeypatch, entry_counts,
):
    client, db = api
    username = "cardio-page-progress"
    _register(client, username)
    today = date(2026, 11, 16)
    monkeypatch.setattr("agent.player_tools.player_local_date", lambda *_: today)
    with db.open_ledger(username) as ledger:
        for index, count in enumerate(entry_counts):
            day = (today - timedelta(days=index % 3)).isoformat()
            session_id = f"oversized-{index:02}"
            ledger.log_workout_session(session_id, day, "Cardio", f"{day}T10:00:00Z",
                                       f"{day}T11:00:00Z")
            ledger.log_session_cardio(session_id, [{
                "machine": "treadmill", "minutes": 30, "speed_kmh": 5.123456789,
                "incline_pct": 4.987654321, "level": 5, "watts": 120, "distance_m": 2000,
                "calories_kcal": 140, "calories_are_estimate": True,
            } for _ in range(count)], f"{day}T11:00:00Z")
        ledger.conn.execute("PRAGMA query_only=ON")
        tool = _cardio_tool(ledger)
        offset, returned = 0, []
        for _ in range(len(entry_counts) + 1):
            payload = tool.invoke({"offset": offset})
            result = json.loads(payload)
            assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
            assert result["window"]["minutes"] == sum(entry_counts) * 30
            assert result["session_count"] == len(entry_counts)
            returned.extend(result["sessions"])
            next_offset = result["next_offset"]
            if next_offset is None:
                break
            assert next_offset > offset
            assert result["sessions"]
            offset = next_offset
        else:
            pytest.fail("Cardio pagination did not terminate")
    if 20 in entry_counts:
        assert result["status"] == "truncated"
        assert result["next_offset"] is None
        assert result["truncation_reason"] == "cardio_session_exceeds_result_limit"
    else:
        assert result["status"] == ("ok" if entry_counts else "no_data")
        assert len(returned) == len(entry_counts)
        assert sum(len(session["entries"]) for session in returned) == sum(entry_counts)
