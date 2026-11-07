"""A tool round shares one ledger connection, so its reads must not overlap."""

import time
from threading import Lock
from types import SimpleNamespace

from agent.player_tools import run_player_tool_calls


def test_tool_calls_in_one_round_never_overlap():
    state = {"active": 0, "most": 0}
    lock = Lock()

    def invoke(_args):
        with lock:
            state["active"] += 1
            state["most"] = max(state["most"], state["active"])
        time.sleep(0.02)
        with lock:
            state["active"] -= 1
        return '{"status":"ok"}'

    names = ("first", "second", "third")
    tools = [SimpleNamespace(name=name, invoke=invoke) for name in names]
    definitions = {name: SimpleNamespace(status_en="", status_ar="", timeout_seconds=5) for name in names}

    messages, _telemetry = run_player_tool_calls(
        [{"name": name, "args": {}, "id": name} for name in names],
        tools=tools, definitions=definitions, language="en",
    )

    assert state["most"] == 1
    assert [message.content for message in messages] == ['{"status":"ok"}'] * 3
