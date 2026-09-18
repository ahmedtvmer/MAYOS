from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from tests.test_context_management import graph as graph_fixture, state
from utils.text_scrubber import CoachOutputScrubber, EMPTY_RESPONSE_FALLBACK, PIPELINE_ERROR_RESPONSE, finalize_coach_output, scrub_coach_output


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
    graph.llm.invoke.return_value = AIMessage(content=raw)
    graph.llm.stream = MagicMock(return_value=iter([AIMessageChunk(content=raw[:10]), AIMessageChunk(content=raw[10:])]))
    request = state("How many squat reps?")
    original = list(request["messages"])
    shown = list(graph.stream_assistant_turn(request))
    saved = MagicMock()
    saved.add_chat_message("assistant", request["response_content"])
    display = "".join(shown)
    assert display == finalize_coach_output(raw)
    assert request["messages"][:-1] == original
    assert display == request["messages"][-1].content == saved.add_chat_message.call_args.args[1]
    assert graph.generation_node(state("How many squat reps?"))["response_content"] == display
    assert graph.assistant_graph.invoke(state("How many squat reps?"))["response_content"] == display


def test_partial_failure_preserves_sanitized_display_and_state(graph):
    def fail():
        yield AIMessageChunk(content="<think>private reasoning</think>Sure! Use controlled reps. ")
        yield AIMessageChunk(content="You have tendonitis")
        raise RuntimeError("internal database secret")
    graph.llm.stream = MagicMock(return_value=fail())
    request = state("How many squat reps?")
    shown = "".join(graph.stream_assistant_turn(request))
    assert shown == "Use controlled reps. [Consult a sports physician regarding joint pain]\n\n" + PIPELINE_ERROR_RESPONSE
    assert shown == request["response_content"] == request["messages"][-1].content
    assert "private" not in shown and "secret" not in shown


@pytest.mark.parametrize("stage", ["hydrate", "router", "handler", "generation"])
def test_graph_and_stream_failures(graph, stage):
    request = state("How many squat reps?")
    if stage == "hydrate":
        request["telemetry_context"] = None
        graph.db.get_user_profile.side_effect = RuntimeError("private detail")
    elif stage == "router":
        graph.evaluate_clinical_semantic_guard.side_effect = RuntimeError("private detail")
    elif stage == "handler":
        request = state("last logged occurrence of squats")
        graph.db.catalog_conn.cursor.return_value.fetchall.return_value = [("squat", "Squat")]
        graph.db.get_last_performance.side_effect = RuntimeError("private detail")
    else:
        graph.llm.invoke.side_effect = RuntimeError("private detail")
        graph.llm.stream = MagicMock(side_effect=RuntimeError("private detail"))
    assert graph.assistant_graph.invoke(request)["response_content"] == PIPELINE_ERROR_RESPONSE
    assert list(graph.stream_assistant_turn(request)) == [PIPELINE_ERROR_RESPONSE]


def test_finish_limit_preserves_partial_answer(graph):
    graph.llm.invoke.return_value = AIMessage(content="Cut off", response_metadata={"finish_reason": "length"})
    graph.llm.stream = MagicMock(return_value=iter([AIMessageChunk(content="Cut off", response_metadata={"finish_reason": "length"})]))
    expected = "Cut off\n\n" + graph.OUTPUT_LIMIT_RESPONSE
    assert graph.generation_node(state("How many squat reps?"))["response_content"] == expected
    request = state("How many squat reps?")
    assert "".join(graph.stream_assistant_turn(request)) == expected
    assert request["response_content"] == request["messages"][-1].content == expected


def test_words_visible_before_sentence_or_generation_finishes(graph):
    consumed = []

    def produce():
        for text in ["Use ", "controlled ", "reps", "."]:
            consumed.append(text)
            yield AIMessageChunk(content=text)
        consumed.append("finished")

    graph.llm.stream = MagicMock(return_value=produce())
    request = state("How many squat reps?")
    stream = graph.stream_assistant_turn(request)
    first = next(stream)
    assert first == "Use"
    assert consumed == ["Use "]
    second = next(stream)
    assert second == " controlled"
    assert consumed == ["Use ", "controlled "]
    output = first + second + "".join(stream)
    assert output == "Use controlled reps."
    assert output == request["response_content"] == request["messages"][-1].content


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


def test_ui_is_thin_client_over_authoritative_service():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    # No direct ledger, graph, or model access from the UI process.
    for forbidden in ("DatabaseManager(", "stream_assistant_turn", "onboarding_graph", "generate_program_pipeline", "get_llm"):
        assert forbidden not in source
    # Dialogue renders from the service ledger and streams server tokens without reconstructing answers.
    assert 'api("GET", "/chat/history")' in source
    assert "/chat/messages" in source
    assert "st.write_stream" in source
    # Persistence lives server-side: the chat router saves the authoritative response.
    server = (Path(__file__).resolve().parents[1] / "svc" / "routers" / "chat.py").read_text()
    assert "persist_assistant_message" in server
