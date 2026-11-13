"""Model-selected Player operations, bound to the original turn and its ledger."""

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, ValidationError
from service.inference_metrics import log_turn_exception

from agent.player_tools import (
    EmptyToolArgs, PlayerReadTool, _encode_tool_result,
    build_player_read_tools, run_player_tool_calls,
)


class ExerciseSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ExerciseHistoryArgs(BaseModel):
    exercise_name: str | None = None
    exercise_id: str | None = None
    scope: Literal["latest_session", "last_occurrence"] = "latest_session"


class SubstitutionArgs(BaseModel):
    source_exercise: str = Field(min_length=1, max_length=200)
    target_exercise: str | None = Field(default=None, max_length=200)
    day_name: str | None = Field(default=None, max_length=200)


class RebuildArgs(BaseModel):
    days: int | None = Field(default=None, ge=1, le=5, strict=True)
    split_type: str | None = None


@dataclass
class PlayerToolTurn:
    state: dict[str, Any]
    config: dict[str, Any] | None

    @property
    def handles(self):
        from agent.assistant_graph import _graph_context
        return _graph_context(self.config)

    @property
    def query(self) -> str:
        from agent.player_prompt import get_message_text
        return get_message_text(self.state["messages"][-1])

    def finish(self, result: dict[str, Any]) -> dict[str, Any]:
        # Offers must be displayed verbatim: confirmation is bound to their exact text.
        previous = self.state.get("tool_action_result")
        if previous is not None:
            result = {**previous, **result,
                      "response_content": previous["response_content"] + "\n\n" + result["response_content"],
                      "program_updated": bool(previous.get("program_updated") or result.get("program_updated")),
                      "movement_restrictions_updated": bool(previous.get("movement_restrictions_updated") or result.get("movement_restrictions_updated"))}
            result["messages"] = [AIMessage(content=result["response_content"])]
        self.state["tool_action_result"] = result
        return {key: value for key, value in result.items() if key != "messages"}


def _search_exercises(turn: PlayerToolTurn, query: str) -> dict[str, Any]:
    from agent import assistant_graph as graph
    _ledger, store = turn.handles
    candidates, by_name = graph._catalog_search_candidates(store, query)
    matches = graph._catalog_search_has_matches(query, candidates, by_name)
    return {"status": "ok" if matches else "no_matches", "exercises": candidates if matches else []}


def _exercise_history(turn: PlayerToolTurn, **kwargs: Any) -> dict[str, Any]:
    from agent import assistant_graph as graph
    args = ExerciseHistoryArgs(**kwargs)
    ledger, store = turn.handles
    if args.scope == "latest_session":
        comparison = graph._session_comparison_context(ledger)
        if comparison is None:
            return {"status": "unavailable"}
        if args.exercise_id or args.exercise_name:
            matches = graph._history_exercise_matches(args.exercise_id or args.exercise_name, comparison.get("exercises", []))
            return {"status": "ok" if matches else "no_matches", **comparison, "exercises": matches}
        return {"status": "ok", **comparison}
    if not args.exercise_id and not args.exercise_name:
        return {"status": "needs_exercise"}
    entry = store.get_exercise_library_entry(args.exercise_id) if args.exercise_id else None
    resolved = (args.exercise_id, entry["name"]) if entry else graph._resolve_arabic_history_exercise(
        ledger.get_active_program(), store, args.exercise_name or "")
    if resolved is None:
        return {"status": "needs_clarification"}
    exercise_id, name = resolved
    return {"status": "ok", "exercise": name, "sets": ledger.get_last_performance(exercise_id),
            "description": graph.describe_exercise(store, exercise_id, name),
            "message": "Last logged occurrence; date and progress comparison are unavailable."}


def _substitute_exercise(turn: PlayerToolTurn, **kwargs: Any) -> dict[str, Any]:
    from agent import assistant_graph as graph
    args = SubstitutionArgs(**kwargs)
    ledger, store = turn.handles
    metadata = {"source_exercise": args.source_exercise, "target_exercise": args.target_exercise,
                "source_day": args.day_name}
    if not args.target_exercise:
        # An alternatives read grants no write permission, regardless of wording.
        from langchain_core.messages import HumanMessage
        query = f"alternatives for {args.source_exercise}"
        if args.day_name:
            query += f" on {args.day_name}"
        result = graph.exercise_substitution_node({**turn.state, "intent_metadata": {**metadata, "read_only": True},
            "messages": [HumanMessage(content=query)]}, turn.config)
        return {"status": "ok", "alternatives": result.get("model_context_content", result["response_content"])}
    if graph._is_arabic_dominant(turn.query):
        if not graph.RE_ARABIC_SWAP_REQUEST.search(graph.RE_ARABIC_DIACRITICS.sub("", turn.query)):
            return turn.finish(graph._response(graph.AUTHORIZATION_RESPONSE))
        program = ledger.get_active_program()
        source = graph._resolve_arabic_source(program, args.source_exercise, args.day_name) if program else None
        target = graph._resolve_arabic_target(store, source[1], source[0], args.target_exercise) \
            if source and args.target_exercise else None
        if source and target:
            metadata = graph._arabic_swap_metadata(source[0], source[1], *target)
            return turn.finish(graph._apply_validated_swap(turn.state, turn.config, metadata))
        return turn.finish(graph._response(graph.ARABIC_SWAP_CLARIFICATION_RESPONSE))
    state = {**turn.state, "intent_metadata": metadata}
    return turn.finish(graph.exercise_substitution_node(state, turn.config))


def _preview_rebuild(turn: PlayerToolTurn, **kwargs: Any) -> dict[str, Any]:
    from agent import assistant_graph as graph
    from agent.ProgramState import PersistedProgramSchema
    from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline
    from agent.program_rules import valid_splits_for
    from agent.program_blueprints import match_split_keyword, resolve_split_type
    from service.chat_program_edit import plan_chat_program_rebuild

    args = RebuildArgs(**kwargs)
    ledger, store = turn.handles
    account_id = turn.state.get("player_account_id")
    if not graph.programs_service.player_controls_program(store, ledger, account_id):
        return turn.finish(graph._response(graph._coach_program_refusal(turn.query),
            request_suggestion=graph._split_change_request_suggestion(turn.query,
                {"target_frequency": args.days, "split_preference": args.split_type})))
    profile = ledger.get_player_profile() or {}
    active = ledger.get_active_program()
    days = args.days or getattr(active, "weekly_frequency", None) or profile.get("weekly_frequency")
    if type(days) is not int or days not in range(1, 6):
        return _rebuild_failure(turn, "needs_days")
    choices = dict(valid_splits_for(days, profile.get("gender", "male")))
    split_type = args.split_type or graph._current_split_family(active)
    if split_type not in choices:
        split_type = resolve_split_type(match_split_keyword(split_type) or "", days)
    if args.split_type and split_type not in choices:
        return _rebuild_failure(turn, "unsupported_split")
    request = ProgramGenerationRequest(frequency_override=days,
        split_id_override=split_type if split_type in choices else None,
        previous_exercise_ids=tuple(str(row.exercise_id) for day in active.days
                                     for row in day.exercises) if active else ())
    try:
        generated, _markdown = generate_program_draft_pipeline(request, ledger=ledger, profile=profile)
        planned = plan_chat_program_rebuild(store, ledger, account_id,
                                          PersistedProgramSchema.model_validate(generated.model_dump()))
        if "error" in planned:
            return _rebuild_failure(turn, planned["error"])
        return _save_preview(turn, planned["proposal"])
    except (ValueError, sqlite3.Error) as exc:
        log_turn_exception(graph.logger, "Program rebuild preview could not be generated", exc)
        return _rebuild_failure(turn, "generation_failed")


def _rebuild_failure(turn: PlayerToolTurn, reason: str) -> dict[str, Any]:
    from agent import assistant_graph as graph
    if reason == "coach_controls":
        return turn.finish(graph._response(graph._coach_program_refusal(turn.query)))
    copy = {
        "needs_days": ("How many days per week should I use for the rebuild preview? Nothing changed.",
                       "تمام، تحب معاينة إعادة بناء البرنامج تبقى كام يوم في الأسبوع؟ مفيش حاجة اتغيرت."),
        "unsupported_split": ("That split is not available for the requested number of days. Choose an available split or change the days; nothing changed.",
                              "التقسيمة دي مش متاحة لعدد الأيام المطلوب. اختار تقسيمة متاحة أو غيّر عدد الأيام؛ مفيش حاجة اتغيرت."),
        "no_program": ("There is no active program to rebuild. Nothing changed.",
                       "مفيش برنامج حالي أقدر أعيد بناءه. مفيش حاجة اتغيرت."),
    }
    default = ("I couldn't generate the program rebuild preview. Nothing changed; please try the rebuild again.",
               "مقدرتش أجهز معاينة إعادة بناء البرنامج. مفيش حاجة اتغيرت؛ جرّب تطلب إعادة البناء تاني.")
    english, arabic = copy.get(reason, default)
    reply = arabic if graph._tool_reply_language(turn.state) == "ar" else english
    return turn.finish(graph._response(reply))


def _save_preview(turn: PlayerToolTurn, proposal: dict[str, Any]) -> dict[str, Any]:
    from agent import assistant_graph as graph
    ledger, _store = turn.handles
    language = graph._tool_reply_language(turn.state)
    summary = graph._chat_edit_summary(proposal, language)
    reply = (f"Program rebuild preview:\n{summary}\n\nConfirm or cancel." if language == "en"
             else f"تمام، دي معاينة إعادة بناء البرنامج:\n{summary}\n\nأكد أو ألغِ.")
    reply = graph.finalize_coach_output(reply)
    preview_id = ledger.set_pending_chat_program_edit(proposal, reply)
    pending = {"offer_id": preview_id, "proposal": proposal}
    return turn.finish({**graph._response(reply), "program_edit_preview": graph._program_edit_preview_payload(pending)})


def _confirm_program_edit(turn: PlayerToolTurn) -> dict[str, Any]:
    from agent import assistant_graph as graph
    ledger, _store = turn.handles
    if (turn.state.get("tool_action_result") or {}).get("program_edit_preview"):
        return {"status": "awaiting_separate_confirmation"}
    pending = ledger.get_pending_chat_program_edit()
    previous = next((graph._get_message_text(message) for message in reversed(turn.state["messages"][:-1])
                     if isinstance(message, graph.AIMessage)), "")
    if pending is None or previous.strip() != pending["offer_text"].strip():
        return {"status": "no_current_preview"}
    answer = graph._program_edit_confirmation_kind(turn.query, pending)
    state = {**turn.state, "intent_metadata": {"preview_id": pending["offer_id"],
             "confirm": answer == "yes", "include_optional": graph._chat_edit_optional_selection(turn.query, pending)}}
    handler = graph.program_edit_confirmation_node if answer in {"yes", "no"} else graph.program_edit_reprompt_node
    return turn.finish(handler(state, turn.config))


def _update_injury(turn: PlayerToolTurn) -> dict[str, Any]:
    from agent import assistant_graph as graph
    route = graph._injury_update_route(turn.state, turn.config)
    handlers = {
        "injury_area_clarification": graph.injury_area_clarification_node,
        "injury_status_update": graph.injury_status_update_node,
        "injury_physician_followup": graph.injury_physician_followup_node,
        "exercise_clearance_update": graph.injury_clearance_update_node,
        "exercise_clearance_disambiguation": graph.exercise_clearance_disambiguation_node,
    }
    handler = handlers.get(route.get("intent"))
    return turn.finish(handler({**turn.state, **route}, turn.config)) if handler else {"status": "needs_clarification"}


def _update_preference(turn: PlayerToolTurn) -> dict[str, Any]:
    from agent import assistant_graph as graph
    ledger, _store = turn.handles
    result = graph._preference_write_intent(turn.query, ledger, turn.state["messages"])
    if result is None:
        return {"status": "needs_explicit_request"}
    if result.get("intent") == "assistant_preference_delete_confirmed":
        return turn.finish(graph.assistant_preference_delete_node({**turn.state, **result}, turn.config))
    return turn.finish(graph._response(result["intent_metadata"]["response_content"]))


def build_player_chat_tools(state: dict[str, Any], config: dict[str, Any] | None):
    from agent import assistant_graph as graph
    turn = PlayerToolTurn(state, config)
    ledger, store = turn.handles
    tools, definitions = build_player_read_tools(ledger, store, state.get("player_account_id"))
    operations = [
        ("search_exercises", "Search the Exercise library by exercise name, muscle or equipment; never program types.",
         ExerciseSearchArgs, lambda **args: _search_exercises(turn, **args)),
        ("get_exercise_history", "Read latest-session comparisons by exercise_name/exercise_id, or its last logged occurrence. Translate names to English; omit scope names for the whole latest session. Arbitrary date ranges are unavailable.",
         ExerciseHistoryArgs, lambda **args: _exercise_history(turn, **args)),
        ("get_player_telemetry", "Read saved training telemetry and fatigue facts; never infer logged figures from the user's question.",
         EmptyToolArgs, lambda: {"telemetry": ledger.get_compact_telemetry()}),
        ("substitute_exercise", "Replace a named program exercise only on an explicit swap directive. Copy source/day from program; translate target to English. Omit target to request alternatives without saving.",
         SubstitutionArgs, lambda **args: _substitute_exercise(turn, **args)),
        ("preview_program_rebuild", "Generate the actual exercises and sets NOW when the Player requests a rebuild, including the CURRENT split with fresh exercise choices. Omit days/split_type to keep the current program. Also use when yes/generate answers an offer to generate a preview and no real preview exists. Never substitute a muscle-group overview or ask permission to generate again. Use split_type from list_program_options; supported display names are also accepted. Never saves the program; a later user turn must confirm the generated preview.",
         RebuildArgs, lambda **args: _preview_rebuild(turn, **args)),
        ("preview_program_edit", "Prepare requested day additions/removals/set changes from the original message; does not save. Ask a separate confirmation.",
         EmptyToolArgs, lambda: turn.finish(graph.program_edit_chat_node(state, config))),
        ("confirm_program_edit", "Answer the latest REAL program preview. Confirm/cancel only on a clear affirmative/negative; generate or an unclear answer redisplays its exercises and sets and asks for confirmation without saving. If no real preview exists, use preview_program_rebuild to answer a request to generate one. Code validates the original reply and pending offer; no confirmation argument is accepted.",
         EmptyToolArgs, lambda: _confirm_program_edit(turn)),
        ("choose_deload", "Apply or undo a one-workout Deload only on the Player's explicit directive; code validates the original message.",
         EmptyToolArgs, lambda: turn.finish(graph.deload_choice_node(
             {**state, "intent_metadata": {"choice": graph._deload_choice(turn.query)}}, config))),
        ("update_injury", "Record a Player-reported physician visit, clearance, injury area or resolution confirmation; never diagnose or infer clearance.",
         EmptyToolArgs, lambda: _update_injury(turn)),
        ("manage_assistant_preference", "Remember/forget a preference only on an explicit request; deleting requires the existing separate confirmation.",
         EmptyToolArgs, lambda: _update_preference(turn)),
        ("update_training_goal", "Save an explicitly stated current/long-term goal or answer its focus-muscle offer; code checks the original message.",
         EmptyToolArgs, lambda: _profile_update(turn, graph._goal_write_intent)),
        ("update_weak_points", "Save explicitly stated Weak points; code validates the original request and whether the Coach manages the program.",
         EmptyToolArgs, lambda: _profile_update(turn, graph._weak_point_write_intent)),
        ("update_movement_restrictions", "Answer a pending Movement restriction offer; code validates the original message and offer before saving.",
         EmptyToolArgs, lambda: _profile_update(turn, graph._movement_restriction_chat_intent)),
        ("preferred_name", "Save an explicitly requested preferred name or recall the saved name from the original message.",
         EmptyToolArgs, lambda: turn.finish(graph._response(graph._name_response(state, ledger) or "Please state the name you want me to use."))),
    ]
    for name, description, schema, operation in operations:
        def invoke(_operation=operation, **args):
            return _encode_tool_result(_operation(**args))
        tools.append(StructuredTool.from_function(func=invoke, name=name, description=description, args_schema=schema))
        definitions[name] = PlayerReadTool(name, description, schema, operation,
                                         "Checking your request…", "ببص على طلبك…")
    return tools, definitions


def _profile_update(turn: PlayerToolTurn, operation) -> dict[str, Any]:
    from agent import assistant_graph as graph
    ledger, store = turn.handles
    fourth = turn.state.get("player_account_id") if operation is graph._weak_point_write_intent else turn.state
    result = operation(turn.query, ledger, store, fourth)
    return turn.finish(result) if result is not None else {"status": "needs_explicit_request"}


_ACTION_NAMES = frozenset({
    "substitute_exercise", "preview_program_rebuild", "preview_program_edit", "confirm_program_edit",
    "choose_deload", "update_injury", "manage_assistant_preference", "update_training_goal",
    "update_weak_points", "update_movement_restrictions", "preferred_name",
})


def run_player_chat_tool_calls(tool_calls, **options):
    """Writes finish on the calling thread; no timeout can leave a write running."""
    if not any(call.get("name") in _ACTION_NAMES for call in tool_calls):
        return run_player_tool_calls(tool_calls, **options)
    by_name = {tool.name: tool for tool in options["tools"]}
    messages, metrics = [], []
    for call in tool_calls:
        name = call.get("name")
        started = time.perf_counter()
        definition = options["definitions"].get(name)
        if definition is None or name not in by_name:
            result = '{"status":"unavailable"}'
        else:
            callback = options.get("status_callback")
            if callback is not None:
                callback(definition.status_ar if options["language"] == "ar" else definition.status_en)
            try:
                result = by_name[name].invoke(call.get("args") or {})
            except ValidationError:
                result = '{"status":"invalid_arguments"}'
        messages.append(ToolMessage(content=result, name=name, tool_call_id=call["id"]))
        metrics.append((name, (time.perf_counter() - started) * 1000))
    return messages, metrics
