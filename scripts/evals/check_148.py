"""#148 check: does DeepInfra reject the production coach message shape?

Sends the exact ``service.coach_ai.build_messages`` output for the canonical
fixture (two leading system messages) to each coach model, twice:

1. raw OpenAI-compatible call (non-streamed), and
2. through the production ``utils.model_downloader.get_coach_llm()`` +
   ``coach_ai._invoke_coach_model`` path (streamed LangChain ``SafeChatOpenAI``),

then the same messages with the system messages merged (harness workaround).

Usage: python scripts/evals/check_148.py
"""

from __future__ import annotations

import importlib

from _common import SPEND, chat, configure_cloud_env, merge_system_messages, role_messages, write_json

MODELS = ["Qwen/Qwen3.5-27B", "Qwen/Qwen3-235B-A22B-Instruct-2507", "Qwen/Qwen3.5-9B"]


def main() -> None:
    from service import coach_ai

    messages = coach_ai.build_messages(
        coach_ai.render_context(coach_ai.CANONICAL_FIXTURE), coach_ai.CANONICAL_QUESTION, coach_ai.CANONICAL_HISTORY
    )
    production = role_messages(messages)
    shape = [m["role"] for m in production]
    rows = []
    for model in MODELS:
        configure_cloud_env(coach_model=model)
        raw = chat(model, production, max_tokens=512, stream=False)
        merged = chat(model, merge_system_messages(production), max_tokens=512, stream=False)

        from utils import model_downloader

        importlib.reload(model_downloader)  # fresh coach singleton for this COACH_MODEL
        lc_status, lc_error, lc_answer = "ok", None, None
        try:
            lc_answer = coach_ai._invoke_coach_model(messages)
        except Exception as exc:  # the 400 surfaces as openai.BadRequestError
            lc_status = f"{type(exc).__name__}"
            lc_error = str(exc)[:400]
        rows.append({
            "model": model,
            "production_shape": shape,
            "raw_two_system": {k: raw[k] for k in ("ok", "status", "error", "finish_reason", "usage")},
            "raw_two_system_answer": raw["content"][:400],
            "langchain_production_path": {"status": lc_status, "error": lc_error, "answer": (lc_answer or "")[:400]},
            "raw_merged_one_system": {k: merged[k] for k in ("ok", "status", "error", "finish_reason", "usage")},
            "raw_merged_answer": merged["content"][:400],
        })
        print(model, "two-system raw:", raw["status"], (raw["error"] or "")[:120],
              "| langchain:", lc_status, "| merged:", merged["status"])
    write_json("check_148.json", rows)
    SPEND.save("check_148")
    print(f"spend ${SPEND.total():.4f}")


if __name__ == "__main__":
    main()
