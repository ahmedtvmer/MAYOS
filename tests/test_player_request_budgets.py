import json
from dataclasses import dataclass, field

import httpx
import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph, fitness_abbreviations, program_rules
from service import checkpoint_review_ai
from utils import model_downloader
from utils.player_output_budgets import CALL_SITE_BUDGETS

MOCK_RESPONSES = {
    "chat_reply": "Try five minutes of easy sets before your working weight.",
    "intent_routing": '{"intent":"coaching_qa","source_exercise":null,"target_exercise":null,"target_frequency":null,"search_query":null}',
    "substitution_resolution": '{"source_exercise":"barbell bench press","target_exercise":"incline dumbbell press"}',
    "abbreviation_expansion": '{"is_fitness_movement":true,"canonical_name":"Bench Press"}',
    "dynamic_split_plan": '{"split_name":"Custom","days":[]}',
    "checkpoint_review": "You trained consistently and your volume rose.",
}


@dataclass
class ExerciseStoreFixture:
    def get_exercise_library_entries(self, exercise_ids: list[str]) -> dict[str, dict[str, str]]:
        return {}


@dataclass
class EmptyProgramFixture:
    days: list[object] = field(default_factory=list)


def _captured_player_requests(monkeypatch, call_site: str):
    request_bodies = []

    def capture(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "DeepSeek-V4-Flash",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": MOCK_RESPONSES[call_site]},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(capture), timeout=5)
    model = model_downloader.SafeChatOpenAI(
        model="deepseek-ai/DeepSeek-V4-Flash",
        api_key="offline-test-key",
        base_url="https://unit.test/v1",
        max_tokens=CALL_SITE_BUDGETS["chat_reply"],
        streaming=False,
        stream_usage=False,
        http_client=client,
        max_retries=0,
    )
    monkeypatch.setattr(model_downloader, "_llm_instance", model)
    return request_bodies, client


def _invoke_player_call(call_site: str) -> None:
    model = model_downloader.get_llm()
    if call_site == "chat_reply":
        state = {
            "messages": [HumanMessage(content="How should I warm up before squats?")],
            "trainee_id": "test-player",
            "preferred_name": None,
            "coach_tone": "Direct and pragmatic",
            "custom_instructions": "",
            "telemetry_context": "",
            "weight_context": None,
        }
        assert assistant_graph.generation_node(state)["response_content"]
    elif call_site == "intent_routing":
        assert assistant_graph._classify_intent_with_llm("Can you explain my squat?").intent == "coaching_qa"
    elif call_site == "substitution_resolution":
        assert assistant_graph.resolve_coreference_with_llm(
            "Replace that with an incline press.",
            [HumanMessage(content="Which one?")],
            EmptyProgramFixture(),
            ExerciseStoreFixture(),
        ) == ("barbell bench press", "incline dumbbell press")
    elif call_site == "abbreviation_expansion":
        assert fitness_abbreviations.resolve_unknown_abbreviation_with_llm("XYZ") == "bench press"
    elif call_site == "dynamic_split_plan":
        assert program_rules.resolve_split(
            2, "Create an unusual two-session arrangement and limit axial loading."
        ).days
    else:
        prompt = checkpoint_review_ai.build_messages(
            checkpoint_review_ai.CANONICAL_FIXTURE["facts"],
            checkpoint_review_ai.CANONICAL_FIXTURE["rating"],
            "en",
        )
        reply = checkpoint_review_ai.bind_review_model(model).invoke(prompt)
        assert checkpoint_review_ai.extract_text(reply)


@pytest.mark.parametrize("call_site", tuple(CALL_SITE_BUDGETS))
def test_player_call_sends_one_output_budget_field(call_site, monkeypatch):
    request_bodies, client = _captured_player_requests(monkeypatch, call_site)
    try:
        _invoke_player_call(call_site)
        assert len(request_bodies) == 1
        budget_fields = {name for name in ("max_tokens", "max_completion_tokens") if name in request_bodies[0]}
        assert budget_fields == {"max_completion_tokens"}
        assert request_bodies[0]["max_completion_tokens"] == CALL_SITE_BUDGETS[call_site]
    finally:
        client.close()
