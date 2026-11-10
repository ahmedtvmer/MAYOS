"""Recommendation eligibility and truthful history through HTTP (#275)."""

import json

import pytest
from fastapi.testclient import TestClient

from svc.app import create_app
from svc.dependencies import get_db
from tests.test_coach_programs import _assigned_player
from tests.test_program_substitution_api import (
    api,
    _exercise,
    _make_player_with_program,
    _program,
)


def _injury(client, headers, area):
    response = client.post(
        "/profile/injuries", headers=headers,
        json={"body_area": area, "description": "Physician review needed"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _clearance(ledger, injury, exercise_id, name, verdict, note=None):
    record, created = ledger.create_exercise_clearance(
        injury_id=injury["id"], exercise_id=exercise_id, exercise_name=name,
        original_wording=f"Physician advice for {name}", verdict=verdict, note=note,
    )
    assert created
    return record


def _swap(client, headers, source, replacement):
    return client.post(
        "/programs/active/substitutions", headers=headers,
        json={"day_name": "Full A", "exercise_id": source, "replacement_exercise_id": replacement},
    )


@pytest.mark.parametrize("verdict", [None, "not_cleared"])
def test_replace_excludes_restricted_candidates_and_applies_a_valid_alternative(api, verdict):
    client, db = api
    headers = _make_player_with_program(client, db)
    # Only Squat is prescribed, leaving a real alternative available to apply.
    program = _program().model_dump()
    program["days"][0]["exercises"] = [_exercise("sq", "Squat").model_dump()]
    program["days"][0]["exercises"][0]["suggested_substitutes"] = [
        {"exercise_id": "ohp", "exercise_name": "Overhead Press"},
        {"exercise_id": "bp", "exercise_name": "Bench Press"},
    ]
    db.ledger.save_training_program(program)
    # Unclassified exercises conflict with every Movement restriction, so the
    # alternative needs its curated action to be offered under "Overhead pressing".
    with db.catalog_transaction():
        db.catalog_conn.execute(
            "INSERT OR REPLACE INTO exercise_curated_fields (exercise_id, primary_muscle, primary_action) "
            "VALUES ('bp', 'Chest', 'Shoulder Horizontal Adduction')"
        )
    injury = _injury(client, headers, "shoulder" if verdict is None else None)
    if verdict:
        _clearance(db.ledger, injury, "ohp", "Overhead Press", verdict)
    db.ledger.upsert_player_profile({"movement_restrictions": ["Overhead pressing"]})

    browse = client.get(
        "/workouts/exercises", headers=headers,
        params={"replacing_exercise_id": "sq", "filter_equipment_access": True},
    )
    assert browse.status_code == 200, browse.text
    offered = {row["id"] for row in browse.json()["exercises"]}
    assert "ohp" not in offered
    assert "bp" in offered
    active = client.get("/programs/active", headers=headers).json()
    assert active["days"][0]["exercises"][0]["suggested_substitutes"] == [
        {"exercise_id": "bp", "exercise_name": "Bench Press"},
    ]
    logging_browse = client.get(
        "/workouts/exercises", headers=headers,
        params={"query": "Overhead Press", "replacing_exercise_id": "sq", "for_logging": True},
    )
    assert logging_browse.status_code == 200, logging_browse.text
    assert "ohp" in {row["id"] for row in logging_browse.json()["exercises"]}
    refused = _swap(client, headers, "sq", "ohp")
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "clearance_excluded"
    applied = _swap(client, headers, "sq", "bp")
    assert applied.status_code == 200, applied.text
    assert applied.json()["days"][0]["exercises"][0]["exercise_id"] == "bp"


@pytest.mark.parametrize("verdict", [None, "not_cleared"])
def test_existing_exercise_is_flagged_loggable_and_eligible_after_resolution(api, verdict):
    client, db = api
    headers = _make_player_with_program(client, db)
    injury = _injury(client, headers, "knee" if verdict is None else None)
    if verdict:
        _clearance(db.ledger, injury, "sq", "Squat", verdict)
    active = client.get("/programs/active", headers=headers)
    assert active.status_code == 200, active.text
    assert active.json()["version"] == 1
    assert active.json()["days"][0]["exercises"][0]["clearance_status"] == (verdict or "unverified")
    # Search without a Replace scope remains usable for truthful logging.
    search = client.get("/workouts/exercises", headers=headers, params={"query": "Squat"})
    assert "sq" in {row["id"] for row in search.json()["exercises"]}
    committed = client.post(
        "/workouts/sessions", headers=headers,
        json={"day_order": 1, "readiness": 4, "sets": [{
            "exercise": active.json()["days"][0]["exercises"][0],
            "sets": [{"weight_kg": 60, "reps": 7, "rpe": 8}],
        }]},
    )
    assert committed.status_code == 201, committed.text
    exported = client.get("/workouts/sessions/export.json", headers=headers)
    assert exported.status_code == 200, exported.text
    logged = exported.json()["sessions"][0]["exercises"][0]
    assert logged["exercise_id"] == "sq"
    assert logged["sets"][0]["weight_kg"] == 60
    assert logged["sets"][0]["reps"] == 7

    resolved = client.put(
        f"/profile/injuries/{injury['id']}", headers=headers,
        json={"body_area": injury["body_area"], "description": injury["description"], "status": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    refreshed = client.get("/programs/active", headers=headers).json()
    assert refreshed["version"] == 1
    assert refreshed["days"][0]["exercises"][0]["clearance_status"] is None
    eligible = _swap(client, headers, "sq", "ohp")
    assert eligible.status_code == 200, eligible.text
    restored = _swap(client, headers, "ohp", "sq")
    assert restored.status_code == 200, restored.text


def test_unmatched_wording_excludes_nothing(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    injury = _injury(client, headers, None)
    _clearance(db.ledger, injury, None, "Overhead Press", "not_cleared")
    assert _swap(client, headers, "sq", "ohp").status_code == 200


def test_legacy_profile_injury_write_flags_the_existing_program_without_rebuilding(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    db.ledger.upsert_player_profile({"injuries_or_limitations": "None"})
    changed = client.patch(
        "/profile", headers=headers, json={"injuries_or_limitations": "knee pain"},
    )
    assert changed.status_code == 200, changed.text
    active = client.get("/programs/active", headers=headers)
    assert active.status_code == 200, active.text
    assert active.json()["version"] == 1
    assert active.json()["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert active.json()["days"][0]["exercises"][0]["clearance_status"] == "unverified"


def test_cleared_with_limits_remains_eligible_and_assistant_reads_the_note(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    shoulder = _injury(client, headers, "shoulder")
    _clearance(db.ledger, shoulder, "ohp", "Overhead Press", "cleared_with_limits", "Light weights only")
    assert _swap(client, headers, "sq", "ohp").status_code == 200
    active = client.get("/programs/active", headers=headers).json()
    overhead = active["days"][0]["exercises"][0]
    assert overhead["clearance_status"] == "cleared_with_limits"
    assert overhead["clearance_limit_notes"] == ["Light weights only"]
    # This is the same existing read tool exposed to assistant chat, not a new tool.
    from agent.player_tools import build_player_read_tools
    tools, _ = build_player_read_tools(db.ledger, db)
    injuries_tool = next(tool for tool in tools if tool.name == "get_player_injuries")
    facts = json.loads(injuries_tool.invoke({}))
    reported = [row for record in facts["injuries"] for row in record["clearances"]]
    assert any(
        row["exercise_name"] == "Overhead Press"
        and row["note"] == "Light weights only"
        for row in reported
    )
    program_tool = next(tool for tool in tools if tool.name == "get_active_program")
    program_facts = json.loads(program_tool.invoke({"exercise_id": "ohp"}))
    assert program_facts["exercise_clearance_flags"]["exercises"] == [{
        "exercise_name": "Overhead Press", "status": "cleared_with_limits",
        "excluded": False, "limit_notes": ["Light weights only"],
    }]
    assert _swap(client, headers, "ohp", "sq").status_code == 200
    assert _swap(client, headers, "sq", "ohp").status_code == 200


def test_program_read_round_trips_through_coach_publish_without_clearance_metadata(api):
    client, db = api
    coach_headers, player_headers, assignment_id, coach_id, _ = _assigned_player(
        (client, db, None)
    )
    with db.open_ledger("p1") as ledger:
        program = _program().model_dump()
        program["days"][0]["warmup_exercises"] = [{
            "exercise_id": "row",
            "equipment": "Cable",
            "exercise_name": "Easy row",
            "sets": 2,
            "reps": 12,
            "rest_seconds": 30,
        }]
        ledger.save_training_program(
            program, published_by_coach_account_id=coach_id
        )

    injury = _injury(client, player_headers, None)
    with db.open_ledger("p1") as ledger:
        _clearance(ledger, injury, "sq", "Squat", "not_cleared")
        _clearance(
            ledger, injury, "row", "Row", "cleared_with_limits", "Light weights only"
        )

    read_program_response = client.get("/programs/active", headers=player_headers)
    assert read_program_response.status_code == 200, read_program_response.text
    read_program = read_program_response.json()
    exercise = read_program["days"][0]["exercises"][0]
    warmup = read_program["days"][0]["warmup_exercises"][0]
    assert exercise["clearance_status"] == "not_cleared"
    assert warmup["clearance_status"] == "cleared_with_limits"
    assert warmup["clearance_limit_notes"] == ["Light weights only"]
    draft = {
        key: read_program[key]
        for key in ("program_name", "split_type", "weekly_frequency", "instructions", "days")
    }
    exercise["clearance_status"] = "cleared"
    exercise["clearance_limit_notes"] = ["forged exercise note"]
    warmup["clearance_status"] = "not_cleared"
    warmup["clearance_limit_notes"] = ["forged warm-up note"]

    draft_path = f"/coach/assignments/{assignment_id}/program-draft"
    saved = client.post(draft_path, headers=coach_headers, json=draft)
    assert saved.status_code == 200, saved.text
    from service.coach_program_drafts import replace_program_draft

    replaced = replace_program_draft(db, coach_id, assignment_id, draft)
    assert replaced is not None
    with db.open_ledger("p1") as ledger:
        stored = ledger.get_program_draft(assignment_id)["draft"]
    for day in stored["days"]:
        for movement in [*day["exercises"], *day["warmup_exercises"]]:
            assert "clearance_status" not in movement
            assert "clearance_limit_notes" not in movement

    published = client.post(f"{draft_path}/publish", headers=coach_headers)
    assert published.status_code == 200, published.text
    active = client.get("/programs/active", headers=player_headers).json()
    assert active["days"][0]["exercises"][0]["clearance_status"] == "not_cleared"
    assert active["days"][0]["warmup_exercises"][0]["clearance_status"] == "cleared_with_limits"
    assert active["days"][0]["warmup_exercises"][0]["clearance_limit_notes"] == [
        "Light weights only"
    ]


def test_undo_does_not_reintroduce_an_excluded_exercise(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    assert _swap(client, headers, "sq", "ohp").status_code == 200
    _injury(client, headers, "knee")
    refused = client.post(
        "/programs/active/substitutions/undo", headers=headers,
        json={"restore_version": 1, "expected_active_version": 2},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "clearance_excluded"
    assert client.get("/programs/active", headers=headers).json()["version"] == 2


def test_another_active_injury_cannot_be_overridden_by_a_clearance(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    shoulder = _injury(client, headers, "shoulder")
    other = _injury(client, headers, None)
    _clearance(db.ledger, shoulder, "ohp", "Overhead Press", "cleared")
    _clearance(db.ledger, other, "ohp", "Overhead Press", "not_cleared")
    assert _swap(client, headers, "sq", "ohp").status_code == 400


def test_latest_advice_for_the_same_injury_wins_including_an_edited_verdict(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    shoulder = _injury(client, headers, "shoulder")
    earlier = _clearance(db.ledger, shoulder, "ohp", "Overhead Press", "not_cleared")
    _clearance(db.ledger, shoulder, "ohp", "Overhead Press", "cleared")
    assert _swap(client, headers, "sq", "ohp").status_code == 200
    assert _swap(client, headers, "ohp", "sq").status_code == 200
    edited = client.put(
        f"/profile/injuries/{shoulder['id']}/clearances/{earlier['id']}", headers=headers,
        json={"exercise_name": "Overhead Press", "original_wording": earlier["original_wording"],
              "verdict": "not_cleared", "note": "Latest advice"},
    )
    assert edited.status_code == 200, edited.text
    refused = _swap(client, headers, "sq", "ohp")
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "clearance_excluded"


@pytest.mark.parametrize(("language", "verdict"), [
    ("en", None), ("ar", None), ("en", "not_cleared"), ("en", "cleared_with_limits"),
])
def test_assistant_catalog_replies_defer_unverified_exercises_and_relay_limits(api, language, verdict):
    from langchain_core.messages import HumanMessage
    from agent.assistant_graph import catalog_search_node

    client, db = api
    headers = _make_player_with_program(client, db)
    injury = _injury(client, headers, "shoulder")
    if verdict:
        _clearance(db.ledger, injury, "ohp", "Overhead Press", verdict, "Light weights only")
    state = {
        "messages": [HumanMessage(content="هل تمرين Overhead Press مناسب؟" if language == "ar" else "Find Overhead Press")],
        "intent_metadata": {"search_query": "Overhead Press"},
        "display_language": language,
    }
    response = catalog_search_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    if verdict == "cleared_with_limits":
        assert "Light weights only" in response["response_content"]
        assert "Overhead Press" in response["response_content"]
    else:
        assert ("مش هقدر أأكد إنه آمن" if language == "ar" else "I can't confirm it's safe") in response["response_content"]


def test_unverified_existing_exercise_alerts_the_coach_when_injury_is_recorded(api):
    client, db = api
    coach_headers, player_headers, _, coach_id, _ = _assigned_player((client, db, None))
    with db.open_ledger("p1") as ledger:
        ledger.save_training_program(_program().model_dump(), published_by_coach_account_id=coach_id)
    _injury(client, player_headers, "knee")
    response = client.get("/coach/alerts", headers=coach_headers)
    assert response.status_code == 200, response.text
    alerts = [row for row in response.json()["alerts"] if row["message_code"] == "coach_alert.program_clearance.v1"]
    assert len(alerts) == 1
    assert alerts[0]["clearance_program_exercises"][0]["clearance_status"] == "unverified"
    with db.open_ledger("p1") as ledger:
        assert ledger.get_active_program().version == 1


def test_coach_receives_one_program_clearance_alert_per_exercise_and_assignment(api):
    client, db = api
    coach_headers, headers, assignment_id, coach_id, _ = _assigned_player((client, db, None))
    db.switch_user("p1")
    db.ledger.save_training_program(_program().model_dump(), published_by_coach_account_id=coach_id)
    injury = _injury(client, headers, None)
    clearance = _clearance(db.ledger, injury, "sq", "Squat", "cleared")
    clearance_path = f"/profile/injuries/{injury['id']}/clearances/{clearance['id']}"
    body = {
        "exercise_name": "Squat", "original_wording": clearance["original_wording"],
        "verdict": "not_cleared", "note": "Physician review",
    }
    changed = client.put(clearance_path, headers=headers, json=body)
    assert changed.status_code == 200, changed.text

    def alerts():
        response = client.get("/coach/alerts", headers=coach_headers)
        assert response.status_code == 200, response.text
        return [row for row in response.json()["alerts"] if row["message_code"] == "coach_alert.program_clearance.v1"]

    notice = alerts()
    assert len(notice) == 1
    assert notice[0]["assignment_id"] == assignment_id
    assert notice[0]["clearance_program_exercises"][0]["exercise_id"] == "sq"
    assert notice[0]["message_params"]["exercise_name"] == "Squat"
    acknowledged = client.post(f"/coach/alerts/{notice[0]['alert_id']}/acknowledge", headers=coach_headers)
    assert acknowledged.status_code == 200, acknowledged.text
    body["note"] = "Updated physician note"
    assert client.put(clearance_path, headers=headers, json=body).status_code == 200
    for _ in range(2):
        active = client.get("/programs/active", headers=headers).json()
        assert active["version"] == 1
        assert active["player_controls_program"] is False
        assert active["days"][0]["exercises"][0]["exercise_id"] == "sq"
        assert active["days"][0]["exercises"][0]["clearance_status"] == "not_cleared"
    assert len(alerts()) == 1
    assert client.post("/assignments/me/end", headers=headers).status_code == 200
    body["note"] = "After assignment ended"
    assert client.put(clearance_path, headers=headers, json=body).status_code == 200
    denied = client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
    assert all(row["assignment_id"] != assignment_id for row in denied)


@pytest.fixture
def library_api(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    from svc.rate_limit import limiter
    limiter._storage.reset()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app) as client:
        yield client, fresh_store


@pytest.mark.parametrize("role", ["player", "coach"])
def test_generated_programs_filter_active_clearances_including_warmups_and_substitutes(library_api, role):
    client, db = library_api
    coach_headers, headers, assignment_id, _, _ = _assigned_player((client, db, None))
    with db.open_ledger("p1") as ledger:
        ledger.upsert_player_profile({"weekly_frequency": 2, "equipment_access": "commercial gym"})
    baseline = client.post("/programs/generate", headers=headers, json={"frequency_override": 2})
    assert baseline.status_code == 200, baseline.text
    movements = [exercise for day in baseline.json()["days"] for exercise in day["exercises"]]
    # Pick an actual previously prescribed exercise so an ineffective filter fails.
    lower_body_parts = {"upper legs", "lower legs"}
    explicit = next(
        exercise for exercise in movements
        if db.get_exercise_library_entry(exercise["exercise_id"])["body_part"].casefold()
        not in lower_body_parts
    )
    assert any(
        db.get_exercise_library_entry(exercise["exercise_id"])["body_part"].casefold()
        in lower_body_parts
        for exercise in movements
    )
    injury = _injury(client, headers, "knee")
    with db.open_ledger("p1") as ledger:
        _clearance(ledger, injury, explicit["exercise_id"], explicit["exercise_name"], "not_cleared")
    if role == "coach":
        generated = client.post(
            f"/coach/assignments/{assignment_id}/program-draft/generate", headers=coach_headers,
            json={"frequency_override": 2},
        )
        assert generated.status_code == 200, generated.text
        published = client.post(
            f"/coach/assignments/{assignment_id}/program-draft/publish", headers=coach_headers,
        )
        assert published.status_code == 200, published.text
        program = client.get("/programs/active", headers=headers).json()
    else:
        generated = client.post("/programs/generate", headers=headers, json={"frequency_override": 2})
        assert generated.status_code == 200, generated.text
        program = generated.json()
    prescribed = [exercise for day in program["days"] for exercise in day["exercises"]]
    assert prescribed
    candidates = [
        exercise for day in program["days"]
        for exercise in [*day["exercises"], *day.get("warmup_exercises", [])]
    ]
    candidates += [substitute for exercise in prescribed for substitute in exercise.get("suggested_substitutes", [])]
    for exercise in candidates:
        assert exercise["exercise_id"] != explicit["exercise_id"]
        entry = db.get_exercise_library_entry(exercise["exercise_id"])
        assert entry["body_part"].casefold() not in lower_body_parts


def test_profile_rebuild_uses_the_injury_submitted_in_the_same_request(library_api):
    client, db = library_api
    _, headers, _, _, _ = _assigned_player((client, db, None))
    with db.open_ledger("p1") as ledger:
        ledger.upsert_player_profile({"weekly_frequency": 2, "rep_preference": "balanced"})
    baseline = client.post("/programs/generate", headers=headers, json={"frequency_override": 2})
    assert baseline.status_code == 200, baseline.text
    changed = client.patch(
        "/profile", headers=headers,
        json={"injuries_or_limitations": "knee pain", "rep_preference": "high"},
    )
    assert changed.status_code == 200, changed.text
    active = client.get("/programs/active", headers=headers)
    assert active.status_code == 200, active.text
    assert active.json()["version"] == baseline.json()["version"] + 1
    for day in active.json()["days"]:
        for exercise in [*day["exercises"], *day.get("warmup_exercises", [])]:
            entry = db.get_exercise_library_entry(exercise["exercise_id"])
            assert entry["body_part"].casefold() not in {"upper legs", "lower legs"}
