import random
import re
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from tests.fakes.chat_model import StreamErrorTurn
from tests.test_context_management import graph as graph_fixture, state
from utils.text_scrubber import (
    BANNED_LEAD_PATTERNS,
    BANNED_TRAIL_PATTERNS,
    UNSAFE_MEDICAL_PATTERNS,
    CoachOutputScrubber,
    EMPTY_RESPONSE_FALLBACK,
    PIPELINE_ERROR_RESPONSE,
    finalize_coach_output,
    scrub_coach_output,
)


@pytest.fixture
def graph(monkeypatch):
    return graph_fixture.__wrapped__(monkeypatch)


@pytest.mark.parametrize("raw,expected", [
    ("Sure thing! Here is the breakdown: Romanian deadlifts overload the lengthened hamstrings. Hope this helps!", "Romanian deadlifts overload the lengthened hamstrings."),
    ("Great question! In terms of biomechanics, the hack squat stabilizes the spine. Keep crushing it!", "The hack squat stabilizes the spine."),
    ("Certainly. As an AI, I suggest high-bar squats over low-bar for quad bias. Let me know if you have any other questions.", "I suggest high-bar squats over low-bar for quad bias."),
    ("Direct technical answer.", "Direct technical answer."),
])
def test_unit_scrubber(raw, expected):
    assert scrub_coach_output(raw) == expected


@pytest.mark.parametrize("raw", ["", "Sure thing! Hope this helps!", "Certainly."])
def test_empty_fallback(raw):
    assert finalize_coach_output(raw) == EMPTY_RESPONSE_FALLBACK


@pytest.mark.parametrize("raw", ["Sure thing! Use controlled reps. Hope this helps!", "Sure thing! Hope this helps!"])
def test_graph_stream_and_saved_parity(graph, raw):
    graph.llm.reset([raw, raw, raw])
    request = state("How many squat reps?")
    original = list(request["messages"])
    shown = list(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db))
    saved = MagicMock()
    saved.add_chat_message("assistant", request["response_content"])
    display = "".join(shown)
    assert display == finalize_coach_output(raw)
    assert request["messages"][:-1] == original
    assert display == request["messages"][-1].content == saved.add_chat_message.call_args.args[1]
    assert graph.generation_node(state("How many squat reps?"))["response_content"] == display
    assert graph.assistant_graph.invoke(state("How many squat reps?"), config={"configurable": {"ledger": graph.db, "store": graph.db}})["response_content"] == display


def test_partial_failure_preserves_sanitized_display_and_state(graph):
    graph.llm.reset([StreamErrorTurn(
        "<think>private reasoning</think>Sure! Use controlled reps. You have tendonitis",
        RuntimeError("internal database secret"),
    )])
    request = state("How many squat reps?")
    shown = "".join(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db))
    assert shown == "Use controlled reps. [Consult a sports physician regarding joint pain]\n\n" + PIPELINE_ERROR_RESPONSE
    assert shown == request["response_content"] == request["messages"][-1].content
    assert "private" not in shown and "secret" not in shown


@pytest.mark.parametrize("stage", ["hydrate", "router", "handler", "generation"])
def test_graph_and_stream_failures(graph, stage):
    request = state("How many squat reps?")
    if stage == "hydrate":
        request["telemetry_context"] = None
        graph.db.get_player_profile.side_effect = RuntimeError("private detail")
    elif stage == "router":
        graph.evaluate_clinical_semantic_guard.side_effect = RuntimeError("private detail")
    elif stage == "handler":
        request = state("last logged occurrence of squats")
        graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("squat", "Squat")]
        graph.db.get_last_performance.side_effect = RuntimeError("private detail")
    else:
        graph.llm.reset([RuntimeError("private detail"), RuntimeError("private detail")])
    assert graph.assistant_graph.invoke(request, config={"configurable": {"ledger": graph.db, "store": graph.db}})["response_content"] == PIPELINE_ERROR_RESPONSE
    assert list(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db)) == [PIPELINE_ERROR_RESPONSE]


def test_finish_limit_preserves_partial_answer(graph):
    partial = AIMessage(content="Cut off", response_metadata={"finish_reason": "length"})
    graph.llm.reset([partial, partial])
    expected = "Cut off\n\n" + graph.OUTPUT_LIMIT_RESPONSE
    assert graph.generation_node(state("How many squat reps?"))["response_content"] == expected
    request = state("How many squat reps?")
    assert "".join(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db)) == expected
    assert request["response_content"] == request["messages"][-1].content == expected


def test_words_visible_before_sentence_or_generation_finishes(graph):
    graph.llm.reset(["Use controlled reps."])
    graph.llm.chunk_size = 5
    request = state("How many squat reps?")
    stream = graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db)
    first = next(stream)
    assert first == "Use"
    assert graph.llm.streamed_chunk_count == 1
    second = next(stream)
    assert second == " controlled"
    assert graph.llm.streamed_chunk_count == 3
    output = first + second + "".join(stream)
    assert output == "Use controlled reps."
    assert output == request["response_content"] == request["messages"][-1].content


def test_stream_subdivides_a_sentence_sized_model_chunk(graph):
    raw = "Use controlled reps while keeping each repetition smooth and balanced."
    graph.llm.reset([raw])
    graph.llm.chunk_size = len(raw)
    request = state("How many squat reps?")
    stream = graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db)

    first = next(stream)
    assert graph.llm.streamed_chunk_count == 1
    second = next(stream)
    assert (first, second) == ("Use", " controlled")
    assert graph.llm.streamed_chunk_count == 1
    tail = "".join(stream)
    assert first + second + tail == raw


def test_long_sentence_releases_complete_words_before_its_end():
    words = "Build strength with controlled repetitions and steady breathing while keeping every movement smooth".split()
    scrubber = CoachOutputScrubber()
    emitted = []
    guarded_samples = [
        "You have tendonitis",
        "Train through the sharp pain",
        "Take ibuprofen",
        "Sure thing!",
        "Here's the answer.",
        "As an AI assistant.",
        "Welcome back!",
        "Let me know if you have any other questions",
    ]
    longest_guard_words = max(len(sample.split()) for sample in guarded_samples)

    for word in words[:-1]:
        piece = scrubber.feed(word + " ")
        emitted.append(piece)
        assert piece.strip() == word
        assert len(scrubber.buffer.split()) <= longest_guard_words

    assert scrubber.feed(words[-1]) == ""
    assert "".join(emitted).strip().split() == words[:-1]
    assert "smooth" not in "".join(emitted)
    assert scrubber.finish() == " smooth"


@pytest.mark.parametrize(
    ("pattern", "phrase", "kind"),
    [
        (UNSAFE_MEDICAL_PATTERNS[0], "You have tendonitis", "unsafe"),
        (UNSAFE_MEDICAL_PATTERNS[1], "Train through the sharp pain", "unsafe"),
        (UNSAFE_MEDICAL_PATTERNS[2], "Take ibuprofen", "unsafe"),
        (BANNED_LEAD_PATTERNS[0], "Sure thing!", "lead"),
        (BANNED_LEAD_PATTERNS[1], "Here's the answer.", "lead"),
        (BANNED_LEAD_PATTERNS[2], "As an AI assistant.", "lead"),
        (BANNED_LEAD_PATTERNS[3], "Welcome back!", "lead"),
        (BANNED_TRAIL_PATTERNS[0], "Hope this helps!", "trail"),
        (BANNED_TRAIL_PATTERNS[1], "Keep crushing it!", "trail"),
        (BANNED_TRAIL_PATTERNS[2], "Let me know if you have any other questions.", "trail"),
        (BANNED_TRAIL_PATTERNS[3], "Remember, consistency is key.", "trail"),
    ],
)
def test_guarded_phrases_never_leak_across_any_chunk_split(pattern, phrase, kind):
    assert pattern.match(phrase) if kind == "lead" else pattern.search(phrase)
    before = "" if kind == "lead" else "Do controlled reps. "
    after = " Use careful form." if kind == "lead" else "." if kind == "unsafe" else ""
    expected = (
        "Use careful form." if kind == "lead"
        else "Do controlled reps. [Consult a sports physician regarding joint pain]." if kind == "unsafe"
        else "Do controlled reps."
    )
    raw = before + phrase + after
    phrase_words = [word.strip("!.,:") for word in phrase.split()]

    for split in range(1, len(raw)):
        scrubber = CoachOutputScrubber()
        visible = scrubber.feed(raw[:split])
        visible += scrubber.feed(raw[split:])
        visible += scrubber.finish()
        assert visible == expected
        assert phrase.casefold() not in visible.casefold()

    scrubber = CoachOutputScrubber()
    early_visible = scrubber.feed(before + phrase)
    for word in phrase_words:
        assert not re.search(rf"\b{re.escape(word)}\b", early_visible, re.IGNORECASE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sure thing! Here is the breakdown: Romanian deadlifts overload the lengthened hamstrings. Hope this helps!", "Romanian deadlifts overload the lengthened hamstrings."),
        ("Great question! In terms of biomechanics, the hack squat stabilizes the spine. Keep crushing it!", "The hack squat stabilizes the spine."),
        ("Certainly. As an AI, I suggest high-bar squats over low-bar for quad bias. Let me know if you have any other questions.", "I suggest high-bar squats over low-bar for quad bias."),
        ("Direct technical answer.", "Direct technical answer."),
        ("", ""),
        ("Sure thing! Hope this helps!", ""),
        ("Certainly.", ""),
        ("Sure thing! Use controlled reps. Hope this helps!", "Use controlled reps."),
        ("<think>private reasoning</think>Sure! Use controlled reps. You have tendonitis", "Use controlled reps. [Consult a sports physician regarding joint pain]"),
        ("Use controlled reps.", "Use controlled reps."),
        ("Cut off", "Cut off"),
        ("<think>private</think>Use controlled reps.<|im_end|>hidden", "Use controlled reps."),
        ("Use controlled reps. You have tendonitis", "Use controlled reps. [Consult a sports physician regarding joint pain]"),
        ("Please do not train through the sharp pain.", "Please do not [Consult a sports physician regarding joint pain]."),
        ("Use controlled reps and try ibuprofen.", "Use controlled reps and [Consult a sports physician regarding joint pain]."),
        ("Use controlled reps\n\nRest between sets.", "Use controlled reps\n\nRest between sets."),
    ],
)
def test_streamed_chunks_match_existing_scrubbed_text(raw, expected):
    chunkings = [[1] * len(raw), [max(1, len(raw))]]
    rng = random.Random(len(raw))
    for _ in range(20):
        chunk_sizes = []
        remaining = len(raw)
        while remaining:
            size = rng.randint(1, min(17, remaining))
            chunk_sizes.append(size)
            remaining -= size
        chunkings.append(chunk_sizes)

    for chunk_sizes in chunkings:
        scrubber = CoachOutputScrubber()
        visible = []
        cursor = 0
        for size in chunk_sizes:
            visible.append(scrubber.feed(raw[cursor:cursor + size]))
            cursor += size
        visible.append(scrubber.finish())
        assert "".join(visible) == expected


@pytest.mark.parametrize("raw,expected", [
    ("<think>private</think>Use controlled reps.<|im_end|>hidden", "Use controlled reps."),
    ("Use controlled reps. You have tendonitis", "Use controlled reps. [Consult a sports physician regarding joint pain]"),
    ("Please do not train through the sharp pain.", "Please do not [Consult a sports physician regarding joint pain]."),
    ("Sure thing! Use controlled reps. Hope this helps!", "Use controlled reps."),
    ("Use controlled reps and try ibuprofen.", "Use controlled reps and [Consult a sports physician regarding joint pain]."),
    ("Use controlled reps\n\nRest between sets.", "Use controlled reps\n\nRest between sets."),
])
def test_incremental_output_independent_of_chunk_boundaries(raw, expected):
    for size in range(1, len(raw) + 1):
        scrubber = CoachOutputScrubber()
        chunks = [scrubber.feed(raw[start:start + size]) for start in range(0, len(raw), size)]
        chunks.append(scrubber.finish())
        assert "".join(chunks) == expected
        assert "private" not in "".join(chunks)
        assert "tendonitis" not in "".join(chunks)
        assert "ibuprofen" not in "".join(chunks)
