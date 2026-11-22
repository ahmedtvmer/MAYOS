"""Short confirmations, no pre-tool preamble, Western digits (#802, #423 option b)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent import assistant_graph
from tests.fakes.chat_model import ToolCallsTurn
from tests.test_context_management import graph as graph_fixture, state


@pytest.fixture
def graph(monkeypatch):
    return graph_fixture.__wrapped__(monkeypatch)


def _route(text, history=()):
    messages = [*history, HumanMessage(content=text)]
    return assistant_graph.router_node(
        {"messages": messages, "telemetry_context": "", "intent_metadata": {}}
    )


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        # The reported message: "I checked, all good, ready to train".
        ("راجعت و كله تمام و جاهز لتمرين", assistant_graph.ARABIC_ACKNOWLEDGEMENT_RESPONSE),
        ("تمام", assistant_graph.ARABIC_ACKNOWLEDGEMENT_RESPONSE),
        ("كله تمام، شكرا!", assistant_graph.ARABIC_ACKNOWLEDGEMENT_RESPONSE),
        ("ماشي جاهزة", assistant_graph.ARABIC_ACKNOWLEDGEMENT_RESPONSE),
        ("ok thanks", assistant_graph.ENGLISH_ACKNOWLEDGEMENT_RESPONSE),
        ("All good, ready to train!", assistant_graph.ENGLISH_ACKNOWLEDGEMENT_RESPONSE),
        ("Got it, thank you 💪", assistant_graph.ENGLISH_ACKNOWLEDGEMENT_RESPONSE),
    ],
)
def test_a_message_that_only_closes_the_topic_gets_a_short_reply(text, reply):
    route = _route(text, history=[AIMessage(content="Your program is set for four days.")])
    assert route["intent"] == "telemetry_intercept"
    assert route["intent_metadata"]["response_content"] == reply


@pytest.mark.parametrize(
    "text",
    [
        "تمام بس غيّر البنش بالدمبل",
        "جاهز، إيه تمرين النهارده؟",
        "ok, now swap bench for dumbbell press",
        "ready? what's next",
        "thanks, how many sets should I do?",
    ],
)
def test_a_confirmation_with_a_request_is_not_cut_short(text):
    route = _route(text)
    assert route.get("intent_metadata", {}).get("response_content") not in {
        assistant_graph.ARABIC_ACKNOWLEDGEMENT_RESPONSE,
        assistant_graph.ENGLISH_ACKNOWLEDGEMENT_RESPONSE,
    }


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("تحب أخلي البرنامج ٤ أيام؟", "تمام"),
        ("Should I move legs to Friday?", "ok"),
    ],
)
def test_ok_answering_an_assistant_question_is_not_a_closing_message(question, answer):
    assert assistant_graph._acknowledgement_response(
        answer, [AIMessage(content=question), HumanMessage(content=answer)]
    ) is None


def test_text_written_before_a_tool_call_is_never_shown_or_saved(graph):
    graph.llm.reset([
        ToolCallsTurn(
            calls=[{"name": "get_player_profile", "args": {}, "id": "preamble-profile"}],
            content="خليني أشوف صلاحية الـ Coach الأول.",
        ),
        "البرنامج الحالي تقدر تغيره بنفسك من تبويب Program.",
    ])
    graph.llm.chunk_size = 4
    request = state("ممكن اغير البرنامج؟")
    output = "".join(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db))

    assert "خليني أشوف" not in output
    assert output.startswith("البرنامج الحالي")
    assert "خليني أشوف" not in request["response_content"]
    assert "خليني أشوف" not in request["messages"][-1].content


def test_a_text_only_answer_still_streams_once_past_the_hold(graph):
    raw = (
        "Keep each repetition controlled and breathe steadily through the lift, "
        "then rest about two minutes before the next set so your form stays sharp. "
        "Finish the session with a light cooldown."
    )
    assert len(raw) > assistant_graph._TOOL_PREAMBLE_HOLD_CHARS
    graph.llm.reset([raw])
    graph.llm.chunk_size = 1
    request = state("How should I pace my sets?")
    stream = graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db)

    first = next(stream)
    assert graph.llm.streamed_chunk_count < len(raw)
    assert len(first) <= assistant_graph._TOOL_PREAMBLE_HOLD_CHARS
    assert first + "".join(stream) == raw


def test_arabic_indic_digits_are_shown_as_western_digits(graph):
    graph.llm.reset(["عندك ٨١ set في الأسبوع، والأفضل ١٠-٢٠ set لكل عضلة."])
    request = state("كام set في الأسبوع؟")
    output = "".join(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db))

    assert output == "عندك 81 set في الأسبوع، والأفضل 10-20 set لكل عضلة."
    assert request["response_content"] == output
