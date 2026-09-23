"""Hosted-provider smoke check for the Phase 0 player-model gate.

Confirms, against the configured OpenAI-compatible endpoint, that:

1. the provider answers with the configured model ID;
2. the thinking/reasoning setting is applied (no ``reasoning_content`` leaks);
3. streaming yields chunks;
4. the model emits the required tool calls.

Usage::

    ./.venv/bin/python scripts/provider_smoke.py

Exit codes: ``0`` on a live pass, ``1`` on a failed live check, and ``2`` when
the check could not run because ``LLM_BACKEND`` is not ``openai`` or no
``LLM_API_KEY`` is configured. A ``not run`` status is deliberately nonzero so
it can never be mistaken for a passed release gate; the orchestrator runs the
live gate once the user supplies the key. The API key is never printed, logged,
or written to the report; both the text and JSON renderings are redacted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

load_dotenv()  # read the untracked .env (key is never printed)

from utils.model_downloader import (  # noqa: E402
    CLOUD_MODEL_REGISTRY,
    DEFAULT_CLOUD_API_BASE,
)

PRODUCTION = CLOUD_MODEL_REGISTRY["production"]
TOOL_PROMPT = "What is the weather in Berlin? Use the get_weather tool to find out."
STREAM_PROMPT = "Reply with the single word: ready"


class WeatherInput(BaseModel):
    city: str = Field(description="City to look up.")


@tool(args_schema=WeatherInput)
def get_weather(city: str) -> str:
    """Returns the current weather for a city."""
    return f"Sunny in {city}."


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class SmokeReport:
    status: str  # "pass" | "fail" | "not_run"
    reason: str = ""
    checks: list[Check] = field(default_factory=list)
    model: str = ""
    base_url: str = ""


# ---------------------------------------------------------------------------
# Configuration (read-only; the key is only ever used as a header value)
# ---------------------------------------------------------------------------


def backend() -> str:
    return os.getenv("LLM_BACKEND", "local").strip().lower()


def configured_model() -> str:
    return os.getenv("LLM_MODEL", "").strip() or PRODUCTION["default_model"]


def configured_api_base() -> str:
    return os.getenv("LLM_API_BASE", "").strip() or DEFAULT_CLOUD_API_BASE


def configured_api_key() -> str:
    return os.getenv("LLM_API_KEY", "").strip()


def _redact(text: Any, secret: str) -> str:
    rendered = str(text)
    return rendered.replace(secret, "***REDACTED***") if secret else rendered


def _thinking_disabled(extra_body: Any) -> bool:
    """True when the effective body disables thinking at either documented shape."""
    if not isinstance(extra_body, dict):
        return False
    if extra_body.get("enable_thinking") is False:
        return True
    nested = extra_body.get("chat_template_kwargs")
    return isinstance(nested, dict) and nested.get("enable_thinking") is False


def _reasoning_content(payload: dict[str, Any]) -> str:
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(message.get("reasoning_content") or "")


def _tool_names(calls: Any) -> list[str]:
    names = []
    for call in calls or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name:
            names.append(str(name))
    return names


def _default_requester(api_base: str, api_key: str) -> Callable[[dict[str, Any], float], dict[str, Any]]:
    """Raw chat-completions probe so the exact request body and reasoning fields are visible."""

    import httpx

    def request(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        response = httpx.post(
            f"{api_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    return request


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def run_smoke(
    chat_model: Any,
    *,
    expected_model: str,
    api_base: str,
    api_key: str = "",
    requester: Callable[[dict[str, Any], float], dict[str, Any]] | None = None,
    timeout: float = 30.0,
) -> SmokeReport:
    """Runs the four checks against ``chat_model`` (and an optional raw probe)."""
    checks: list[Check] = []
    actual_model = str(getattr(chat_model, "model_name", "") or "")
    checks.append(
        Check("model_id", actual_model == expected_model, f"configured={expected_model!r} built={actual_model!r}")
    )

    extra_body = getattr(chat_model, "extra_body", None)
    checks.append(
        Check("non_reasoning_config", _thinking_disabled(extra_body), f"extra_body={extra_body!r}")
    )

    try:
        chunk_count = 0
        streamed = []
        for chunk in chat_model.stream(STREAM_PROMPT):
            chunk_count += 1
            streamed.append(str(getattr(chunk, "content", "")))
        text = "".join(streamed).strip()
        checks.append(
            Check("streaming", chunk_count > 0 and bool(text), f"chunks={chunk_count} chars={len(text)}")
        )
    except Exception as exc:  # noqa: BLE001 - reported, never re-raised with a key
        checks.append(Check("streaming", False, f"stream raised {type(exc).__name__}: {_redact(exc, api_key)}"))

    try:
        bound = chat_model.bind_tools([get_weather])
        response = bound.invoke(TOOL_PROMPT)
        names = _tool_names(getattr(response, "tool_calls", None))
        checks.append(Check("tool_calls", "get_weather" in names, f"tool_calls={names}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("tool_calls", False, f"invoke raised {type(exc).__name__}: {_redact(exc, api_key)}"))

    if requester is not None:
        probe_payload: dict[str, Any] = {
            "model": expected_model,
            "messages": [{"role": "user", "content": STREAM_PROMPT}],
            "max_tokens": PRODUCTION["default_max_tokens"],
            "temperature": 0.0,
        }
        if isinstance(extra_body, dict):
            probe_payload.update(extra_body)
        try:
            payload = requester(probe_payload, timeout)
            echoed = str(payload.get("model", "") or "")
            checks.append(
                Check(
                    "provider_model_echo",
                    echoed == expected_model or echoed.startswith(expected_model),
                    f"provider echoed {echoed!r}",
                )
            )
            reasoning = _reasoning_content(payload)
            checks.append(
                Check(
                    "non_reasoning_response",
                    reasoning == "",
                    "no reasoning_content" if reasoning == "" else f"reasoning_content={len(reasoning)} chars",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                Check("provider_probe", False, f"raw request failed {type(exc).__name__}: {_redact(exc, api_key)}")
            )

    status = "pass" if all(check.passed for check in checks) else "fail"
    return SmokeReport(status=status, checks=checks, model=actual_model, base_url=api_base)


def render_report(report: SmokeReport, api_key: str = "") -> str:
    lines = [f"provider smoke: {report.status}"]
    if report.model:
        lines.append(f"  model: {report.model}")
    if report.base_url:
        lines.append(f"  base_url: {report.base_url}")
    if report.reason:
        lines.append(f"  reason: {_redact(report.reason, api_key)}")
    for check in report.checks:
        marker = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{marker}] {check.name}: {_redact(check.detail, api_key)}")
    return _redact("\n".join(lines), api_key)


def render_json(report: SmokeReport, api_key: str = "") -> str:
    """JSON rendering with the same redaction as the text report."""
    payload = {
        "status": report.status,
        "reason": _redact(report.reason, api_key),
        "checks": [
            {"name": check.name, "passed": check.passed, "detail": _redact(check.detail, api_key)}
            for check in report.checks
        ],
    }
    return _redact(json.dumps(payload), api_key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live hosted player-model smoke check (Phase 0 gate).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    api_key = configured_api_key()
    model = configured_model()
    api_base = configured_api_base()

    if backend() != "openai":
        report = SmokeReport(status="not_run", reason=f"LLM_BACKEND={backend()!r}, expected 'openai'", model=model, base_url=api_base)
    elif not api_key:
        report = SmokeReport(status="not_run", reason="LLM_API_KEY not set", model=model, base_url=api_base)
    else:
        try:
            from utils.model_downloader import get_llm

            chat_model = get_llm()
        except Exception as exc:  # noqa: BLE001
            report = SmokeReport(status="fail", reason=f"model build failed: {_redact(exc, api_key)}", model=model, base_url=api_base)
        else:
            report = run_smoke(
                chat_model,
                expected_model=model,
                api_base=api_base,
                api_key=api_key,
                requester=_default_requester(api_base, api_key),
                timeout=args.timeout,
            )

    print(render_json(report, api_key) if args.json else render_report(report, api_key))

    # A "not run" smoke is NOT a passed release gate: exit 2 so CI cannot treat
    # a missing key or local backend as green. 0 = live pass, 1 = live failure.
    if report.status == "pass":
        return 0
    if report.status == "fail":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
