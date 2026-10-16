"""Bulk Program template assignment contract tests (ticket #306).

Exercises the public FastAPI surface against real temporary catalogs and player
ledgers. Covers multi-assign with independent drafts and ``source_template_id``,
per-player partial failure through the ADR 025 gate, replace/skip for existing
drafts, independence from later template edits, and 'Publish all' through the
normal publish path with default request resolution.
"""

import copy
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

TEMPLATES_PATH = "/coach/program-templates"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    from service.analytics import override_analytics_preference_reader

    override_analytics_preference_reader(db.analytics_preference_allows)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
    finally:
        override_analytics_preference_reader(None)
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert (
        client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code
        == 200
    )
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={
                "display_name": f"Coach {username}",
                "bio": "b",
                "specialization": "s",
                "capacity": capacity,
            },
        ).status_code
        == 200
    )
    return headers


def _assign_player(client, coach_headers, player_name):
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": token, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return player_headers, redeemed.json()["assignment"]["assignment_id"]


def _program(exercise_id="sq", **overrides):
    exercise = {
        "exercise_id": exercise_id,
        "exercise_name": "Squat",
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rir": 2.0,
        "rest_seconds": 180,
        "warmup_sets": 2,
        "tempo": None,
        "notes": None,
        "suggested_substitutes": [],
    }
    exercise.update(overrides.pop("exercise", {}))
    day = {
        "day_name": "Upper 1",
        "day_order": 1,
        "week_order": 1,
        "warmup_exercises": [],
        "exercises": [exercise],
        "cardio": None,
    }
    program = {
        "program_name": "Upper Block",
        "split_type": "Upper/Lower",
        "weekly_frequency": 1,
        "instructions": "",
        "days": [day],
        "weeks": [],
    }
    program.update(overrides)
    return program


def _create_template(client, coach_headers, name="My Template", program=None):
    created = client.post(
        TEMPLATES_PATH,
        headers=coach_headers,
        json={
            "name": name,
            "description": "Reusable split",
            "program": program if program is not None else _program(),
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _working_draft(client, coach_headers, assignment_id):
    draft = client.get(
        f"/coach/assignments/{assignment_id}/program-draft", headers=coach_headers
    )
    assert draft.status_code == 200, draft.text
    return draft.json()


# --------------------------------------------------------------------------
# Multi-assign, provenance, independence
# --------------------------------------------------------------------------


def test_assign_copies_template_to_multiple_players_with_source_template_id(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    p1_headers, asg1 = _assign_player(client, coach, "p1")
    p2_headers, asg2 = _assign_player(client, coach, "p2")
    template = _create_template(client, coach)

    assigned = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/assign",
        headers=coach,
        json={
            "targets": [
                {"assignment_id": asg1, "existing_draft": "replace"},
                {"assignment_id": asg2, "existing_draft": "replace"},
            ]
        },
    )
    assert assigned.status_code == 200, assigned.text
    results = {row["assignment_id"]: row for row in assigned.json()["results"]}
    assert set(results) == {asg1, asg2}
    for assignment_id in (asg1, asg2):
        row = results[assignment_id]
        assert row["status"] == "assigned"
        assert row["source_template_id"] == template["template_id"]
        assert row["source_template_name"] == "My Template"
        assert row["draft"]["source_template_id"] == template["template_id"]
        assert row["draft"]["draft"]["days"][0]["exercises"][0]["exercise_id"] == "sq"

    draft1 = _working_draft(client, coach, asg1)
    draft2 = _working_draft(client, coach, asg2)
    assert draft1["source_template_id"] == template["template_id"]
    assert draft1["source_template_name"] == "My Template"
    assert draft2["source_template_id"] == template["template_id"]


def test_assign_partial_failure_rejects_bad_assignment_without_failing_rest(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, good_assignment = _assign_player(client, coach, "p1")
    other_coach = _make_coach(client, db, "coach-b")
    _, foreign_assignment = _assign_player(client, other_coach, "p2")
    template = _create_template(client, coach)

    assigned = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/assign",
        headers=coach,
        json={
            "targets": [
                {"assignment_id": good_assignment},
                {"assignment_id": foreign_assignment},
                {"assignment_id": "asg:missing"},
            ]
        },
    )
    assert assigned.status_code == 200, assigned.text
    results = {row["assignment_id"]: row for row in assigned.json()["results"]}
    assert results[good_assignment]["status"] == "assigned"
    assert results[foreign_assignment]["status"] == "rejected"
    assert results["asg:missing"]["status"] == "rejected"
    assert results[foreign_assignment]["message_code"] == "assignment.none_active.v1"

    # The successful player really got the independent draft.
    assert _working_draft(client, coach, good_assignment)["draft"]["program_name"] == "Upper Block"


def test_assign_existing_draft_replace_and_skip_per_player(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, replace_assignment = _assign_player(client, coach, "p1")
    _, skip_assignment = _assign_player(client, coach, "p2")
    template = _create_template(client, coach, program=_program(exercise={"target_sets": 5}))

    # Give each player a pre-existing draft that is NOT from the template.
    for assignment_id in (replace_assignment, skip_assignment):
        seeded = client.post(
            f"/coach/assignments/{assignment_id}/program-draft",
            headers=coach,
            json=_program(exercise_id="row", exercise={"target_sets": 2}),
        )
        assert seeded.status_code == 200, seeded.text

    assigned = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/assign",
        headers=coach,
        json={
            "targets": [
                {"assignment_id": replace_assignment, "existing_draft": "replace"},
                {"assignment_id": skip_assignment, "existing_draft": "skip"},
            ]
        },
    )
    assert assigned.status_code == 200, assigned.text
    results = {row["assignment_id"]: row for row in assigned.json()["results"]}
    assert results[replace_assignment]["status"] == "replaced"
    assert results[skip_assignment]["status"] == "skipped"

    # Replaced player now has the template copy with the source id.
    replaced = _working_draft(client, coach, replace_assignment)
    assert replaced["source_template_id"] == template["template_id"]
    assert replaced["draft"]["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert replaced["draft"]["days"][0]["exercises"][0]["target_sets"] == 5

    # Skipped player keeps its original draft untouched.
    skipped = _working_draft(client, coach, skip_assignment)
    assert skipped["source_template_id"] is None
    assert skipped["draft"]["days"][0]["exercises"][0]["exercise_id"] == "row"
    assert skipped["draft"]["days"][0]["exercises"][0]["target_sets"] == 2


def test_assign_existing_draft_defaults_to_skip(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach)
    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach,
        json=_program(exercise_id="row"),
    )
    assert created.status_code == 200, created.text

    skipped = _assign(client, coach, template, assignment_id)
    assert skipped.status_code == 200, skipped.text
    result = skipped.json()["results"][0]
    assert result["status"] == "skipped"
    assert _working_draft(client, coach, assignment_id)["draft"]["days"][0][
        "exercises"
    ][0]["exercise_id"] == "row"


def test_assigning_a_foreign_template_is_a_uniform_404(api):
    client, db, _ = api
    coach_a = _make_coach(client, db, "coach-a")
    _, assignment = _assign_player(client, coach_a, "p1")
    coach_b = _make_coach(client, db, "coach-b")
    template = _create_template(client, coach_a, name="A only")

    rejected = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/assign",
        headers=coach_b,
        json={"targets": [{"assignment_id": assignment}]},
    )
    assert rejected.status_code == 404, rejected.text


def test_template_edit_does_not_change_draft_or_published_program(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    player_headers, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach, program=_program(exercise={"target_sets": 3}))

    assert (
        client.post(
            f"{TEMPLATES_PATH}/{template['template_id']}/assign",
            headers=coach,
            json={"targets": [{"assignment_id": assignment_id}]},
        ).status_code
        == 200
    )
    draft_before = _working_draft(client, coach, assignment_id)
    assert draft_before["draft"]["days"][0]["exercises"][0]["target_sets"] == 3

    # Edit the template after assigning.
    edited = client.put(
        f"{TEMPLATES_PATH}/{template['template_id']}",
        headers=coach,
        json={
            "name": "Renamed",
            "description": None,
            "program": _program(exercise_id="bp", exercise={"target_sets": 9}),
        },
    )
    assert edited.status_code == 200, edited.text

    # The existing draft is unchanged (independent copy).
    draft_after = _working_draft(client, coach, assignment_id)
    assert draft_after["draft"]["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert draft_after["draft"]["days"][0]["exercises"][0]["target_sets"] == 3

    # Publish the untouched draft; the published program is still the copy.
    published = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/publish",
        headers=coach,
    )
    assert published.status_code == 200, published.text
    assert published.json()["source_template_id"] == template["template_id"]
    active = client.get("/programs/active", headers=player_headers).json()
    assert active["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert active["source_template_id"] == template["template_id"]


# --------------------------------------------------------------------------
# Publish all
# --------------------------------------------------------------------------


def _create_substitution_request(client, player_headers, exercise_id="sq"):
    response = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "exercise_substitution",
            "day_name": "Upper 1",
            "exercise_id": exercise_id,
            "replacement_exercise_id": "bp",
            "reason": "Please change this exercise.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_publish_all_publishes_each_draft_and_resolves_open_requests(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    p1_headers, asg1 = _assign_player(client, coach, "p1")
    p2_headers, asg2 = _assign_player(client, coach, "p2")
    template = _create_template(client, coach)

    # First pass: create drafts and publish them so the players hold a
    # coach-controlled program (needed before they can raise a request).
    assert (
        client.post(
            f"{TEMPLATES_PATH}/{template['template_id']}/assign",
            headers=coach,
            json={"targets": [{"assignment_id": asg1}, {"assignment_id": asg2}]},
        ).status_code
        == 200
    )
    first = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/publish-all",
        headers=coach,
        json={"assignment_ids": [asg1, asg2]},
    )
    assert first.status_code == 200, first.text
    for row in first.json()["results"]:
        assert row["status"] == "published"
        assert row["version"] == 1
        assert row["resolved_request_count"] == 0

    request = _create_substitution_request(client, p1_headers)

    # Second pass: re-assign then publish all; the open request resolves by default.
    assert (
        client.post(
            f"{TEMPLATES_PATH}/{template['template_id']}/assign",
            headers=coach,
            json={"targets": [{"assignment_id": asg1}, {"assignment_id": asg2}]},
        ).status_code
        == 200
    )
    second = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/publish-all",
        headers=coach,
        json={"assignment_ids": [asg1, asg2]},
    )
    assert second.status_code == 200, second.text
    results = {row["assignment_id"]: row for row in second.json()["results"]}
    assert results[asg1]["status"] == "published"
    assert results[asg1]["version"] == 2
    assert results[asg1]["resolved_request_count"] == 1
    assert results[asg1]["resolved_request_ids"] == [request["request_id"]]
    assert results[asg2]["status"] == "published"
    assert results[asg2]["resolved_request_count"] == 0

    assert db.get_program_request(request["request_id"])["status"] == "applied"


def test_publish_all_reports_validation_errors_per_player(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, good_assignment = _assign_player(client, coach, "p1")
    _, broken_assignment = _assign_player(client, coach, "p2")
    _, no_draft_assignment = _assign_player(client, coach, "p3")
    template = _create_template(client, coach)

    assert (
        client.post(
            f"{TEMPLATES_PATH}/{template['template_id']}/assign",
            headers=coach,
            json={
                "targets": [
                    {"assignment_id": good_assignment},
                    {"assignment_id": broken_assignment},
                ]
            },
        ).status_code
        == 200
    )
    # Corrupt the broken player's draft directly in its ledger, bypassing validation.
    broken_account = db.get_active_account_by_username("p2")
    with db.open_ledger(broken_account["ledger_id"]) as ledger:
        stored = ledger.get_program_draft(broken_assignment)
        stored["draft"]["days"][0]["exercises"][0]["target_rir"] = 99
        ledger.replace_program_draft(broken_assignment, stored["draft"])

    published = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/publish-all",
        headers=coach,
        json={"assignment_ids": [good_assignment, broken_assignment, no_draft_assignment]},
    )
    assert published.status_code == 200, published.text
    results = {row["assignment_id"]: row for row in published.json()["results"]}
    assert results[good_assignment]["status"] == "published"
    assert results[broken_assignment]["status"] == "invalid"
    assert {issue["code"] for issue in results[broken_assignment]["errors"]} == {"invalid_rir"}
    assert results[no_draft_assignment]["status"] == "no_draft"


def test_publish_all_rejects_a_foreign_template(api):
    client, db, _ = api
    coach_a = _make_coach(client, db, "coach-a")
    _, assignment = _assign_player(client, coach_a, "p1")
    coach_b = _make_coach(client, db, "coach-b")
    template = _create_template(client, coach_a)

    rejected = client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/publish-all",
        headers=coach_b,
        json={"assignment_ids": [assignment]},
    )
    assert rejected.status_code == 404, rejected.text


def test_active_program_and_draft_show_source_template_name(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    player_headers, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach, name="Strength Base")

    assert (
        client.post(
            f"{TEMPLATES_PATH}/{template['template_id']}/assign",
            headers=coach,
            json={"targets": [{"assignment_id": assignment_id}]},
        ).status_code
        == 200
    )

    view = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach
    ).json()
    assert view["has_draft"] is True

    assert (
        client.post(
            f"/coach/assignments/{assignment_id}/program-draft/publish",
            headers=coach,
        ).status_code
        == 200
    )
    view = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach
    ).json()
    assert view["program"]["source_template_id"] == template["template_id"]
    assert view["program"]["source_template_name"] == "Strength Base"
    player_view = client.get("/programs/active", headers=player_headers)
    assert player_view.status_code == 200, player_view.text
    assert player_view.json()["source_template_id"] == template["template_id"]
    assert player_view.json()["source_template_name"] == "Strength Base"


# --------------------------------------------------------------------------
# Origin verification and provenance preservation
# --------------------------------------------------------------------------


def _assign(client, coach_headers, template, assignment_id, **target):
    target.setdefault("assignment_id", assignment_id)
    return client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/assign",
        headers=coach_headers,
        json={"targets": [target]},
    )


def _publish_all(client, coach_headers, template, assignment_ids):
    return client.post(
        f"{TEMPLATES_PATH}/{template['template_id']}/publish-all",
        headers=coach_headers,
        json={"assignment_ids": assignment_ids},
    )


def test_publish_all_rejects_a_draft_whose_origin_changed_since_assignment(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, assignment_id = _assign_player(client, coach, "p1")
    first = _create_template(client, coach, name="First")
    second = _create_template(client, coach, name="Second")

    assert _assign(client, coach, first, assignment_id).status_code == 200
    # The coach swaps in a different template before publishing the first.
    assert (
        _assign(client, coach, second, assignment_id, existing_draft="replace").status_code
        == 200
    )

    rejected = _publish_all(client, coach, first, [assignment_id])
    assert rejected.status_code == 200, rejected.text
    row = rejected.json()["results"][0]
    assert row["status"] == "rejected"
    assert row["message_code"] == "assignment.program_draft_changed.v1"

    # Nothing was published and the draft survived with its real origin.
    draft = _working_draft(client, coach, assignment_id)
    assert draft["source_template_id"] == second["template_id"]

    published = _publish_all(client, coach, second, [assignment_id])
    assert published.json()["results"][0]["status"] == "published"
    assert published.json()["results"][0]["version"] == 1


def test_publish_all_rejects_manual_and_other_template_drafts_partial_success(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, manual_assignment = _assign_player(client, coach, "p1")
    _, other_assignment = _assign_player(client, coach, "p2")
    _, target_assignment = _assign_player(client, coach, "p3")
    requested = _create_template(client, coach, name="Requested")
    other_template = _create_template(client, coach, name="Other")

    # p1: a hand-written draft with no template origin.
    hand_written = client.post(
        f"/coach/assignments/{manual_assignment}/program-draft",
        headers=coach,
        json=_program(),
    )
    assert hand_written.status_code == 200, hand_written.text
    # p2: a copy of a different template.
    assert _assign(client, coach, other_template, other_assignment).status_code == 200
    # p3: a real copy of the requested template.
    assert _assign(client, coach, requested, target_assignment).status_code == 200

    published = _publish_all(
        client, coach, requested, [manual_assignment, other_assignment, target_assignment]
    )
    assert published.status_code == 200, published.text
    results = {row["assignment_id"]: row for row in published.json()["results"]}
    assert results[manual_assignment]["status"] == "rejected"
    assert results[manual_assignment]["message_code"] == "assignment.program_draft_changed.v1"
    assert results[other_assignment]["status"] == "rejected"
    assert results[target_assignment]["status"] == "published"

    # The unrelated drafts are untouched and still open.
    assert _working_draft(client, coach, manual_assignment)["source_template_id"] is None
    assert (
        _working_draft(client, coach, other_assignment)["source_template_id"]
        == other_template["template_id"]
    )


def test_assign_skip_reports_the_existing_drafts_actual_origin(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, assignment_id = _assign_player(client, coach, "p1")
    existing = _create_template(client, coach, name="Existing")
    requested = _create_template(client, coach, name="Requested")

    assert _assign(client, coach, existing, assignment_id).status_code == 200
    skipped = _assign(client, coach, requested, assignment_id, existing_draft="skip")
    assert skipped.status_code == 200, skipped.text
    row = skipped.json()["results"][0]
    assert row["status"] == "skipped"
    # The skipped result must report the draft's REAL origin, not the requested one.
    assert row["source_template_id"] == existing["template_id"]
    assert row["source_template_name"] == "Existing"

    # Publishing the requested template must not touch the skipped draft.
    assert _publish_all(client, coach, requested, [assignment_id]).json()["results"][0][
        "status"
    ] == "rejected"
    assert _publish_all(client, coach, existing, [assignment_id]).json()["results"][0][
        "status"
    ] == "published"


def test_editing_a_template_draft_preserves_origin_through_publish(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach, name="Base")
    assert _assign(client, coach, template, assignment_id).status_code == 200

    edited = client.put(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach,
        json=_program(exercise={"target_sets": 6}),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["source_template_id"] == template["template_id"]

    published = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/publish", headers=coach
    )
    assert published.status_code == 200, published.text
    assert published.json()["source_template_id"] == template["template_id"]
    view = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach).json()
    assert view["program"]["source_template_id"] == template["template_id"]


def test_applying_a_substitution_request_preserves_template_origin(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    player_headers, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach, name="Base")
    assert _assign(client, coach, template, assignment_id).status_code == 200
    assert (
        client.post(
            f"/coach/assignments/{assignment_id}/program-draft/publish", headers=coach
        ).status_code
        == 200
    )

    request = _create_substitution_request(client, player_headers)
    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request['request_id']}/apply",
        headers=coach,
    )
    assert applied.status_code == 200, applied.text
    active = client.get("/programs/active", headers=player_headers).json()
    assert active["source_template_id"] == template["template_id"]


def test_generating_over_a_template_draft_clears_the_stale_origin(api, monkeypatch):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    _, assignment_id = _assign_player(client, coach, "p1")
    template = _create_template(client, coach, name="Base")
    assert _assign(client, coach, template, assignment_id).status_code == 200

    def fake(request, *, inference_call=None, ledger):
        program = GeneratedProgramSchema(
            program_name="Fresh Plan",
            split_type="Full Body",
            weekly_frequency=1,
            days=[
                ProgramDaySchema(
                    day_name="Full A",
                    day_order=1,
                    exercises=[
                        ProgramExerciseSchema(
                            exercise_id="sq",
                            exercise_name="Squat",
                            target_reps_min=5,
                            target_reps_max=8,
                        ),
                        ProgramExerciseSchema(
                            exercise_id="bp",
                            exercise_name="Bench Press",
                            target_reps_min=5,
                            target_reps_max=8,
                        ),
                        ProgramExerciseSchema(
                            exercise_id="row",
                            exercise_name="Row",
                            target_reps_min=5,
                            target_reps_max=8,
                        ),
                    ],
                )
            ],
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_draft_pipeline", fake)

    generated = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate?replace=true",
        headers=coach,
        json={},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["source_template_id"] is None
    assert _working_draft(client, coach, assignment_id)["source_template_id"] is None


def test_public_player_mutations_keep_origin_after_assignment_ends(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    player_headers, assignment_id = _assign_player(client, coach, "p1")
    program = _program()
    week_one_day = copy.deepcopy(program["days"][0])
    week_two_day = copy.deepcopy(program["days"][0])
    week_two_day["week_order"] = 2
    program["days"] = [week_one_day, week_two_day]
    program["weeks"] = [
        {"week_name": "Base", "week_order": 1, "days": [week_one_day]},
        {"week_name": "Build", "week_order": 2, "days": [week_two_day]},
    ]
    template = _create_template(client, coach, name="Base", program=program)
    assert _assign(client, coach, template, assignment_id).status_code == 200
    assert (
        client.post(
            f"/coach/assignments/{assignment_id}/program-draft/publish", headers=coach
        ).status_code
        == 200
    )

    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200
    active = client.get("/programs/active", headers=player_headers)
    assert active.status_code == 200, active.text
    assert active.json()["source_template_id"] == template["template_id"]

    substituted = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": "Upper 1",
            "exercise_id": "sq",
            "replacement_exercise_id": "bp",
            "expected_active_version": active.json()["version"],
        },
    )
    assert substituted.status_code == 200, substituted.text
    assert substituted.json()["source_template_id"] == template["template_id"]

    edited = client.post(
        "/programs/active/edits",
        headers=player_headers,
        json={
            "day_name": "Upper 1",
            "week_order": 1,
            "day_order": 1,
            "expected_active_version": substituted.json()["version"],
            "exercises": [
                {"source_index": 0, "exercise_id": "bp", "target_sets": 2}
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["source_template_id"] == template["template_id"]

    undone = client.post(
        "/programs/active/substitutions/undo",
        headers=player_headers,
        json={
            "restore_version": substituted.json()["version"],
            "expected_active_version": edited.json()["version"],
        },
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["source_template_id"] == template["template_id"]
    reloaded = client.get("/programs/active", headers=player_headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["source_template_id"] == template["template_id"]

    # Seed the final week's completion, then repeat through the public API.
    account = db.get_active_account_by_username("p1")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.log_workout_session(
            "source-template-repeat",
            "2026-10-16",
            "Upper 1",
            "2026-10-16T10:00:00+00:00",
            "2026-10-16T11:00:00+00:00",
            program_version=reloaded.json()["version"],
            program_week_order=2,
            program_day_order=1,
        )
    repeated = client.post(
        "/programs/active/repeat-from-week-1",
        headers=player_headers,
        json={"expected_active_version": reloaded.json()["version"]},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["source_template_id"] == template["template_id"]
    assert repeated.json()["source_template_name"] == "Base"
