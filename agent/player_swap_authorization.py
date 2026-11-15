"""Bind selected substitutions to affirmative clauses in the current Player message."""

import re
from typing import Any

from agent.context_router import _exercise_mentions, _normalize

_UNCERTAIN_SWAP = re.compile(
    r"[?؟]|\b(?:not|never|no|maybe|perhaps|should|would|might|consider|thinking|if|unless|don['’]t|won['’]t|can['’]t)\b|"
    r"(?:^|\s)(?:مش|لا|لن|ما|هل|ممكن|يمكن|لو|نفسي|بفكر|يمكنني|ربما|لعل|أظن|اظن)(?:\s|$)", re.I,
)


def _swap_clause(clause: str) -> tuple[str, str] | None:
    from agent import assistant_graph as graph

    clause = graph.RE_ARABIC_DIACRITICS.sub("", clause).replace("ـ", "").strip()
    if _UNCERTAIN_SWAP.search(clause):
        return None
    english = graph.RE_EXPLICIT_SWAP.fullmatch(graph._action_command(clause))
    if english:
        return english.group("source"), english.group("target")
    arabic = graph.RE_ARABIC_SWAP_REQUEST.match(clause)
    if arabic is None:
        return None
    names = re.fullmatch(r"(.+?)\s+ب(?:تمرين\s+|\s*)?(.+)", clause[arabic.end():])
    return (names[1], names[2]) if names else None


def _exercise_name(text: str) -> str:
    text = re.sub(r"^(?:(?:the|my|a|an|تمرين|الـ|ال)\s+)+", "", text.strip(), flags=re.I)
    text = re.sub(r"\s+يا\s+كابتن$", "", text).strip(" .!,")
    aliases = {
        "البنش": "bench press", "بنش": "bench press",
        "السكوات": "back squat", "الدامبل": "dumbbell bench press",
        "دامبل": "dumbbell bench press", "ضغط مائل بالبار": "barbell incline bench press",
        "الليج برس": "leg press", "ليج برس": "leg press",
    }
    return aliases.get(_normalize(text), text)


def _named_source(program: Any, store: Any, name: str, day: str | None):
    from agent import assistant_graph as graph

    name = graph.expand_fitness_abbreviations(_exercise_name(name))
    days = [row for row in program.days if day is None or row.day_name == day]
    normalized = _normalize(name)
    mentions = _exercise_mentions(normalized, days, store)
    covered = set(index for match in mentions for index in range(match.start, match.end))
    if any(not char.isspace() and index not in covered for index, char in enumerate(normalized)):
        return _source_from_words(program, name, day)
    mentioned = {match.key for match in mentions}
    matches = [(row, exercise) for row in days for exercise in row.exercises
               if str(exercise.exercise_id) in mentioned]
    if len(matches) != 1 or len(mentioned) != 1:
        return None
    if set(normalized.split()) < set(_normalize(matches[0][1].exercise_name).split()):
        return _source_from_words(program, name, day)
    return matches[0]


def _source_from_words(program: Any, name: str, day: str | None):
    from agent import assistant_graph as graph

    source = graph._resolve_arabic_source(program, name, day)
    if source is None or not set(_normalize(name).split()) <= set(_normalize(source[1].exercise_name).split()):
        return None
    return source


def authorized_swap_metadata(turn: Any, args: Any) -> dict[str, Any] | None:
    ledger, store = turn.handles
    program = ledger.get_active_program()
    if program is None:
        return None
    for clause in _affirmative_swap_clauses(turn.query):
        names = _swap_clause(clause)
        if names is not None:
            metadata = _matching_swap(program, store, names, args)
            if metadata is not None:
                return metadata
    return None


def _affirmative_swap_clauses(query: str):
    from agent import assistant_graph as graph

    # Negation/question scope must survive conjunction splitting.
    for sentence in re.split(r"(?<=[.;؛\n])", graph.RE_ARABIC_DIACRITICS.sub("", query)):
        if not _UNCERTAIN_SWAP.search(sentence):
            yield from re.split(r"\s+(?:and(?:\s+also|\s+then)?|also|then|plus)\s+|\s+و(?=قول)", sentence, flags=re.I)


def _matching_swap(program: Any, store: Any, names: tuple[str, str], args: Any):
    from agent import assistant_graph as graph

    requested_day = graph._requested_substitution_day(program, " ".join(names))
    source_name, target_name = (graph._remove_day_suffix(name, requested_day) for name in names)
    source = _named_source(program, store, source_name, requested_day)
    selected = _named_source(program, store, args.source_exercise, requested_day)
    if source is None or selected is None or source != selected:
        return None
    if args.day_name is not None and args.day_name != source[0].day_name:
        return None
    target = graph._resolve_arabic_target(store, source[1], source[0], _exercise_name(target_name))
    selected_target = graph._resolve_arabic_target(store, source[1], source[0], args.target_exercise)
    if target is None or selected_target is None or target[0] != selected_target[0]:
        return None
    return graph._arabic_swap_metadata(source[0], source[1], *target)
