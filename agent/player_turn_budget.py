"""Admission accounting for complete Player provider requests, including repeat rounds."""

import json
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.messages import SystemMessage

from agent.player_prompt import (
    CONTEXT_TOO_LONG_RESPONSE, HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING,
    PromptBudgetError, message_role, prompt_token_count,
)


# Escaped bytes upper-bound text tokens even if calibrated estimates undercount.
# Envelope slack covers provider role markers and schema framing as well.
PLAYER_TURN_INPUT_TOKEN_LIMIT = 96_000
PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT = 24_000


def provider_tool_schemas(tools) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {
        "name": tool.name, "description": tool.description,
        "parameters": tool.args_schema.model_json_schema(),
    }} for tool in tools]


def provider_request_attempts(model) -> int:
    candidate = getattr(model, "bound", model)
    retries = getattr(candidate, "max_retries", 0)
    return max(1, retries + 1) if type(retries) is int else 1


def _provider_message(message) -> dict[str, Any]:
    result = {"role": message_role(message), "content": message.content}
    if getattr(message, "tool_call_id", None):
        result["tool_call_id"] = message.tool_call_id
    if getattr(message, "name", None):
        result["name"] = message.name
    calls = getattr(message, "tool_calls", None)
    if calls:
        result["tool_calls"] = [{"id": call["id"], "type": "function", "function": {
            "name": call["name"], "arguments": json.dumps(call["args"]),
        }} for call in calls]
    result.update(getattr(message, "additional_kwargs", {}))
    return result


@dataclass
class PlayerTurnInputBudget:
    consumed: int = 0
    estimated_consumed: int = 0

    def fits_tool_round(self, messages, schemas, attempts=1) -> bool:
        """Check capacity without spending it, including a schema-free final answer."""
        projected = replace(self)
        try:
            projected.admit(messages, schemas, attempts)
            projected.prepare_request(messages, attempts=attempts)
        except PromptBudgetError:
            return False
        return True

    def prepare_request(self, messages, schemas=(), attempts=1):
        """Reserve the complete request, dropping only old conversation exchanges."""
        prepared = list(messages)
        while True:
            try:
                self.admit(prepared, schemas, attempts)
                return prepared
            except PromptBudgetError:
                # Keep the fixed prompt, current query and every current tool pair.
                current = max((index for index, message in enumerate(prepared)
                               if message_role(message) == "user"), default=0)
                oldest = next((index for index in range(current)
                               if message_role(prepared[index]) in {"user", "assistant"}), None)
                if oldest is None:
                    raise
                end = next((index for index in range(oldest + 1, current)
                            if message_role(prepared[index]) == "user"), current)
                del prepared[oldest:end]

    def admit(self, messages, schemas=(), attempts=1) -> None:
        request = {"messages": [_provider_message(message) for message in messages]}
        if schemas:
            request.update(tools=list(schemas), tool_choice="auto")
        rendered = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        framing = 128 * (1 + len(messages) + len(schemas))
        upper_bound = len(json.dumps(request, ensure_ascii=True, separators=(",", ":"))) + framing
        # Framing is ASCII byte slack; convert it at the same rate as serialized
        # JSON rather than charging each byte as a whole estimated token.
        estimate = prompt_token_count([SystemMessage(content=rendered + " " * framing)])
        if (estimate > HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
                or self.estimated_consumed + estimate * attempts > PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT
                or self.consumed + upper_bound * attempts > PLAYER_TURN_INPUT_TOKEN_LIMIT):
            raise PromptBudgetError(CONTEXT_TOO_LONG_RESPONSE)
        self.consumed += upper_bound * attempts
        self.estimated_consumed += estimate * attempts
