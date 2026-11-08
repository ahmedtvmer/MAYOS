"""Deterministic Program Context pieces for hosted Player chat (ADR 105)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent.focus_muscles import FOCUS_REGION_POLICY, FOCUS_REVIEW_MUSCLES
from agent.player_prompt import (
    HOSTED_PROMPT_MAX_BYTES, HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES,
    get_message_text, message_role,
)
from agent.player_tools import run_player_tool_calls
from core.weak_point_suggestions import WEAK_POINT_ALIASES

MAX_CONTEXT_PIECE_BYTES = 8 * 1024
PROGRAM_TOPIC = "program_what_how_many"
_PROGRAM = re.compile(r"\b(?:program|routine|split|(?:training|workout) plan)\b|برنامج|برنامجي|تقسيم", re.I)
_QUESTION = re.compile(
    r"\b(?:what|how|which|show|list|tell|sets?|reps?|frequency|often|volume)\b|"
    r"ايه|إيه|كام|كم|ازاي|إزاي|وريني|تمارين|سيتات|مجموعات|عدات|تكرار", re.I,
)
_OTHER_TOPIC = re.compile(
    r"\b(?:why|rationale|progress|history|last|yesterday|lifted|ate|calories|nutrition|technique|form|cue|pain|hurts?|injury)\b|"
    r"ليه|السبب|اتحسن|تقدمي|امبارح|اكلت|سعرات|تغذي|وجع|اصاب|\bاخر\b|(?:عملت|رفعت)\s+(?:كام|كم)", re.I,
)
_PROGRAM_MEASURE = re.compile(
    r"\b(?:sets?|reps?|exercises?|frequency|volume|train|workouts?)\b|"
    r"تمارين|سيتات|مجموعات|عدات|تكرار|بتمرن|بتدرب", re.I,
)
_EXTRA_MUSCLES = {
    "biceps": ("bi", "باي", "الباي"),
    "triceps": ("tri", "تراي", "التراي"),
    "quads": ("كواد", "كوادز", "رجل امامي", "الرجل الامامي"),
    "hamstrings": ("هامسترنج", "رجل خلفي", "الرجل الخلفي"),
}
_REGIONS = {
    "lower": ("leg day", "leg days", "lower day", "lower days", "lower body",
              "يوم الرجل", "ايام الرجل", "يوم الارجل", "الجزء السفلي"),
    "upper": ("upper day", "upper days", "upper body", "يوم الجزء العلوي", "الجزء العلوي"),
}
_DAY_REGIONS = {
    "lower": ("leg", "legs", "lower", "رجل", "الرجل", "ارجل", "الارجل", "سفلي"),
    "upper": ("upper", "push", "pull", "chest", "back", "arms", "علوي", "صدر", "ظهر"),
}
_WEEKDAYS = (
    ("monday", "mon", "الاثنين", "اثنين", "الاتنين", "اتنين"),
    ("tuesday", "tue", "الثلاثاء", "ثلاثاء", "التلات", "تلات"),
    ("wednesday", "wed", "الاربعاء", "اربعاء", "الاربع", "اربع"),
    ("thursday", "thu", "الخميس", "خميس"),
    ("friday", "fri", "الجمعة", "جمعة"),
    ("saturday", "sat", "السبت", "سبت"),
    ("sunday", "sun", "الاحد", "احد", "الحد", "حد"),
)
_EXERCISE_SHORT_NAMES = {
    "bench": ("bench", "بنش", "البنش"),
    "squat": ("squat", "squats", "سكوات", "السكوات"),
    "deadlift": ("deadlift", "ديدليفت"),
    "pulldown": ("pulldown", "lat pulldown"),
    "row": ("row", "rows"),
    "leg curl": ("leg curl", "leg curls"),
}


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    key: str


@dataclass(frozen=True)
class RoutedContext:
    messages: list[BaseMessage]
    topics: tuple[str, ...] = ()
    pieces: tuple[str, ...] = ()


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.translate(str.maketrans("أإآى", "اااي"))
    return re.sub(r"[^\w]+", " ", normalized).strip()


def _mentions(text: str, vocabulary: Sequence[tuple[str, str]]) -> list[_Mention]:
    matches = []
    for key, phrase in vocabulary:
        phrase = _normalize(phrase)
        if not phrase:
            continue
        # Arabic articles/conjunctions can attach to gym nicknames.
        prefix = r"(?:و|ف)?(?:لل|[بلك]?ال|[بلك])?" if re.search(r"[\u0600-\u06ff]", phrase) else ""
        for match in re.finditer(rf"(?<!\w){prefix}{re.escape(phrase)}(?!\w)", text):
            matches.append(_Mention(match.start(), match.end(), key))
    return matches


def _overlaps(left: _Mention, right: _Mention) -> bool:
    return left.start < right.end and right.start < left.end


def _longest_mentions(matches: Sequence[_Mention]) -> list[_Mention]:
    selected: list[_Mention] = []
    for match in sorted(matches, key=lambda mention: (-(mention.end - mention.start), mention.start)):
        # Identical spans may name both arm muscles; retain both.
        if not any(_overlaps(match, prior) and (match.start, match.end) != (prior.start, prior.end)
                   for prior in selected):
            selected.append(match)
    return sorted(selected, key=lambda mention: mention.start)


def _muscle_mentions(text: str) -> list[_Mention]:
    vocabulary = [
        (muscle, alias) for muscle, aliases in WEAK_POINT_ALIASES
        for alias in (muscle, muscle.replace("_", " "), *aliases, *_EXTRA_MUSCLES.get(muscle, ()))
    ]
    return _longest_mentions(_mentions(text, vocabulary))


def _active_exercise_short_names(active_names: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(exercise_id, alias) for exercise_id, name in active_names
            for stem, aliases in _EXERCISE_SHORT_NAMES.items()
            if _mentions(_normalize(name), [(stem, stem)]) for alias in aliases]


def _exercise_mentions(text: str, days: Sequence[Any], store: Any) -> list[_Mention]:
    active_names = list(dict.fromkeys(
        (str(exercise.exercise_id), exercise.exercise_name)
        for day in days for exercise in day.exercises
    ))
    vocabulary = store.get_exercise_name_vocabulary() if store is not None else []
    active_ids = {exercise_id for exercise_id, _name in active_names}
    active = _longest_mentions(_mentions(text, active_names + [
        (exercise_id, alias) for exercise_id, alias in vocabulary if exercise_id in active_ids
    ]))
    short_names = _longest_mentions(_mentions(text, _active_exercise_short_names(active_names)))
    catalog = _catalog_exercise_mentions(text, vocabulary, active, short_names)
    selected = active + catalog
    return selected + [match for match in short_names
                       if not any(_overlaps(match, prior) for prior in selected)]


def _catalog_exercise_mentions(text, vocabulary, active, short_names) -> list[_Mention]:
    # Bare library aliases like "bench" must not override the Player's own variant.
    return [match for match in _longest_mentions(_mentions(text, vocabulary))
            if not any(_overlaps(match, prior) for prior in active)
            and not any(_overlaps(match, short) and match.end - match.start <= short.end - short.start
                        for short in short_names)]


def _day_has_region(day: Any, region: str, targets: dict[str, str]) -> bool:
    name = _normalize(day.day_name)
    named_regions = {match.key for match in _mentions(name, [
        (key, word) for key, words in _DAY_REGIONS.items() for word in words
    ])}
    if named_regions:
        return region in named_regions
    # Full-body days load both regions; a lower day may also have arm isolations.
    muscles = {group for exercise in day.exercises
               for group, names in FOCUS_REVIEW_MUSCLES.items()
               if targets.get(str(exercise.exercise_id), "").casefold() in names}
    regions = {FOCUS_REGION_POLICY[muscle]["home_region"] for muscle in muscles}
    return region in regions


def _weekday_day_names(text: str, days: Sequence[Any]) -> set[str]:
    selected: set[str] = set()
    for aliases in _WEEKDAYS:
        if _mentions(text, [(aliases[0], alias) for alias in aliases]):
            matching_days = [day.day_name for day in days if _mentions(
                _normalize(day.day_name), [(aliases[0], alias) for alias in aliases]
            )]
            selected.update(matching_days or [aliases[0]])
    return selected


def _region_day_names(text: str, days: Sequence[Any], ledger: Any) -> set[str]:
    selected: set[str] = set()
    regions = {match.key for match in _mentions(
        text, [(region, alias) for region, aliases in _REGIONS.items() for alias in aliases]
    )}
    if regions:
        targets = ledger.volume_review_exercise_targets(
            [str(exercise.exercise_id) for day in days for exercise in day.exercises]
        )
        for region in regions:
            matching_days = [day.day_name for day in days if _day_has_region(day, region, targets)]
            selected.update(matching_days or [_REGIONS[region][0]])
    return selected


def _day_mentions(text: str, days: Sequence[Any], ledger: Any) -> list[str]:
    selected = {match.key for match in _longest_mentions(_mentions(
        text, [(day.day_name, day.day_name) for day in days]
    ))}
    selected.update(_weekday_day_names(text, days))
    selected.update(_region_day_names(text, days, ledger))
    order = {day.day_name: index for index, day in enumerate(days)}
    return sorted(selected, key=lambda name: (order.get(name, len(days)), name))


def _program_days(ledger: Any) -> list[Any]:
    program = ledger.get_active_program()
    if program is None:
        return []
    week = ledger.get_program_position(program).current_week
    return sorted([day for day in program.days if day.week_order == week], key=lambda day: day.day_order)


def _day_words(days: Sequence[Any]) -> list[tuple[str, str]]:
    return ([(day.day_name, day.day_name) for day in days]
            + [(region, alias) for region, aliases in _REGIONS.items() for alias in aliases]
            + [(aliases[0], alias) for aliases in _WEEKDAYS for alias in aliases])


def _without_day_names(text: str, days: Sequence[Any]) -> str:
    # Day labels such as Chest & Back scope the whole day, not only those muscles.
    characters = list(text)
    for match in _mentions(text, _day_words(days)):
        characters[match.start:match.end] = " " * (match.end - match.start)
    return "".join(characters)


def _program_scopes(text: str, ledger: Any, store: Any) -> list[dict[str, str]]:
    days = _program_days(ledger)
    day_names = _day_mentions(text, days, ledger)
    scope_text = _without_day_names(text, days)
    exercises = _exercise_mentions(scope_text, days, store)
    muscles = [match.key for match in _muscle_mentions(scope_text)
               if not any(_overlaps(match, exercise) for exercise in exercises)]
    named_scopes = ([{"exercise_id": key} for key in dict.fromkeys(match.key for match in exercises)]
                    + [{"muscle": muscle} for muscle in dict.fromkeys(muscles)])
    if day_names:
        return [{"day_name": day, **scope} for day in day_names for scope in (named_scopes or [{}])]
    return named_scopes or [{}]


def _program_question(text: str, ledger: Any, store: Any) -> bool:
    if not _QUESTION.search(text) or _OTHER_TOPIC.search(text):
        return False
    if _PROGRAM.search(text) or _muscle_mentions(text):
        return True
    if _PROGRAM_MEASURE.search(text):
        return True
    days = _program_days(ledger)
    return bool(_mentions(text, _day_words(days)) or _exercise_mentions(text, days, store))


def _piece_name(scope: dict[str, str]) -> str:
    fields = [name for name in ("day_name", "exercise_id", "muscle") if name in scope]
    return "program." + ("+".join(fields) if fields else "overview")


def _context_calls(scopes: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"name": "get_active_program", "args": scope,
             "id": f"context-program-{index + 1}", "type": "tool_call"}
            for index, scope in enumerate(scopes)]


def route_player_context(
    messages: Sequence[BaseMessage], ledger: Any, store: Any, tool_context: dict[str, Any],
) -> RoutedContext:
    """Add bounded simulated reads only at hosted-model entry, after deterministic gates."""
    latest = next((get_message_text(message) for message in reversed(messages)
                   if message_role(message) == "user"), "")
    text = _normalize(latest)
    if ledger is None or not _program_question(text, ledger, store):
        return RoutedContext(list(messages))
    scopes = _program_scopes(text, ledger, store)
    calls = _context_calls(scopes)
    results, _metrics = run_player_tool_calls(calls, **tool_context)
    return _bounded_context(messages, calls, results)


def _bounded_context(
    messages: Sequence[BaseMessage], calls: Sequence[dict[str, Any]], results: Sequence[ToolMessage],
) -> RoutedContext:
    available = _available_context_bytes(messages)
    included_calls, included_results, pieces = [], [], []
    for call, result in zip(calls, results):
        size = len(str(result.content).encode("utf-8")) + len(
            json.dumps(call, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if size <= available:
            included_calls.append(call)
            included_results.append(result)
            pieces.append(_piece_name(call["args"]))
            available -= size
    if not included_calls:
        return RoutedContext(list(messages), (PROGRAM_TOPIC,))
    simulated = AIMessage(content="", tool_calls=included_calls)
    return RoutedContext([*messages, simulated, *included_results], (PROGRAM_TOPIC,), tuple(pieces))


def _available_context_bytes(messages: Sequence[BaseMessage]) -> int:
    # Empty/one/many and Unicode results share the content-byte ceiling used by the tool loop.
    return min(MAX_CONTEXT_PIECE_BYTES, HOSTED_PROMPT_MAX_BYTES
               - HOSTED_PROMPT_TOOL_RESULT_RESERVE_BYTES
               - sum(len(str(message.content).encode("utf-8")) for message in messages))
