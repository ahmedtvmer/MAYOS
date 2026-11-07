"""Player Food log reads and nutrient-only Coach/Roster inference (#478)."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph
from agent.player_tools import MAX_TOOL_RESULT_BYTES, build_player_read_tools
from service import coach_ai, coach_roster_ai, food_log, roster_snapshot, weight_history
from service.assignments import record_roster_ai_disclosure
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn
from tests.test_roster_snapshot import api, _assign, _make_coach  # noqa: F401


INSTANT = datetime(2026, 11, 7, 23, 30, tzinfo=UTC)
TODAY = date(2026, 11, 8)  # Pacific/Kiritimati, already tomorrow at this instant.
LIBRARY_NAME = "PRIVATE_LIBRARY_FOOD_478"
PERSONAL_NAME = "PRIVATE_PERSONAL_FOOD_478"
QUICK_INTERNAL_NAME = "PRIVATE_QUICK_INTERNAL_478"


def _insert(ledger, day, kind="library_food", name=LIBRARY_NAME, kcal=200, protein=20):
    nutrients = {"energy_kcal": kcal, "protein_g": protein,
                 "carbohydrate_g": 10, "fat_g": 5}
    quick = kind == "quick_add"
    if quick:
        nutrients.update(protein_g=None, carbohydrate_g=None, fat_g=None)
    entry = {
        "id": uuid4().hex, "entry_date": day.isoformat(), "kind": kind,
        "food_id": None if quick else "PRIVATE_FOOD_ID_478",
        "name": name, "arabic_name": "اسم طعام خاص",
        "logged_time": "12:30", "meal_label": "lunch",
        "grams": None if quick else 100, "quantity": None if quick else 100,
        "unit": None if quick else "grams", "portion_label": None,
        "portion_grams": None, "nutrients": nutrients,
        "nutrients_per_100g": None if quick else nutrients,
        "created_at": INSTANT.isoformat(),
    }
    with ledger.ledger_transaction():
        ledger.insert_food_log_entry(entry)


@pytest.fixture
def assigned_food_player(api, monkeypatch):  # noqa: F811
    client, db = api

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSTANT.astimezone(tz) if tz else INSTANT.replace(tzinfo=None)

    # Freeze the clock boundary; all date resolution still uses the real schedule.
    monkeypatch.setattr(weight_history, "datetime", FrozenDateTime)
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "foodassistantplayer")
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.append_training_schedule(
            player["ledger_id"], [1, 3, 5], "Pacific/Kiritimati",
            "2026-01-01", "2026-01-01T00:00:00Z",
        )
        _insert(ledger, TODAY)
        _insert(ledger, TODAY, "personal_food", PERSONAL_NAME, 300, 30)
        _insert(ledger, TODAY, "quick_add", QUICK_INTERNAL_NAME, 500)
        _insert(ledger, TODAY - timedelta(days=1), kcal=250, protein=25)
        _insert(ledger, TODAY - timedelta(days=13), kcal=70, protein=7)
        _insert(ledger, TODAY - timedelta(days=14), "personal_food", "TOO_OLD_FOOD", 8000)
        _insert(ledger, TODAY + timedelta(days=1), "personal_food", "FUTURE_FOOD", 9000)
        ledger.upsert_nutrition_adherence(TODAY, "roughly")
        ledger.replace_computed_nutrition_adherence(TODAY - timedelta(days=1), "on_target")
    return db, coach_id, player


def _tool(ledger):
    tools, _definitions = build_player_read_tools(ledger)
    return next(tool for tool in tools if tool.name == "get_player_food_log")


@pytest.mark.parametrize("mode", ["stream", "graph"])
@pytest.mark.parametrize(("query", "day", "expected_kcal"), [
    ("What did I eat today?", "today", 1000),
    ("What did I eat today? List it briefly.", "today", 1000),
    ("what did I eat yesterday", "yesterday", 250),
    ("أنا أكلت إيه النهارده؟", "today", 1000),
    ("أنا أكلت إيه امبارح؟", "yesterday", 250),
    ("ماذا أكلت اليوم؟", "today", 1000),
    ("ماذا تناولت أمس؟", "yesterday", 250),
])
def test_food_recall_pipeline_skips_exercise_history_655(
    assigned_food_player, monkeypatch, mode, query, day, expected_kcal
):
    db, _coach_id, player = assigned_food_player
    answer = "Here is your Food log." if query.isascii() else "ده سجل أكلك."
    model = ScriptedChatModel([
        ToolCallsTurn(calls=[{
            "name": "get_player_food_log", "args": {"day": day}, "id": "food-recall",
        }]),
        answer,
    ])
    monkeypatch.setattr(assistant_graph, "llm", model)
    state = {"messages": [HumanMessage(content=query)],
             "display_language": "en" if query.isascii() else "ar"}

    with db.open_ledger(player["ledger_id"]) as ledger:
        if mode == "stream":
            output = "".join(assistant_graph.stream_assistant_turn(state, ledger=ledger, store=db))
        else:
            state = assistant_graph.assistant_graph.invoke(
                state, config={"configurable": {"ledger": ledger, "store": db}}
            )
            output = state["response_content"]

    assert state["intent"] == "coaching_qa"
    assert output == state["response_content"] == answer
    tool_reply = next(
        message for message in model.calls[-1]["messages"] if message.type == "tool"
    )
    logged_day = json.loads(tool_reply.content)
    expected_date = TODAY if day == "today" else TODAY - timedelta(days=1)
    assert logged_day["date"] == expected_date.isoformat()
    assert logged_day["totals"]["energy_kcal"] == expected_kcal
    assert LIBRARY_NAME in {entry["name"] for entry in logged_day["entries"]}


@pytest.mark.parametrize("mode", ["stream", "graph"])
def test_exercise_history_pipeline_keeps_logged_comparison_655(fresh_store, mode):
    ledger = fresh_store.ledger
    for day, weight in [("2026-11-05", 75), ("2026-11-07", 80)]:
        ledger.log_workout_session(
            day, day, "Upper", f"{day}T10:00:00+00:00", f"{day}T11:00:00+00:00"
        )
        ledger.log_workout_set(f"set-{day}", day, "25", 1, weight, 8, 8)
    state = {"messages": [HumanMessage(content="how did I do on bench press last session?")]}

    if mode == "stream":
        output = "".join(assistant_graph.stream_assistant_turn(
            state, ledger=ledger, store=fresh_store
        ))
    else:
        state = assistant_graph.assistant_graph.invoke(
            state, config={"configurable": {"ledger": ledger, "store": fresh_store}}
        )
        output = state["response_content"]

    assert state["intent"] == "exercise_history"
    assert "80 kg × 8 reps @ RIR 2" in output
    assert "Baseline: 2026-11-05" in output
    assert "best load +5 kg" in output
    assert "requested time period is unavailable" not in output


def test_player_reads_own_day_and_personal_names_without_writing(assigned_food_player):
    db, _coach_id, player = assigned_food_player
    with db.open_ledger("unrelated-food-player") as other:
        _insert(other, TODAY, "personal_food", "OTHER_PLAYER_FOOD", 9999)
    with db.open_ledger(player["ledger_id"]) as ledger:
        before = list(ledger.conn.iterdump())
        payload = _tool(ledger).invoke({})
        result = json.loads(payload)
        assert list(ledger.conn.iterdump()) == before
        api_day = food_log.read_day(ledger, TODAY, TODAY)

    assert result["date"] == TODAY.isoformat()
    assert result["totals"] == api_day["totals"] == {
        "energy_kcal": 1000, "protein_g": 50, "carbohydrate_g": 20, "fat_g": 10,
    }
    assert sorted(entry["name"] for entry in result["entries"]) == sorted([
        LIBRARY_NAME, PERSONAL_NAME, "Quick add",
    ])
    assert result["entry_count"] == 3
    assert result["next_offset"] is None
    assert result["entries"][0]["time"] == "12:30"
    assert PERSONAL_NAME in payload
    for secret in (QUICK_INTERNAL_NAME, "OTHER_PLAYER_FOOD", "FUTURE_FOOD", "TOO_OLD_FOOD",
                   "PRIVATE_FOOD_ID_478"):
        assert secret not in payload
    assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES


@pytest.mark.parametrize(("day", "expected_kcal"), [
    ("yesterday", 250), ((TODAY - timedelta(days=13)).isoformat(), 70),
    ((TODAY - timedelta(days=2)).isoformat(), 0),
])
def test_player_recent_dates_include_boundary_and_empty_day(assigned_food_player, day, expected_kcal):
    db, _coach_id, player = assigned_food_player
    with db.open_ledger(player["ledger_id"]) as ledger:
        result = json.loads(_tool(ledger).invoke({"day": day}))
    assert result["status"] == "ok"
    assert result["totals"]["energy_kcal"] == expected_kcal
    if expected_kcal == 0:
        assert result["entries"] == []


@pytest.mark.parametrize("day", [
    (TODAY - timedelta(days=14)).isoformat(), (TODAY + timedelta(days=1)).isoformat(),
    "2026-02-30", "not-a-date",
])
def test_player_rejects_dates_outside_visible_recent_window(assigned_food_player, day):
    db, _coach_id, player = assigned_food_player
    with db.open_ledger(player["ledger_id"]) as ledger:
        result = json.loads(_tool(ledger).invoke({"day": day}))
    assert result == {"status": "invalid_date", "earliest_date": "2026-10-26", "today": "2026-11-08"}


def test_player_pagination_preserves_whole_day_totals_and_all_entries(assigned_food_player):
    db, _coach_id, player = assigned_food_player
    day = TODAY - timedelta(days=2)
    names = {f"طعام خاص طويل {index} " + "م" * 100 for index in range(35)}
    with db.open_ledger(player["ledger_id"]) as ledger:
        for name in names:
            _insert(ledger, day, "personal_food", name, 10, 1)
        tool = _tool(ledger)
        offset = 0
        seen = []
        for _ in range(len(names)):
            payload = tool.invoke({"day": day.isoformat(), "offset": offset})
            assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
            page = json.loads(payload)
            assert page["status"] == "ok"
            assert page["totals"]["energy_kcal"] == 350
            seen.extend(entry["name"] for entry in page["entries"])
            if page["next_offset"] is None:
                break
            assert page["next_offset"] > offset
            offset = page["next_offset"]
    assert offset > 0
    assert len(seen) == len(names)
    assert set(seen) == names


def test_single_oversized_name_is_marked_and_keeps_totals_available(assigned_food_player):
    db, _coach_id, player = assigned_food_player
    day = TODAY - timedelta(days=2)
    with db.open_ledger(player["ledger_id"]) as ledger:
        _insert(ledger, day, "personal_food", "م" * 5000)
        payload = _tool(ledger).invoke({"day": day.isoformat()})
    result = json.loads(payload)
    assert len(payload.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
    assert result["entries"][0]["name"] == "م" * 200
    assert result["entries"][0]["name_truncated"] is True
    assert result["totals"]["energy_kcal"] == 200
    assert result["next_offset"] is None


def _assert_nutrient_only(days, window):
    assert len(days) == window
    assert days[0]["date"] == (TODAY - timedelta(days=window - 1)).isoformat()
    assert days[-1] == {
        "date": TODAY.isoformat(), "energy_kcal": 1000, "protein_g": 50,
        "adherence": "roughly", "adherence_source": "answered",
    }
    assert days[-2] == {
        "date": (TODAY - timedelta(days=1)).isoformat(), "energy_kcal": 250,
        "protein_g": 25, "adherence": "on_target", "adherence_source": "computed",
    }
    assert days[-3]["energy_kcal"] is None
    for day in days:
        assert set(day) == {"date", "energy_kcal", "protein_g", "adherence", "adherence_source"}


def _assert_no_food_details(payload):
    for secret in (LIBRARY_NAME, PERSONAL_NAME, QUICK_INTERNAL_NAME, "اسم طعام خاص",
                   "PRIVATE_FOOD_ID_478", "FUTURE_FOOD", "TOO_OLD_FOOD",
                   "nutrients_per_100g", "personal_food", "portion_grams"):
        assert secret not in payload


def test_coach_context_and_prompt_contain_only_daily_totals_with_adherence(assigned_food_player):
    db, coach_id, player = assigned_food_player
    facts = coach_ai.gather_player_context(db, coach_id, player["assignment_id"], now=INSTANT)
    _assert_nutrient_only(facts["nutrition"]["food_log_days"], 14)
    assert facts["nutrition"]["food_log_days"][0]["energy_kcal"] == 70
    _assert_no_food_details(json.dumps(facts, ensure_ascii=False))
    messages = coach_ai.build_messages(coach_ai.render_context(facts), "What did they eat?", [])
    payload = coach_ai.canonical_messages_text(messages)
    _assert_no_food_details(payload)
    assert "1000 kcal, 50 g protein" in payload
    assert "2026-11-07" in payload
    assert "computed" in payload
    assert "no Food log entries" in payload


def test_roster_snapshot_and_hosted_prompt_have_seven_days_without_food_details(assigned_food_player):
    db, coach_id, _player = assigned_food_player
    response = roster_snapshot.roster_signal_snapshot(db, coach_id, now=INSTANT)
    signal = response["snapshot"]["players"][0]
    _assert_nutrient_only(signal["food_log_days_7d"], 7)
    _assert_no_food_details(json.dumps(response, ensure_ascii=False))
    prepared = coach_roster_ai.prepare_roster_question(response, "Who met their targets?", [])
    payload = coach_ai.canonical_messages_text(prepared.messages)
    _assert_no_food_details(payload)
    assert '"energy_kcal":1000.0' in payload
    assert '"protein_g":50.0' in payload
    assert '"adherence_source":"answered"' in payload


def test_roster_drops_injected_food_details_inside_daily_totals(assigned_food_player):
    db, coach_id, _player = assigned_food_player
    response = roster_snapshot.roster_signal_snapshot(db, coach_id, now=INSTANT)
    poisoned = deepcopy(response)
    signal = poisoned["snapshot"]["players"][0]
    signal["food_log_days_7d"][-1].update({
        "name": PERSONAL_NAME, "personal_foods": [{"name": PERSONAL_NAME}],
        "entries": [{"name": LIBRARY_NAME}], "food_id": "PRIVATE_FOOD_ID_478",
    })
    prepared = coach_roster_ai.prepare_roster_question(poisoned, "Compare daily totals", [])
    payload = coach_ai.canonical_messages_text(prepared.messages)
    _assert_no_food_details(payload)
    assert '"energy_kcal":1000.0' in payload


def test_previous_roster_disclosure_excludes_player_until_acknowledged(assigned_food_player):
    db, coach_id, player = assigned_food_player
    with db.catalog_transaction():
        db.catalog_conn.execute(
            "UPDATE assignments SET roster_ai_disclosure_version='2' WHERE assignment_id=?",
            (player["assignment_id"],),
        )
    response = roster_snapshot.roster_signal_snapshot(db, coach_id, now=INSTANT)
    assert response["snapshot"]["players"] == []
    assert response["excluded_for_missing_disclosure"] == 1
    record_roster_ai_disclosure(db, player["account_id"])
    renewed = roster_snapshot.roster_signal_snapshot(db, coach_id, now=INSTANT)
    _assert_nutrient_only(renewed["snapshot"]["players"][0]["food_log_days_7d"], 7)
