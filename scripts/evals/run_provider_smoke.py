"""Provider-level smoke checks for one #184 player candidate."""

from __future__ import annotations

import argparse
import json

from _common import SPEND, body_manifest, chat, configure_cloud_env, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    configure_cloud_env(player_model=args.model)

    tool_spec = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Look up weather for a city.",
            "parameters": {
                "type": "object", "properties": {"city": {"type": "string"}},
                "required": ["city"], "additionalProperties": False,
            },
            "strict": True,
        },
    }]
    tool_result = chat(
        args.model,
        [{"role": "user", "content": "Call get_weather for Berlin. Do not answer with prose."}],
        max_tokens=80,
        tools=tool_spec,
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
        stream=False,
    )
    tool_calls = tool_result.get("tool_calls") or []
    tool_args = None
    tool_parse_error = None
    if tool_calls:
        try:
            tool_args = json.loads(tool_calls[0]["arguments"])
        except (KeyError, TypeError, ValueError) as exc:
            tool_parse_error = f"{type(exc).__name__}: {str(exc)[:180]}"
    tool_pass = bool(
        tool_result["ok"] and tool_calls and tool_calls[0].get("name") == "get_weather"
        and tool_args == {"city": "Berlin"}
    )

    schema_result = chat(
        args.model,
        [{"role": "user", "content": "Return a short JSON answer saying ready is true."}],
        max_tokens=80,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "ready_probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"ready": {"type": "boolean"}, "message": {"type": "string"}},
                    "required": ["ready", "message"],
                    "additionalProperties": False,
                },
            },
        },
        stream=False,
    )
    structured_value = None
    structured_parse_error = None
    try:
        structured_value = json.loads(schema_result["content"])
    except (TypeError, ValueError) as exc:
        structured_parse_error = f"{type(exc).__name__}: {str(exc)[:180]}"
    structured_pass = bool(
        schema_result["ok"] and isinstance(structured_value, dict)
        and structured_value.get("ready") is True and isinstance(structured_value.get("message"), str)
    )

    stream_result = chat(
        args.model,
        [{"role": "user", "content": "Reply with the single word ready."}],
        max_tokens=30,
        stream=True,
    )
    stream_usage = stream_result["usage"] or {}
    stream_pass = bool(
        stream_result["ok"] and stream_result["content"].strip()
        and not stream_result["usage_estimated"]
        and stream_usage.get("prompt_tokens", 0) > 0
        and stream_usage.get("completion_tokens", 0) > 0
    )

    reasoning_visible = bool(
        stream_result["reasoning"]
        or "<think>" in stream_result["content"].lower()
        or "</think>" in stream_result["content"].lower()
    )
    no_reasoning_pass = not reasoning_visible
    checks = {
        "tool_calls": {"passed": tool_pass, "tool_calls": tool_calls, "parsed_arguments": tool_args,
                        "parse_error": tool_parse_error, "request_extra_body": tool_result["request_extra_body"]},
        "strict_structured_output": {"passed": structured_pass, "parsed": structured_value,
                                      "parse_error": structured_parse_error,
                                      "status": schema_result["status"], "error": schema_result["error"],
                                      "request_extra_body": schema_result["request_extra_body"]},
        "streaming_with_usage": {"passed": stream_pass, "content_chars": len(stream_result["content"]),
                                 "usage": stream_usage, "usage_estimated": stream_result["usage_estimated"],
                                 "ttft_s": stream_result["ttft_s"], "total_s": stream_result["total_s"],
                                 "request_extra_body": stream_result["request_extra_body"]},
        "no_leaked_reasoning": {"passed": no_reasoning_pass,
                                "reasoning_chars": len(stream_result["reasoning"]),
                                "visible_think_marker": "<think>" in stream_result["content"].lower()
                                or "</think>" in stream_result["content"].lower()},
    }
    tag = args.model.split("/")[-1]
    overall = all(check["passed"] for check in checks.values())
    write_json(f"player_smoke_{tag}.json", {
        "model": args.model,
        "request_bodies": body_manifest(args.model),
        "status": "PASS" if overall else "FAIL",
        "checks": checks,
        "spend": SPEND.rows,
        "spend_usd": round(SPEND.total(), 6),
    })
    SPEND.save(f"smoke_{tag}")
    print(f"{args.model} smoke={'PASS' if overall else 'FAIL'} spend=${SPEND.total():.4f}")
    for name, row in checks.items():
        print(f"  {name}: {'PASS' if row['passed'] else 'FAIL'}")


if __name__ == "__main__":
    main()
