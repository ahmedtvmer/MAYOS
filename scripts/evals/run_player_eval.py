"""Player / Arabic turns for #139: graph path, raw production-prompt calls, structured output.

For one player model (``--model``), over the draft #138 set:

1. **Graph path.** Each Arabic message, its English equivalent and each Franco
   item goes through the production ``agent.assistant_graph.stream_assistant_turn``
   (hydrate -> router -> clinical guard -> handler or streamed generation) with
   the model swapped by env (``LLM_MODEL``) and a fresh, empty synthetic ledger.
   Records the routed intent, guard hit, reply, reply language and TTFT.
2. **Raw calls.** The production prompt (``build_prompt_payload``) for each
   Arabic/English pair sent straight to DeepInfra (streamed, thinking off), with
   and without a per-turn "Reply in Modern Standard Arabic." line, to get billed
   token counts, TTFT, tok/s, truncation and reply language independent of the
   router's canned replies.
3. **Structured output.** The router-fallback ``IntentClassification`` schema via
   LangChain ``with_structured_output`` using ``json_schema`` (production
   default), ``function_calling`` and ``json_mode``, on the program-change items
   in both languages. Parse success and intent accuracy.

Usage: MAYOS_DATA_DIR=<scratch> python scripts/evals/run_player_eval.py --model Qwen/Qwen3.5-9B
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from _common import (
    EVAL_DIR,
    SPEND,
    arabic_share,
    chat,
    configure_cloud_env,
    qwen_token_count,
    role_messages,
    write_json,
)

TELEMETRY = (
    "Split: Upper/Lower 4 days | Last session 2026-09-26 Lower A: Squat 100kg x 5 x 3 @RPE8, "
    "Romanian Deadlift 90kg x 8 x 3, Leg Press 180kg x 10 x 3 | Readiness 4/5"
)
MSA_DIRECTIVE = "\nReply in Modern Standard Arabic."
PROGRAM_IDS = {"exercise_substitution", "program_mutation", "catalog_search"}


def load_set() -> dict[str, Any]:
    return json.loads((EVAL_DIR / "arabic_eval_set.json").read_text(encoding="utf-8"))


def graph_turn(store: Any, text: str, ledger_id: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    from agent import assistant_graph as graph

    state: dict[str, Any] = {
        "messages": [HumanMessage(content=text)],
        "trainee_id": ledger_id,
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": TELEMETRY,
    }
    t0 = time.perf_counter()
    first = None
    pieces = []
    with store.open_ledger(ledger_id) as ledger:
        for piece in graph.stream_assistant_turn(state, ledger=ledger, store=store):
            if first is None:
                first = time.perf_counter() - t0
            pieces.append(piece)
    reply = "".join(pieces)
    return {
        "intent": state.get("intent"),
        "intent_metadata": {k: v for k, v in (state.get("intent_metadata") or {}).items()
                            if k in {"mode", "semantic_score", "source_exercise", "target_exercise",
                                     "target_frequency", "search_query"}},
        "reply": reply,
        "reply_arabic_share": round(arabic_share(reply), 3),
        "first_chunk_s": round(first or 0.0, 3),
        "total_s": round(time.perf_counter() - t0, 3),
    }


def guard_probe(text: str) -> dict[str, Any]:
    from agent.assistant_graph import RE_DIAGNOSIS, _acute_injury_hit
    from agent.clinical_guard import evaluate_clinical_semantic_guard

    hit, score = evaluate_clinical_semantic_guard(text, threshold=0.70)
    return {"tier0_regex": _acute_injury_hit(text), "diagnosis_regex": bool(RE_DIAGNOSIS.search(text)),
            "semantic_hit": hit, "semantic_score": round(score, 3)}


def raw_call(model: str, text: str, directive: bool) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    from agent.assistant_graph import build_prompt_payload

    payload = role_messages(build_prompt_payload({
        "messages": [HumanMessage(content=text)],
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": TELEMETRY,
    }))
    if directive:
        payload[0]["content"] += MSA_DIRECTIVE
    result = chat(model, payload, max_tokens=200)
    return {
        "status": result["status"], "error": result["error"], "reply": result["content"],
        "reasoning_chars": len(result["reasoning"]), "finish_reason": result["finish_reason"],
        "usage": result["usage"], "ttft_s": result["ttft_s"], "tokens_per_s": result["tokens_per_s"],
        "total_s": result["total_s"], "reply_arabic_share": round(arabic_share(result["content"]), 3),
    }


def structured_probe(text: str, method: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from agent.assistant_graph import ROUTER_PROMPT, IntentClassification
    from utils.model_downloader import get_llm

    system = ROUTER_PROMPT
    if method == "json_mode":
        system += "\n\nRespond only with a JSON object with keys: " + json.dumps(
            IntentClassification.model_json_schema()["properties"])
    t0 = time.perf_counter()
    try:
        structured = get_llm().with_structured_output(IntentClassification, method=method)
        parsed = structured.invoke([SystemMessage(content=system), HumanMessage(content=text)])
        return {"ok": parsed is not None, "parsed": parsed.model_dump() if parsed else None,
                "error": None, "total_s": round(time.perf_counter() - t0, 3)}
    except Exception as exc:
        return {"ok": False, "parsed": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "total_s": round(time.perf_counter() - t0, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    configure_cloud_env(player_model=args.model)

    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager
    from utils import model_metering

    # Count LangChain-path spend (graph generation + structured calls) via the metering seam.
    model_metering.set_recorder(
        lambda **kw: SPEND.add(kw["model"], int(kw["input_tokens"]), int(kw["output_tokens"])))

    tmp = Path(tempfile.mkdtemp(prefix="arabic-eval-"))
    catalog = tmp / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog)
    store = DatabaseManager(catalog_path=catalog, ledgers_dir=tmp / "users", backups_dir=tmp / "backups")

    data = load_set()
    rows = []
    for item in data["player_messages"]:
        row = {k: item[k] for k in ("id", "category", "code_switched", "text", "english",
                                    "expected_intent", "guard_should_trigger")}
        row["tokens_text_ar"] = qwen_token_count(item["text"])
        row["tokens_text_en"] = qwen_token_count(item["english"])
        row["guard_ar"] = guard_probe(item["text"])
        row["guard_en"] = guard_probe(item["english"])
        row["graph_ar"] = graph_turn(store, item["text"], f"eval_{item['id']}_ar")
        row["graph_en"] = graph_turn(store, item["english"], f"eval_{item['id']}_en")
        row["raw_ar"] = raw_call(args.model, item["text"], directive=False)
        row["raw_ar_directive"] = raw_call(args.model, item["text"], directive=True)
        row["raw_en"] = raw_call(args.model, item["english"], directive=False)
        rows.append(row)
        print(item["id"], row["graph_ar"]["intent"], "/", row["graph_en"]["intent"],
              f"ar={row['raw_ar']['reply_arabic_share']}", f"${SPEND.total():.4f}", flush=True)

    franco = []
    for item in data["franco_fail_closed"]:
        franco.append({**item, "guard": guard_probe(item["text"]),
                       "graph": graph_turn(store, item["text"], f"eval_{item['id']}")})
        print(item["id"], franco[-1]["graph"]["intent"], flush=True)

    structured = []
    for item in data["player_messages"]:
        if item["category"] != "program_change":
            continue
        for lang, text in (("ar", item["text"]), ("en", item["english"])):
            for method in ("json_schema", "function_calling", "json_mode"):
                probe = structured_probe(text, method)
                intent = (probe["parsed"] or {}).get("intent")
                structured.append({"id": item["id"], "lang": lang, "method": method,
                                   "expected_intent": item["expected_intent"], **probe,
                                   "intent_correct": intent == item["expected_intent"]})
    store.catalog_conn.close()

    tag = args.model.split("/")[-1]
    write_json(f"player_{tag}.json", {"model": args.model, "telemetry": TELEMETRY, "messages": rows,
                                      "franco": franco, "structured": structured, "spend": SPEND.rows})
    SPEND.save(f"player_{tag}")
    print(f"done {args.model} spend ${SPEND.total():.4f}")


if __name__ == "__main__":
    main()
