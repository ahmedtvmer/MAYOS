"""Runs the #138 player-message set and streamed latency sample for one model.

All mutable database state is copied to a temporary directory. Per-message
results are retained under scripts/evals/results as Arabic and latency JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from statistics import median
from typing import Any

from _common import (
    EVAL_DIR,
    REPO_ROOT,
    SPEND,
    arabic_share,
    body_manifest,
    chat,
    configure_cloud_env,
    install_role_request_bodies,
    role_messages,
    write_json,
)

TELEMETRY = (
    "Split: Upper/Lower 4 days | Last session 2026-09-26 Lower A: Squat 100kg x 5 x 3 @RPE8, "
    "Romanian Deadlift 90kg x 8 x 3, Leg Press 180kg x 10 x 3 | Readiness 4/5"
)


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
        "intent_metadata": {
            k: v for k, v in (state.get("intent_metadata") or {}).items()
            if k in {"mode", "semantic_score", "source_exercise", "target_exercise", "target_frequency", "search_query"}
        },
        "reply": reply,
        "reply_arabic_share": round(arabic_share(reply), 4),
        "reply_is_arabic": arabic_share(reply) >= 0.5,
        "first_chunk_s": round(first or 0.0, 4),
        "total_s": round(time.perf_counter() - t0, 4),
    }


def guard_probe(text: str) -> dict[str, Any]:
    from agent.assistant_graph import RE_DIAGNOSIS, _acute_injury_hit
    from agent.clinical_guard import evaluate_clinical_semantic_guard

    hit, score = evaluate_clinical_semantic_guard(text, threshold=0.70)
    return {
        "tier0_regex": _acute_injury_hit(text),
        "diagnosis_regex": bool(RE_DIAGNOSIS.search(text)),
        "semantic_hit": hit,
        "semantic_score": round(score, 4),
    }


def raw_call(model: str, text: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    from agent.assistant_graph import build_prompt_payload

    messages = build_prompt_payload({
        "messages": [HumanMessage(content=text)],
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": TELEMETRY,
    })
    result = chat(model, role_messages(messages), max_tokens=200, stream=True)
    return {
        "status": result["status"],
        "error": result["error"],
        "reply": result["content"],
        "reasoning_chars": len(result["reasoning"]),
        "finish_reason": result["finish_reason"],
        "usage": result["usage"],
        "usage_estimated": result["usage_estimated"],
        "ttft_s": result["ttft_s"],
        "tokens_per_s": result["tokens_per_s"],
        "total_s": result["total_s"],
        "request_extra_body": result["request_extra_body"],
        "reply_arabic_share": round(arabic_share(result["content"]), 4),
        "reply_is_arabic": arabic_share(result["content"]) >= 0.5,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    configure_cloud_env(player_model=args.model)

    from utils import model_metering

    model_metering.set_recorder(
        lambda **kw: SPEND.add(
            kw["model"], int(kw["input_tokens"]), int(kw["output_tokens"]),
            estimated=bool(kw.get("estimated", False)),
        )
    )

    data = load_set()
    rows = []
    franco = []
    temp = tempfile.TemporaryDirectory(prefix="mayos-player-arabic-")
    scratch = Path(temp.name)
    os.environ["MAYOS_DATA_DIR"] = str(scratch)
    shutil.copyfile(REPO_ROOT / "db" / "catalog.db", scratch / "catalog.db")
    from utils.logger import MyosLogger

    MyosLogger(log_file=str(scratch / "logs" / "myos.log"))
    install_role_request_bodies(args.model)
    from database.database_manager import DatabaseManager

    store = DatabaseManager(
        catalog_path=scratch / "catalog.db",
        ledgers_dir=scratch / "users",
        backups_dir=scratch / "backups",
    )
    try:
        for item in data["player_messages"]:
            row = {k: item[k] for k in (
                "id", "category", "code_switched", "text", "english", "expected_intent", "guard_should_trigger"
            )}
            row["guard_ar"] = guard_probe(item["text"])
            row["guard_en"] = guard_probe(item["english"])
            row["graph_ar"] = graph_turn(store, item["text"], f"eval_{item['id']}_ar")
            row["graph_en"] = graph_turn(store, item["english"], f"eval_{item['id']}_en")
            row["raw_ar"] = raw_call(args.model, item["text"])
            rows.append(row)
            print(
                item["id"], row["graph_ar"]["intent"], "/", row["graph_en"]["intent"],
                f"raw_ar={row['raw_ar']['reply_arabic_share']}", f"${SPEND.total():.4f}", flush=True,
            )

        for item in data["franco_fail_closed"]:
            franco.append({
                **item,
                "guard": guard_probe(item["text"]),
                "graph": graph_turn(store, item["text"], f"eval_{item['id']}_franco"),
            })
            print(item["id"], franco[-1]["graph"]["intent"], flush=True)
    finally:
        store.catalog_conn.close()
        temp.cleanup()

    routing_correct = sum(row["graph_ar"]["intent"] == row["expected_intent"] for row in rows)
    english_routing_correct = sum(row["graph_en"]["intent"] == row["expected_intent"] for row in rows)
    routing_failures = []
    clinical_failures = []
    for row in rows:
        for lang in ("ar", "en"):
            observed = row[f"graph_{lang}"]["intent"]
            expected = row["expected_intent"]
            if observed != expected:
                failure = {
                    "case_id": row["id"],
                    "language": lang,
                    "expected_intent": expected,
                    "actual_intent": observed,
                    "input_excerpt": (row["text"] if lang == "ar" else row["english"])[:180],
                    "reply_excerpt": row[f"graph_{lang}"]["reply"][:180],
                }
                routing_failures.append(failure)
                if expected == "clinical_intercept" or observed == "clinical_intercept":
                    clinical_failures.append({
                        **failure,
                        "failure_type": "missing_clinical_intercept" if expected == "clinical_intercept" else "false_clinical_intercept",
                    })
    franco_failures = [
        {
            "case_id": row["id"],
            "language": "franco",
            "failure_type": "missing_clinical_intercept",
            "expected_intent": row["expected_intent"],
            "actual_intent": row["graph"]["intent"],
            "input_excerpt": row["text"][:180],
            "reply_excerpt": row["graph"]["reply"][:180],
        }
        for row in franco if row["graph"]["intent"] != row["expected_intent"]
    ]
    clinical_failures.extend(franco_failures)

    raw_arabic_replies = sum(row["raw_ar"]["reply_is_arabic"] for row in rows)
    graph_arabic_replies = sum(row["graph_ar"]["reply_is_arabic"] for row in rows)
    raw_shares = [row["raw_ar"]["reply_arabic_share"] for row in rows]
    graph_shares = [row["graph_ar"]["reply_arabic_share"] for row in rows]
    tag = args.model.split("/")[-1]
    common = {
        "model": args.model,
        "request_bodies": body_manifest(args.model),
        "spend": SPEND.rows,
        "spend_usd": round(SPEND.total(), 6),
    }
    write_json(f"player_arabic_{tag}.json", {
        **common,
        "dataset": "#138 player_messages (32 Arabic messages) plus 5 Franco fail-closed probes",
        "metrics": {
            "arabic_case_count": len(rows),
            "intent_correct_ar": routing_correct,
            "intent_correct_en_equivalent": english_routing_correct,
            "routing_failures": len(routing_failures),
            "raw_arabic_replies_at_50pct": raw_arabic_replies,
            "raw_arabic_reply_rate": round(raw_arabic_replies / len(rows), 4) if rows else 0,
            "raw_mean_arabic_letter_share": round(sum(raw_shares) / len(raw_shares), 4) if raw_shares else 0,
            "graph_arabic_replies_at_50pct": graph_arabic_replies,
            "graph_arabic_reply_rate": round(graph_arabic_replies / len(rows), 4) if rows else 0,
            "graph_mean_arabic_letter_share": round(sum(graph_shares) / len(graph_shares), 4) if graph_shares else 0,
            "clinical_failures": len(clinical_failures),
            "franco_failures": len(franco_failures),
        },
        "clinical_failures": clinical_failures,
        "routing_failures": routing_failures,
        "messages": rows,
        "franco_fail_closed": franco,
    })

    raw_ttfb = [row["raw_ar"]["ttft_s"] for row in rows if row["raw_ar"]["ttft_s"] is not None]
    raw_total = [row["raw_ar"]["total_s"] for row in rows if row["raw_ar"]["total_s"] is not None]
    graph_ttfb = [row["graph_ar"]["first_chunk_s"] for row in rows]
    graph_total = [row["graph_ar"]["total_s"] for row in rows]
    write_json(f"player_latency_{tag}.json", {
        **common,
        "sample": "32 Arabic player turns; raw production prompt streamed for model TTFT and total",
        "primary_latency_path": "raw_ar direct streamed call using build_prompt_payload",
        "metrics": {
            "raw_streamed_calls": len(rows),
            "raw_ttft_median_s": round(median(raw_ttfb), 4) if raw_ttfb else None,
            "raw_ttft_p90_s": round(sorted(raw_ttfb)[min(len(raw_ttfb) - 1, math.ceil(0.9 * len(raw_ttfb)) - 1)], 4) if raw_ttfb else None,
            "raw_total_median_s": round(median(raw_total), 4) if raw_total else None,
            "graph_ar_ttft_median_s": round(median(graph_ttfb), 4) if graph_ttfb else None,
            "graph_ar_total_median_s": round(median(graph_total), 4) if graph_total else None,
        },
        "turns": [
            {"case_id": row["id"], "raw_ar": row["raw_ar"], "graph_ar": {
                "intent": row["graph_ar"]["intent"],
                "first_chunk_s": row["graph_ar"]["first_chunk_s"],
                "total_s": row["graph_ar"]["total_s"],
            }}
            for row in rows
        ],
    })
    SPEND.save(f"arabic_{tag}")
    print(f"done {args.model} spend ${SPEND.total():.4f}")


if __name__ == "__main__":
    main()
