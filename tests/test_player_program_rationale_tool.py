import json
from types import SimpleNamespace

from agent.player_tools import build_player_read_tools


def _program(*, rationale=None, authored=False):
    exercises = [
        SimpleNamespace(
            exercise_id=f"id-{index}", exercise_name=f"Lift {index}", note="Coach note",
            target_sets=3, target_reps_min=8, target_reps_max=12,
            target_rpe=8, rest_seconds=120, set_groups=[],
        )
        for index in range(1, 5)
    ]
    day = SimpleNamespace(day_name="Push", day_order=1, exercises=exercises,
                          warmup_exercises=[], cardio=None)
    return SimpleNamespace(
        program_name="Plan", weekly_frequency=1, split_type="Full Body",
        days=[day], weeks=[], version=2, program_rationale=rationale,
        published_by_coach_account_id="coach" if authored else None,
        source_template_id=None,
    )


def _reader(program):
    tools, _ = build_player_read_tools(SimpleNamespace(get_active_program=lambda: program))
    return next(tool for tool in tools if tool.name == "get_program_rationale")


def test_active_program_reports_player_authority_without_assignment():
    program = _program()
    ledger = SimpleNamespace(
        get_active_program=lambda: program,
        get_program_position=lambda _program: SimpleNamespace(current_week=1),
        volume_review_exercise_targets=lambda _ids: {},
    )
    store = SimpleNamespace(get_active_assignment_for_player=lambda _account_id: None)

    tools, _definitions = build_player_read_tools(ledger, store, "player-id")
    result = json.loads(next(tool for tool in tools if tool.name == "get_active_program").invoke({}))

    assert result["program_authority"] == "player"


def test_active_program_reports_coach_authority_and_display_name():
    program = _program(authored=True)
    program.created_at = "2026-10-27T12:00:00+00:00"
    ledger = SimpleNamespace(
        get_active_program=lambda: program,
        get_program_position=lambda _program: SimpleNamespace(current_week=1),
        volume_review_exercise_targets=lambda _ids: {},
    )
    store = SimpleNamespace(
        get_active_assignment_for_player=lambda _account: {
            "coach_account_id": "coach", "started_at": "2026-10-27T11:00:00+00:00"
        },
        get_account=lambda _account: {"username": "coach-handle"},
        get_coach_profile=lambda _account: {
            "display_name": "Coach Display", "bio": "", "specialization": ""
        },
    )

    tools, _definitions = build_player_read_tools(ledger, store, "player-id")
    result = json.loads(next(tool for tool in tools if tool.name == "get_active_program").invoke({}))

    assert result["program_authority"] == "coach"
    assert result["coach"] == "Coach Display"


def test_program_rationale_reader_scopes_by_day_or_exercise_and_keeps_unknown_codes():
    program = _program(rationale={
        "split": {"code": "split.new_code", "params": {}},
        "day_order": {"code": "day_order.new_code", "params": {}},
        "focus_muscles": [{"muscle": "biceps", "extras": [{
            "exercise_id": "id-1", "day_order": 1,
            "day_choice_reason": {"code": "focus.new_weekly_exposure", "params": {"day_order": 1}},
        }]}],
        "days": [{"day_order": 1, "exercises": [
            {"position": 1, "exercise_id": "id-1", "rationale": {
                "selection": {"code": "selection.focus_muscle_extra", "params": {}},
                "day_choice": {"code": "focus.new_weekly_exposure", "params": {"day_order": 1}},
            }},
            {"position": 2, "exercise_id": "id-2", "selection": {"code": "selection.staple", "params": {}}},
        ]}],
    })
    reader = _reader(program)

    day = json.loads(reader.invoke({"day_name": "Push"}))
    exercise = json.loads(reader.invoke({"exercise_id": "id-2", "day_name": "Push"}))

    assert day["days"][0]["day"] == "Push"
    assert len(day["days"][0]["exercises"]) == 4
    assert exercise["days"][0]["exercises"][0]["exercise_id"] == "id-2"
    assert exercise["days"][0]["exercises"][0]["rationale"]["selection"]["code"] == "selection.staple"
    assert day["split"]["code"] == "split.new_code"
    assert day["days"][0]["exercises"][0]["rationale"]["day_choice"]["code"] == "focus.new_weekly_exposure"
    assert day["days"][0]["exercises"][0]["day_choice"]["code"] == "focus.new_weekly_exposure"
    assert day["focus_muscles"][0]["extras"][0]["day_choice_reason"]["code"] == "focus.new_weekly_exposure"


def test_program_rationale_reader_reports_legacy_and_coach_authored_source_and_note():
    legacy = json.loads(_reader(_program()).invoke({}))
    authored = json.loads(_reader(_program(authored=True)).invoke({"exercise_id": "id-1"}))

    assert legacy["reason_available"] is False
    assert authored["reason_available"] is False
    assert authored["source"] == "coach_authored"
    assert authored["days"][0]["exercises"][0]["coach_note"] == "Coach note"


def test_program_rationale_reader_never_exceeds_4_kb():
    rationale = {"split": {"code": "split.test", "params": {}}, "days": [
        {"day_order": 1, "exercises": [{"position": i, "exercise_id": f"id-{i}", "rationale": {
            "selection": {"code": "selection.staple", "params": {"exercise_id": f"id-{i}", "slot": "horizontal_press"}},
            "position": {"code": "position.heavy_compound", "params": {"slot": "horizontal_press"}},
            "prescription": {"sets": {"code": "sets.coach_dose", "params": {"count": 4}},
                             "reps": {"code": "reps.movement_class", "params": {"rep_min": 6, "rep_max": 8}},
                             "rir": {"code": "rir.experience_level", "params": {"target_rir": 2}},
                             "rest": {"code": "rest.movement_class", "params": {"rest_seconds": 150}}}},
            "changes": [{"code": "change.substitution", "params": {"from": "old"}, "at": "2026-01-01T00:00:00Z"}]}
            for i in range(1, 5)]}
    ]}
    result = _reader(_program(rationale=rationale)).invoke({})
    assert len(result.encode("utf-8")) <= 4096
    assert json.loads(result)["reason_available"] is True


def test_reader_preserves_change_history_removed_entries_and_unavailable_focus():
    program = _program(rationale={
        "focus_muscles": [{"muscle": "glutes", "status": "unavailable", "code": "focus.unavailable", "params": {}}],
        "days": [{"day_order": 1, "removed": [{"exercise_id": "old", "code": "change.program_edit_removed"}],
                  "exercises": [{"position": 1, "exercise_id": "id-1", "selection": {"code": "selection.staple", "params": {}},
                                 "position_reason": {"code": "position.isolation", "params": {}},
                                 "prescription": {}, "changes": [{"code": "change.substitution", "params": {"from": "old"}, "at": "today"}]}]}],
    })
    whole = json.loads(_reader(program).invoke({}))
    exercise = json.loads(_reader(program).invoke({"exercise_id": "id-1"}))
    assert whole["days"][0]["exercises"][0]["changes"][0]["code"] == "change.substitution"
    assert whole["days"][0]["removed"][0]["exercise_id"] == "old"
    assert whole["focus_muscles"][0]["status"] == "unavailable"
    assert exercise["days"][0]["exercises"][0]["changes"]


def test_coach_published_generated_program_is_not_labeled_automatic():
    program = _program(rationale={"days": []}, authored=True)
    result = json.loads(_reader(program).invoke({}))
    assert result["source"] == "coach_generated"
    assert result["days"][0]["exercises"][0]["coach_note"] == "Coach note"


def test_oversized_day_rationale_is_paged_without_losing_reasons():
    program = _program(rationale={"days": [{"day_order": 1, "exercises": [
        {"position": index, "exercise_id": f"id-{index}", "rationale": {
            "selection": {"code": "selection.staple", "params": {"detail": "x" * 1100}},
        }} for index in range(1, 5)
    ]}]})
    first = json.loads(_reader(program).invoke({"day_order": 1}))

    assert first["reason_available"] is True
    assert len(json.dumps(first, separators=(",", ":")).encode()) <= 4096
    assert first["days"][0]["exercises"]
    assert first["next_page"] > 0
    second = json.loads(_reader(program).invoke({"day_order": 1, "page": first["next_page"]}))
    assert second["days"][0]["exercises"]
    assert len(json.dumps(second, separators=(",", ":")).encode()) <= 4096
