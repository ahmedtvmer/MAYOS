"""Shared plumbing for the #139 Arabic & coach evaluation harness.

Research harness only: it imports and calls production code but never changes
it. The DeepInfra key is read from the repo ``.env`` (``LLM_API_KEY``) into the
process environment and is never printed, logged, or written to results.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
API_BASE = "https://api.deepinfra.com/v1/openai"

#: DeepInfra list prices, USD per 1M tokens (in, out), fetched 2026-09-28 from
#: https://api.deepinfra.com/models/list (standard tier).
PRICES: dict[str, tuple[float, float]] = {
    "Qwen/Qwen3.5-9B": (0.10, 0.15),
    "Qwen/Qwen3.5-27B": (0.26, 2.60),
    "Qwen/Qwen3-235B-A22B-Instruct-2507": (0.09, 0.55),
}

#: Qwen3.5 is a hybrid thinking model: thinking is ON by default and is turned
#: off per request with this chat-template kwarg (the production default in
#: ``utils.model_downloader._build_cloud_llm``). Qwen3-235B-A22B-Instruct-2507
#: is a non-thinking-only release; the kwarg is sent anyway and is harmless.
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

_KEY_FILE_CANDIDATES = (REPO_ROOT / ".env", Path("/mnt/work/MAYOS/.env"))


def load_api_key() -> None:
    """Puts ``LLM_API_KEY`` into ``os.environ`` from the repo .env (never echoed)."""
    if os.environ.get("LLM_API_KEY"):
        return
    for path in _KEY_FILE_CANDIDATES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("LLM_API_KEY="):
                os.environ["LLM_API_KEY"] = line.split("=", 1)[1].strip().strip("'\"")
                return
    raise SystemExit("LLM_API_KEY not found in .env")


def configure_cloud_env(player_model: str | None = None, coach_model: str | None = None) -> None:
    """Points the production registry at DeepInfra with the given model ids."""
    load_api_key()
    os.environ["LLM_BACKEND"] = "openai"
    os.environ["LLM_API_BASE"] = API_BASE
    os.environ.pop("TESTING", None)
    os.environ.pop("LLM_EXTRA_BODY", None)
    os.environ.pop("LLM_ENABLE_THINKING", None)
    if player_model:
        os.environ["LLM_MODEL"] = player_model
    if coach_model:
        os.environ["COACH_MODEL"] = coach_model


def openai_client():
    from openai import OpenAI

    load_api_key()
    return OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=API_BASE, timeout=180.0, max_retries=0)


class Spend:
    """Thread-safe token/USD ledger across a run, persisted to results/spend.json."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict[str, float]] = {}

    def add(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        usd = prompt_tokens * price_in / 1e6 + completion_tokens * price_out / 1e6
        with self._lock:
            row = self.rows.setdefault(model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0})
            row["calls"] += 1
            row["prompt_tokens"] += prompt_tokens
            row["completion_tokens"] += completion_tokens
            row["usd"] += usd
        return usd

    def total(self) -> float:
        return sum(row["usd"] for row in self.rows.values())

    def save(self, name: str) -> None:
        """One file per run (runs may execute in parallel processes)."""
        path = RESULTS_DIR / "spend" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"by_model": self.rows, "total_usd": round(self.total(), 5)}, indent=2),
                        encoding="utf-8")


SPEND = Spend()


def role_messages(messages: list[Any]) -> list[dict[str, str]]:
    """LangChain messages -> OpenAI chat dicts (same mapping ChatOpenAI uses)."""
    roles = {"system": "system", "human": "user", "ai": "assistant"}
    out = []
    for message in messages:
        if isinstance(message, dict):
            out.append({"role": message["role"], "content": str(message["content"])})
        else:
            out.append({"role": roles[message.type], "content": str(message.content)})
    return out


def merge_system_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Harness-only workaround for #148: fold every system message into one leading one.

    Content is kept verbatim and in order, joined by a blank line, so the model
    is told exactly what production tells it.
    """
    systems = [m["content"] for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    return ([{"role": "system", "content": "\n\n".join(systems)}] if systems else []) + rest


def chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float = 0.0,
    extra_body: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    stream: bool = True,
) -> dict[str, Any]:
    """One DeepInfra call with timing. Streams by default for TTFT and tok/s.

    Returns ``{ok, status, error, content, reasoning, finish_reason, usage,
    ttft_s, total_s, tokens_per_s, usd, tool_calls}``.
    """
    from openai import APIStatusError

    client = openai_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "extra_body": NO_THINKING if extra_body is None else extra_body,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools is not None:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
    t0 = time.perf_counter()
    result: dict[str, Any] = {"ok": False, "status": None, "error": None, "content": "", "reasoning": "",
                              "finish_reason": None, "usage": None, "ttft_s": None, "total_s": None,
                              "tokens_per_s": None, "usd": 0.0, "tool_calls": None}
    try:
        if stream and tools is None:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
            pieces: list[str] = []
            reasoning: list[str] = []
            for chunk in client.chat.completions.create(**kwargs):
                if chunk.usage is not None:
                    result["usage"] = {"prompt_tokens": chunk.usage.prompt_tokens,
                                       "completion_tokens": chunk.usage.completion_tokens}
                for choice in chunk.choices or []:
                    delta = choice.delta
                    text = getattr(delta, "content", None)
                    think = getattr(delta, "reasoning_content", None)
                    if (text or think) and result["ttft_s"] is None:
                        result["ttft_s"] = time.perf_counter() - t0
                    if text:
                        pieces.append(text)
                    if think:
                        reasoning.append(think)
                    if choice.finish_reason:
                        result["finish_reason"] = choice.finish_reason
            result["content"] = "".join(pieces)
            result["reasoning"] = "".join(reasoning)
        else:
            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            result["content"] = choice.message.content or ""
            result["reasoning"] = getattr(choice.message, "reasoning_content", None) or ""
            result["finish_reason"] = choice.finish_reason
            if choice.message.tool_calls:
                result["tool_calls"] = [
                    {"name": call.function.name, "arguments": call.function.arguments}
                    for call in choice.message.tool_calls
                ]
            if response.usage is not None:
                result["usage"] = {"prompt_tokens": response.usage.prompt_tokens,
                                   "completion_tokens": response.usage.completion_tokens}
        result["ok"] = True
        result["status"] = 200
    except APIStatusError as exc:
        result["status"] = exc.status_code
        result["error"] = str(exc.message)[:500]
    except Exception as exc:  # network / timeout
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    result["total_s"] = time.perf_counter() - t0
    usage = result["usage"]
    if usage:
        result["usd"] = SPEND.add(model, usage["prompt_tokens"], usage["completion_tokens"])
        gen_s = result["total_s"] - (result["ttft_s"] or 0.0)
        if result["ttft_s"] is not None and gen_s > 0 and usage["completion_tokens"] > 1:
            result["tokens_per_s"] = (usage["completion_tokens"] - 1) / gen_s
    return result


_TOKENIZER = None


def qwen_token_count(text: str) -> int:
    """Raw text tokens under the Qwen3.5 tokenizer (shared by 9B and 27B)."""
    global _TOKENIZER
    if _TOKENIZER is None:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        _TOKENIZER = Tokenizer.from_file(hf_hub_download("Qwen/Qwen3.5-9B", "tokenizer.json"))
    return len(_TOKENIZER.encode(text, add_special_tokens=False).ids)


def has_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" for ch in text)


def arabic_share(text: str) -> float:
    """Arabic letters as a share of all letters (0..1)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ") / len(letters)


def write_json(name: str, payload: Any) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
