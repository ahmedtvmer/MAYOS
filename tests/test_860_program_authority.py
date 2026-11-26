"""#860: program authority is decided in code, never in the model's view.

Covers the three program-authority states — no assignment, assigned before the
Coach publishes, assigned after the Coach publishes — for direct change
requests (swaps and program/split changes), change requests that today would
reach a hosted model, and the questions that must keep reaching it. The model
never sees authority wording: ``STATIC_SYSTEM_CORE`` and the active-program
tool result carry no authority field or Coach name.

Fixtures reuse the assignment/publication helpers' service seams
(``service.coach`` / ``service.assignments``) and the ledger save with coach
provenance used in ``tests/test_player_chat_privacy.py`` and
``tests/test_coach_programs.py``.
"""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent import assistant_graph, player_prompt, player_tools
from agent.ProgramState import (
    GeneratedProgramSchema,
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from service import assignments as assignments_service
from service import coach as coach_service
from service import programs as programs_service
from tests.fakes.chat_model import ScriptedChatModel

SWAP_SOURCE = "Bench Press (Barbell)"
SWAP_TARGET = "Bench Press (Dumbbell)"
PROGRAM_NAMES = ("Back Squat (Barbell)", "Bench Press (Barbell)")
EGYPTIAN_SWAP = f"بدل {SWAP_SOURCE} بـ {SWAP_TARGET}"
MSA_SWAP = f"استبدل {SWAP_SOURCE} بـ {SWAP_TARGET}"
ENGLISH_SWAP = f"swap {SWAP_SOURCE} for {SWAP_TARGET}"
ARABIC_PROGRAM_CHANGE = "غيّر برنامجي لـ PPL 3 أيام"
ENGLISH_PROGRAM_CHANGE = "change my program to PPL, 3 days"
SWAP_REQUESTS = (EGYPTIAN_SWAP, MSA_SWAP, ENGLISH_SWAP)
PROGRAM_CHANGES = (ARABIC_PROGRAM_CHANGE, ENGLISH_PROGRAM_CHANGE)
BRO_SPLIT_ENGLISH = "change my routine to a bro split with a chest and back day"
BRO_SPLIT_ARABIC = "عايز أغيّر الروتين بتاعي لتقسيمة صدر وضهر ودراع"
COACH_REFUSAL_AR = (
    "يتولى مدربك المعيّن التحكم في برنامجك التدريبي. "
    "يمكنك مراجعة طلب وإرساله إلى مدربك."
)
SCENARIOS = ("unassigned", "assigned_unpublished", "assigned_published")


# --- fixtures ---------------------------------------------------------------


def _register_player(db, username: str) -> SimpleNamespace:
    account_id = db.create_account(username)
    assert account_id, username
    account = db.get_active_account_by_username(username)
    assert account is not None
    with db.open_ledger(account["ledger_id"]):
        pass
    return SimpleNamespace(
        account_id=account_id,
        username=username,
        ledger_id=account["ledger_id"],
    )


def _assigned_player(db, player_name: str) -> SimpleNamespace:
    """Coach "coach" actively assigned ``player_name`` through the service seams."""
    coach = _register_player(db, "coach")
    player = _register_player(db, player_name)
    issued = coach_service.issue_coach_invite(db, "coach", actor="cli")
    assert issued["ok"], issued
    # Redeeming the coach invite seeds the coach profile row (capacity 10), so
    # no second insert is needed — a second one would violate the unique index.
    granted = coach_service.redeem_coach_invite(db, coach.account_id, issued["token"])
    assert granted["ok"], granted
    assert db.get_coach_capacity(coach.account_id) is not None
    invite = assignments_service.issue_assignment_invite(db, coach.account_id)
    assert invite["ok"], invite
    redeemed = assignments_service.redeem_assignment_invite(
        db, invite["token"], player.account_id, True
    )
    assert "error" not in redeemed, redeemed
    assignment = db.get_active_assignment_for_player(player.account_id)
    assert assignment is not None
    return SimpleNamespace(
        player=player,
        coach_account_id=coach.account_id,
        assignment_id=assignment["assignment_id"],
    )


def _resolved_exercise_id(store, name: str) -> str:
    matches = store.find_exercises_by_name(name, limit=1)
    assert matches, name
    return str(store.get_exercise_library_entry(str(matches[0]["id"]))["id"])


def _resolved_exercises(store, names) -> tuple[list[PersistedProgramExerciseSchema], dict[str, str]]:
    exercises = []
    ids: dict[str, str] = {}
    for name in names:
        matches = store.find_exercises_by_name(name, limit=1)
        assert matches, name
        entry = store.get_exercise_library_entry(str(matches[0]["id"]))
        exercise_id = str(entry["id"])
        ids[name] = exercise_id
        exercises.append(
            PersistedProgramExerciseSchema(
                exercise_id=exercise_id,
                exercise_name=entry["name"],
                target_sets=3,
                target_reps_min=8,
                target_reps_max=12,
            )
        )
    return exercises, ids


def _save_player_program(
    db, ledger_id: str, names, published_by: str | None, resolve_only: tuple[str, ...] = ()
) -> dict[str, str]:
    exercises, ids = _resolved_exercises(db, names)
    for name in resolve_only:
        ids[name] = _resolved_exercise_id(db, name)
    with db.open_ledger(ledger_id) as ledger:
        ledger.save_training_program(
            PersistedProgramSchema(
                program_name="Plan",
                split_type="Full Body",
                weekly_frequency=1,
                days=[PersistedProgramDaySchema(
                    day_name="Full A", day_order=1, exercises=exercises,
                )],
            ).model_dump(),
            published_by_coach_account_id=published_by,
        )
    return ids


@pytest.fixture(params=SCENARIOS)
def scenario_player(request, fresh_store):
    """One Player per program-authority state, each with an active program."""
    db = fresh_store
    if request.param == "unassigned":
        player = _register_player(db, "p860-unassigned")
        ids = _save_player_program(
            db, player.ledger_id, PROGRAM_NAMES, published_by=None,
            resolve_only=(SWAP_TARGET,),
        )
        return {
            "db": db, "username": player.username, "account_id": player.account_id,
            "scenario": request.param, "ids": ids,
        }
    assigned = _assigned_player(db, f"p860-{request.param}")
    published_by = (
        assigned.coach_account_id if request.param == "assigned_published" else None
    )
    ids = _save_player_program(
        db, assigned.player.ledger_id, PROGRAM_NAMES, published_by=published_by,
        resolve_only=(SWAP_TARGET,),
    )
    return {
        "db": db, "username": assigned.player.username,
        "account_id": assigned.player.account_id, "scenario": request.param,
        "ids": ids,
    }


def _turn_state(scenario, query: str) -> dict:
    return {
        "messages": [HumanMessage(content=query)],
        "trainee_id": scenario["username"],
        "player_account_id": scenario["account_id"],
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def _run_turn(scenario, monkeypatch, query: str, model: ScriptedChatModel | None = None):
    db = scenario["db"]
    if model is None:
        model = ScriptedChatModel([])
    monkeypatch.setattr(assistant_graph, "llm", model)
    db.switch_user(scenario["username"])
    before = db.ledger.get_active_program().version
    state = _turn_state(scenario, query)
    response = "".join(
        assistant_graph.stream_assistant_turn(state, ledger=db.ledger, store=db)
    )
    return state, response, model, before


def _script_mutation(monkeypatch, exercises: list[PersistedProgramExerciseSchema]) -> None:
    """Replaces the hosted-model generation pipeline with a saving fake."""
    program = GeneratedProgramSchema(
        program_name="Mutated Plan",
        split_type="PPL",
        weekly_frequency=3,
        days=[
            ProgramDaySchema(
                day_name=f"Day {index}", day_order=index,
                exercises=[
                    ProgramExerciseSchema(
                        exercise_id=exercise.exercise_id,
                        exercise_name=exercise.exercise_name,
                        target_reps_min=8, target_reps_max=12,
                    )
                    for exercise in exercises
                ],
            )
            for index in (1, 2, 3)
        ],
    )

    def fake(*args, **kwargs):
        ledger = kwargs.get("ledger")
        if ledger is not None:
            ledger.save_training_program(program.model_dump())
        return program, "md"

    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", fake)
    # #867: the rebuild preview drafts the same program without saving it.
    monkeypatch.setattr(
        assistant_graph, "generate_program_draft_pipeline", lambda *args, **kwargs: (program, "md")
    )


def _confirm_rebuild(scenario, monkeypatch, query: str, offer: str, model=None):
    """#867: a rebuild changes the program only after the Player says yes."""
    db = scenario["db"]
    monkeypatch.setattr(assistant_graph, "llm", model or ScriptedChatModel([]))
    state = _turn_state(scenario, "yes")
    state["messages"] = [HumanMessage(content=query), AIMessage(content=offer), HumanMessage(content="yes")]
    response = "".join(assistant_graph.stream_assistant_turn(state, ledger=db.ledger, store=db))
    return state, response


def _mutation_exercises(scenario) -> list[PersistedProgramExerciseSchema]:
    """Three per day: GeneratedProgramSchema rejects shorter training days."""
    exercises, _ids = _resolved_exercises(scenario["db"], (*PROGRAM_NAMES, SWAP_TARGET))
    return exercises


def _program_change_model(query: str) -> ScriptedChatModel:
    """The Arabic change route classifies through the Arabic router first."""
    if query == ARABIC_PROGRAM_CHANGE:
        return ScriptedChatModel([
            {"intent": "program_change", "target_split_type": "ppl", "target_frequency": 3}
        ])
    return ScriptedChatModel([])


def _is_arabic(query: str) -> bool:
    return any("\u0600" <= character <= "\u06ff" for character in query)


# --- change requests: Player-controlled programs change ----------------------


@pytest.mark.parametrize("scenario_player", ["unassigned", "assigned_unpublished"], indirect=True)
@pytest.mark.parametrize("query", [*SWAP_REQUESTS, *PROGRAM_CHANGES])
def test_player_controlled_change_requests_change_the_program(
    scenario_player, monkeypatch, query
):
    scenario = scenario_player
    if query in PROGRAM_CHANGES:
        _script_mutation(monkeypatch, _mutation_exercises(scenario))
        model = _program_change_model(query)
    else:
        model = None
    state, response, model, before = _run_turn(scenario, monkeypatch, query, model)
    db = scenario["db"]
    if query in PROGRAM_CHANGES:
        assert state["intent"] == "program_mutation"
        assert state["program_updated"] is False
        assert db.ledger.get_active_program().version == before
        state, response = _confirm_rebuild(scenario, monkeypatch, query, response)

    assert state["program_updated"] is True
    active = db.ledger.get_active_program()
    assert active.version == before + 1
    if query in SWAP_REQUESTS:
        assert state["intent"] == "exercise_substitution"
        ids = [e.exercise_id for e in active.days[0].exercises]
        assert scenario["ids"][SWAP_TARGET] in ids
        assert scenario["ids"][SWAP_SOURCE] not in ids
    else:
        assert state["intent"] == "program_mutation"
        assert active.weekly_frequency == 3
        assert active.program_name == "Mutated Plan"


@pytest.mark.parametrize("scenario_player", ["assigned_published"], indirect=True)
@pytest.mark.parametrize("query", [*SWAP_REQUESTS, *PROGRAM_CHANGES])
def test_coach_published_change_requests_get_the_fixed_refusal(
    scenario_player, monkeypatch, query
):
    scenario = scenario_player
    _script_mutation(monkeypatch, _mutation_exercises(scenario))
    model = _program_change_model(query)
    state, response, model, before = _run_turn(scenario, monkeypatch, query, model)
    db = scenario["db"]

    assert state["intent"] == "coach_controlled"
    assert state["program_updated"] is False
    active = db.ledger.get_active_program()
    assert active.version == before
    ids = [e.exercise_id for e in active.days[0].exercises]
    assert scenario["ids"][SWAP_SOURCE] in ids
    assert scenario["ids"][SWAP_TARGET] not in ids
    if _is_arabic(query):
        assert response == COACH_REFUSAL_AR
    else:
        assert response == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    suggestion = state["request_suggestion"]
    if query in SWAP_REQUESTS:
        assert suggestion["kind"] == "exercise_substitution"
        assert suggestion["exercise_id"] == scenario["ids"][SWAP_SOURCE]
        assert suggestion["replacement_exercise_id"] == scenario["ids"][SWAP_TARGET]
    else:
        assert suggestion["kind"] == "split_change"
        assert suggestion["desired_weekly_frequency"] == 3


# --- change requests that today reach the model ------------------------------


@pytest.mark.parametrize("scenario_player", SCENARIOS, indirect=True)
@pytest.mark.parametrize("query", [BRO_SPLIT_ENGLISH, BRO_SPLIT_ARABIC])
def test_unbuildable_change_requests_get_a_fixed_reply_without_a_model(
    scenario_player, monkeypatch, query
):
    scenario = scenario_player
    state, response, model, before = _run_turn(
        scenario, monkeypatch, query, ScriptedChatModel([])
    )
    db = scenario["db"]

    # The scripted model fails the test if anything streams: no turn, no calls.
    assert not model.calls
    assert db.ledger.get_active_program().version == before
    if scenario["scenario"] == "assigned_published":
        assert state["intent"] == "coach_controlled"
        assert state["request_suggestion"]["kind"] == "split_change"
        if _is_arabic(query):
            assert response == COACH_REFUSAL_AR
        else:
            assert response == programs_service.COACH_CONTROLLED_REQUEST_ERROR
        return
    assert state["intent"] == "change_help"
    assert state["program_updated"] is False
    language = "ar" if _is_arabic(query) else "en"
    frequency, split_names = assistant_graph._player_split_plan(db.ledger)
    assert response == assistant_graph._change_help_reply(language, frequency, split_names)
    assert split_names and all(name in response for name in split_names)
    if language == "ar":
        assert "بدل X بـ Y" in response
        assert "غيّر برنامجي لـ" in response
    else:
        assert "swap X for Y" in response
        assert "change my program to" in response
    for wording in ("Coach", "coach", "كوتش", "مدرب"):
        assert wording not in response


# --- questions stay with the model -------------------------------------------


@pytest.mark.parametrize("scenario_player", ["unassigned", "assigned_published"], indirect=True)
@pytest.mark.parametrize(
    "query",
    [
        "should I change my split?",
        "why is bench on Push day?",
        "Can I switch my program to 3 days if work is busy?",
        "Could you tell me whether to switch my program?",
        "Would it be better to change my program to PPL?",
        "البرنامج ده كويس ليا؟",
        "ينفع أغيّر برنامجي؟",
        "ممكن أغيّر برنامجي؟",
    ],
)
def test_change_questions_stay_with_the_model(scenario_player, monkeypatch, query):
    scenario = scenario_player
    model = ScriptedChatModel([{"intent": "coaching_qa"}])
    monkeypatch.setattr(assistant_graph, "llm", model)
    db = scenario["db"]
    db.switch_user(scenario["username"])
    state = _turn_state(scenario, query)

    route = assistant_graph.router_node(
        state, {"configurable": {"ledger": db.ledger, "store": db}}
    )

    assert route["intent"] == "coaching_qa"


@pytest.mark.parametrize("scenario_player", ["unassigned"], indirect=True)
@pytest.mark.parametrize(
    "query",
    [
        "switch split to 3 days",
        "change my split to 4 days",
    ],
)
def test_frequency_changes_stay_executable(scenario_player, monkeypatch, query):
    """#860: a frequency change keeps program_mutation."""
    scenario = scenario_player
    _script_mutation(monkeypatch, _mutation_exercises(scenario))
    state, response, model, before = _run_turn(
        scenario, monkeypatch, query, ScriptedChatModel([])
    )
    db = scenario["db"]
    assert state["intent"] == "program_mutation"
    assert db.ledger.get_active_program().version == before
    state, response = _confirm_rebuild(scenario, monkeypatch, query, response, model)

    assert state["intent"] == "program_mutation"
    assert state["program_updated"] is True
    assert db.ledger.get_active_program().version == before + 1
    assert not model.calls


@pytest.mark.parametrize("scenario_player", ["unassigned"], indirect=True)
def test_new_split_without_a_target_never_rebuilds(scenario_player, monkeypatch):
    """Owner decision 2026-11-24: "give me a new split" is too loose to rebuild on."""
    scenario = scenario_player
    state, _response, model, before = _run_turn(
        # Worst case: the classifier itself calls it a program rebuild.
        scenario, monkeypatch, "give me a new split",
        ScriptedChatModel([{"intent": "program_mutation"}]),
    )

    assert state["intent"] == "change_help"
    assert state["program_updated"] is False
    assert scenario["db"].ledger.get_active_program().version == before
    assert [call["mode"] for call in model.calls] == ["structured"]


@pytest.mark.parametrize(
    ("query", "directive"),
    [
        ("غيّر برنامجي لـ PPL و chest x back و arms", True),
        ("غيّر البرنامج لـ PPL و chest x back و arms", True),
        ("عايز أغيّر برنامجي لـ PPL 3 أيام", True),
        ("غيّر روتيني لـ Full Body", True),
        ("ظبطلي تقسيمتي على 4 أيام", True),
        ("برنامجي كويس ليا؟", False),
        ("مش عايز أغيّر برنامجي", False),
        ("كنت عايز أغيّر برنامجي بس مش متأكد", False),
    ],
)
def test_arabic_my_program_is_a_change_directive(query, directive):
    """«غيّر برنامجي» fell through to the model, which invented a Coach."""
    assert assistant_graph._arabic_program_change_is_directive(query) is directive


# --- authority left the model's instructions and tool results ----------------


def test_static_system_core_carries_no_authority_wording():
    core = player_prompt.STATIC_SYSTEM_CORE
    lowered = core.casefold()
    assert "coach authority" not in lowered
    assert "program_authority" not in lowered
    assert "quote coach_note" not in lowered
    assert "mention coach or program requests" not in lowered
    assert "Program changes are handled outside this reply" in core
    # #859: no refusal and no request offer, for every Player; the swap
    # wording names no Coach, so it is no cue for an invented Coach.
    assert "never say you can't change the program" in core
    assert "never offer to send a request to anyone" in core
    assert lowered.count("coach") == 1  # only "You are Mayos, an evidence-based strength coach."
    assert "Tabs Home, Program, Nutrition, Progress." in core


@pytest.mark.parametrize("scenario_player", SCENARIOS, indirect=True)
def test_active_program_tool_result_carries_no_authority_or_coach_name(
    scenario_player,
):
    scenario = scenario_player
    db = scenario["db"]
    db.switch_user(scenario["username"])
    tools, _definitions = player_tools.build_player_read_tools(
        db.ledger, db, scenario["account_id"]
    )
    tool = next(item for item in tools if item.name == "get_active_program")

    result = json.loads(tool.invoke({}))

    assert "program_authority" not in result
    assert "coach" not in result
    if scenario["scenario"] == "assigned_published":
        assert "coach" not in json.dumps(result).casefold()


def test_rationale_record_for_a_coach_authored_note_carries_no_note(fresh_store):
    """#860 (owner decision 2026-11-24): the Coach's note never reaches the model."""
    db = fresh_store
    assigned = _assigned_player(db, "p860-rationale-note")
    exercises = []
    for name in PROGRAM_NAMES:
        matches = db.find_exercises_by_name(name, limit=1)
        assert matches, name
        entry = db.get_exercise_library_entry(str(matches[0]["id"]))
        exercises.append(
            PersistedProgramExerciseSchema(
                exercise_id=str(entry["id"]),
                exercise_name=entry["name"],
                note="Coach private note 860",
                target_sets=3,
                target_reps_min=8,
                target_reps_max=12,
            )
        )
    from agent.program_rationale_reader import read_program_rationale

    with db.open_ledger(assigned.player.ledger_id) as ledger:
        ledger.save_training_program(
            PersistedProgramSchema(
                program_name="Plan",
                split_type="Full Body",
                weekly_frequency=1,
                days=[PersistedProgramDaySchema(
                    day_name="Full A", day_order=1, exercises=exercises,
                )],
            ).model_dump(),
            published_by_coach_account_id=assigned.coach_account_id,
        )
        result = read_program_rationale(ledger.get_active_program())

    assert result["source"] == "coach_authored"
    record = result["days"][0]["exercises"][0]
    for key in ("coach_note", "exercise_note", "note"):
        assert key not in record
    assert "Coach private note 860" not in json.dumps(result, ensure_ascii=False)
