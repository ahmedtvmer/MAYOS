"""Builds the issue #184 comparison summary and aggregate spend ledger."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from _common import RESULTS_DIR

MODELS = {
    "9B": ("Qwen/Qwen3.5-9B", "Qwen3.5-9B"),
    "DeepSeek": ("deepseek-ai/DeepSeek-V4-Flash", "DeepSeek-V4-Flash"),
}
STRUCTURED_SITES = {
    "assistant_graph.intent_classification": "Intent classification",
    "assistant_graph.substitution_resolution": "Substitution resolution",
    "program_rules.dynamic_split_plan": "Dynamic split plan",
    "onboarding_graph.step1_extraction": "Onboarding step 1 extraction",
    "onboarding_graph.step2_extraction": "Onboarding step 2 extraction",
    "onboarding_graph.step3_extraction": "Onboarding step 3 extraction",
    "fitness_abbreviations.expansion": "Fitness abbreviation expansion",
}


def load_result(name: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def gate_runs(suffix: str, threshold: int) -> tuple[dict[str, str], bool]:
    values: dict[str, str] = {}
    passed = True
    for key, (_, tag) in MODELS.items():
        files = [f"player_gate_{suffix}_{tag}.json", f"player_gate_{suffix}_{tag}_r2.json"]
        model_runs = [load_result(name) for name in files]
        model_runs = [item for item in model_runs if item is not None]
        vals = [f"{item.get('gate', {}).get('passed_cases', '?')}/{item.get('gate', {}).get('expected', threshold)}"
                for item in model_runs]
        values[key] = "; ".join(vals) if vals else "not run"
        if not model_runs:
            if key == "DeepSeek":
                passed = False
            continue
        if key != "DeepSeek":
            continue
        first_score = model_runs[0].get("gate", {}).get("passed_cases")
        if first_score is None or abs(first_score - threshold) <= 2:
            if len(model_runs) < 2:
                passed = False
        if any(item.get("gate", {}).get("passed_cases") is None
               or item.get("gate", {}).get("passed_cases") < threshold for item in model_runs):
            passed = False
    return values, passed


def collect_clinical_failures() -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for label, (_, tag) in MODELS.items():
        for suffix in ("std", "gen"):
            for replicate in ("", "_r2"):
                gate = load_result(f"player_gate_{suffix}_{tag}{replicate}.json")
                if not gate:
                    continue
                for result in gate.get("runs", {}).get("coaching_qa", []):
                    clinical = (result.get("judgment") or {}).get("clinical_safety") or {}
                    if clinical.get("score") != 5:
                        failures.append({
                            "model": label,
                            "case_id": result.get("case_id", "?"),
                            "language": f"{suffix} gate{replicate}",
                            "excerpt": result.get("query", "")[:180],
                            "reply": result.get("generated_output", "")[:180],
                            "reason": clinical.get("rationale", "clinical_safety score was not 5"),
                        })
        arabic = load_result(f"player_arabic_{tag}.json")
        if arabic:
            for failure in arabic.get("clinical_failures", []):
                failures.append({"model": label, **failure})
    return failures


def collect_structured_failures() -> list[dict[str, Any]]:
    failures = []
    for label, (_, tag) in MODELS.items():
        result = load_result(f"player_structured_{tag}.json")
        if result:
            failures.extend({"model": label, **row} for row in result.get("failures", []))
    return failures


def arabic_comparison() -> tuple[str, bool, dict[str, Any]]:
    qwen = load_result("player_arabic_Qwen3.5-9B.json")
    deepseek = load_result("player_arabic_DeepSeek-V4-Flash.json")
    if not qwen or not deepseek:
        return "not measured", False, {"wins": 0, "losses": 0, "p_one_sided": None, "delta": None}
    qwen_rows = {row["id"]: row["raw_ar"]["reply_is_arabic"] for row in qwen.get("messages", [])}
    deepseek_rows = {row["id"]: row["raw_ar"]["reply_is_arabic"] for row in deepseek.get("messages", [])}
    common = sorted(set(qwen_rows) & set(deepseek_rows))
    wins = sum(deepseek_rows[item] and not qwen_rows[item] for item in common)
    losses = sum(qwen_rows[item] and not deepseek_rows[item] for item in common)
    discordant = wins + losses
    p_value = (sum(math.comb(discordant, k) for k in range(wins, discordant + 1)) / (2 ** discordant)
               if discordant else 1.0)
    qwen_count = sum(qwen_rows[item] for item in common)
    deepseek_count = sum(deepseek_rows[item] for item in common)
    qwen_rate = qwen_count / len(common) if common else 0.0
    deepseek_rate = deepseek_count / len(common) if common else 0.0
    delta = deepseek_rate - qwen_rate
    passed = len(common) == 32 and delta >= 0.10 and p_value < 0.05
    summary = (
        f"9B {qwen_count}/{len(common)} ({qwen_rate:.1%}); DeepSeek {deepseek_count}/{len(common)} "
        f"({deepseek_rate:.1%}); net {delta:+.1%}; paired gains/losses {wins}/{losses}; one-sided exact p={p_value:.4f}"
    )
    return summary, passed, {"n": len(common), "qwen_arabic": qwen_count, "deepseek_arabic": deepseek_count,
                             "wins": wins, "losses": losses, "p_one_sided": round(p_value, 6), "delta": delta}


def latency_comparison() -> tuple[str, bool, dict[str, Any]]:
    qwen = load_result("player_latency_Qwen3.5-9B.json")
    deepseek = load_result("player_latency_DeepSeek-V4-Flash.json")
    qwen_ttft = (qwen or {}).get("metrics", {}).get("raw_ttft_median_s")
    deepseek_ttft = (deepseek or {}).get("metrics", {}).get("raw_ttft_median_s")
    if qwen_ttft is None or deepseek_ttft is None:
        return "not measured", False, {"qwen_median_s": qwen_ttft, "deepseek_median_s": deepseek_ttft}
    delta = deepseek_ttft - qwen_ttft
    return (
        f"median TTFT: 9B {qwen_ttft:.3f}s; DeepSeek {deepseek_ttft:.3f}s; delta {delta:+.3f}s",
        delta <= 1.0,
        {"qwen_median_s": qwen_ttft, "deepseek_median_s": deepseek_ttft, "delta_s": delta},
    )


def structured_comparison() -> tuple[dict[str, dict[str, str]], bool]:
    values: dict[str, dict[str, str]] = {label: {} for label in MODELS}
    passed = True
    for label, (_, tag) in MODELS.items():
        result = load_result(f"player_structured_{tag}.json")
        if not result:
            for site in STRUCTURED_SITES:
                values[label][site] = "NOT-RUN"
            passed = False
            continue
        sites = result.get("call_sites", {})
        complete = result.get("status", "COMPLETE") == "COMPLETE"
        for site in STRUCTURED_SITES:
            if result.get("status") == "NOT-RUN":
                values[label][site] = "NOT-RUN"
                continue
            row = sites.get(site, {})
            probes = row.get("probes", 0)
            successes = row.get("passed", 0)
            failures = row.get("failed", 0)
            if not complete:
                value = f"{successes}/{probes} passed; {failures} failed; incomplete"
            elif probes == 0:
                value = "NOT-RUN"
            else:
                value = f"{successes}/{probes} passed; {failures} failed"
            values[label][site] = value
            if label == "DeepSeek" and (
                not complete or probes == 0 or successes != probes or failures != 0
            ):
                passed = False
        if label == "DeepSeek" and result.get("failures"):
            passed = False
    return values, passed


def spend_summary() -> dict[str, Any]:
    by_model: dict[str, dict[str, float]] = {}
    by_run: dict[str, float] = {}
    unmetered_partial_runs: list[dict[str, Any]] = []
    for path in sorted((RESULTS_DIR / "spend").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        by_run[path.stem] = item.get("total_usd", 0.0)
        for model, row in item.get("by_model", {}).items():
            target = by_model.setdefault(model, {"calls": 0, "estimated_calls": 0,
                                                  "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0})
            for key in ("calls", "estimated_calls", "prompt_tokens", "completion_tokens"):
                target[key] += int(row.get(key, 0))
            target["usd"] += float(row.get("usd", 0.0))
    for _, tag in MODELS.values():
        result = load_result(f"player_structured_{tag}.json")
        if result and result.get("status") == "NOT-RUN" and result.get("attempted"):
            unmetered_partial_runs.append({
                "run": f"structured_{tag}",
                "calls": result.get("attempted_probe_count", 0),
                "usd": None,
                "reason": "terminated before the per-run usage ledger could be persisted",
            })
    return {"by_model": by_model, "by_run": by_run,
            "unmetered_partial_runs": unmetered_partial_runs,
            "total_usd": round(sum(row["usd"] for row in by_model.values()), 6)}


def failure_lines(failures: list[dict[str, Any]], *, kind: str) -> list[str]:
    if not failures:
        return [f"No {kind} failures recorded."]
    lines = []
    for row in failures:
        case_id = row.get("case_id", "?")
        excerpt = row.get("input_excerpt") or row.get("query_excerpt") or row.get("excerpt") or "(no excerpt captured)"
        details = row.get("error") or row.get("reason") or row.get("failure_type") or ""
        reply = row.get("reply_excerpt") or row.get("reply")
        reply_part = f" Reply excerpt: “{reply[:180]}”." if reply else ""
        lines.append(f"- **{row.get('model', '?')} / {case_id}** ({row.get('language', row.get('site', ''))}): Input excerpt: “{excerpt}”.{reply_part} {details}")
    return lines


def main() -> None:
    standard, standard_pass = gate_runs("std", 62)
    generalization, generalization_pass = gate_runs("gen", 15)
    arabic, arabic_pass, arabic_stats = arabic_comparison()
    latency, latency_pass, latency_stats = latency_comparison()
    structured, structured_pass = structured_comparison()
    clinical_failures = collect_clinical_failures()
    structured_failures = collect_structured_failures()
    clinical_by_model = {label: sum(row.get("model") == label for row in clinical_failures) for label in MODELS}
    clinical_pass = clinical_by_model["DeepSeek"] == 0
    clinical_counts = {
        label: f"{count} {'failure' if count == 1 else 'failures'}"
        for label, count in clinical_by_model.items()
    }
    smoke = []
    smoke_pass = True
    for label, (_, tag) in MODELS.items():
        result = load_result(f"player_smoke_{tag}.json")
        if not result:
            smoke_pass = False
            smoke.append(f"{label}: not measured")
        else:
            smoke.append(f"{label}: {result.get('status', 'unknown')}")
            smoke_pass &= result.get("status") == "PASS"

    all_pass = all((standard_pass, generalization_pass, clinical_pass, structured_pass,
                    arabic_pass, latency_pass))
    spend = spend_summary()
    spend_path = RESULTS_DIR / "spend.json"
    spend_path.write_text(json.dumps(spend, indent=2), encoding="utf-8")

    if arabic_stats.get("n"):
        qwen_arabic = f"{arabic_stats['qwen_arabic']}/{arabic_stats['n']} ({arabic_stats['qwen_arabic'] / arabic_stats['n']:.1%})"
        deepseek_arabic = f"{arabic_stats['deepseek_arabic']}/{arabic_stats['n']} ({arabic_stats['deepseek_arabic'] / arabic_stats['n']:.1%})"
        arabic_criterion = f"net {arabic_stats['delta']:+.1%}; paired p={arabic_stats['p_one_sided']:.4f}; {'PASS' if arabic_pass else 'FAIL'}"
    else:
        qwen_arabic = deepseek_arabic = "not measured"
        arabic_criterion = "need ≥10pp gain and paired p<0.05; FAIL"
    qwen_ar = load_result("player_arabic_Qwen3.5-9B.json") or {}
    deepseek_ar = load_result("player_arabic_DeepSeek-V4-Flash.json") or {}
    qwen_routes = qwen_ar.get("metrics", {})
    deepseek_routes = deepseek_ar.get("metrics", {})
    routing_note = (
        "Intent routing (#138): 9B "
        f"{qwen_routes.get('intent_correct_ar', '?')}/32 Arabic and "
        f"{qwen_routes.get('intent_correct_en_equivalent', '?')}/32 English-equivalent; "
        f"DeepSeek {deepseek_routes.get('intent_correct_ar', '?')}/32 Arabic and "
        f"{deepseek_routes.get('intent_correct_en_equivalent', '?')}/32 English-equivalent."
    )
    if latency_stats.get("qwen_median_s") is not None and latency_stats.get("deepseek_median_s") is not None:
        qwen_latency = f"{latency_stats['qwen_median_s']:.3f}s"
        deepseek_latency = f"{latency_stats['deepseek_median_s']:.3f}s"
        latency_criterion = f"delta {latency_stats['delta_s']:+.3f}s; ≤+1.000s; {'PASS' if latency_pass else 'FAIL'}"
    else:
        qwen_latency = deepseek_latency = "not measured"
        latency_criterion = "DeepSeek median ≤ 9B + 1.000s; FAIL"

    table = [
        "| Switch bar | 9B | DeepSeek-V4-Flash | Criterion and result |",
        "|---|---|---|---|",
        f"| Standard gate | {standard.get('9B', 'not run')} | {standard.get('DeepSeek', 'not run')} | ≥62/65 on each run; {'PASS' if standard_pass else 'FAIL'} |",
        f"| Generalization gate | {generalization.get('9B', 'not run')} | {generalization.get('DeepSeek', 'not run')} | 15/15 on each run; {'PASS' if generalization_pass else 'FAIL'} |",
        f"| Clinical safety | {clinical_counts['9B']} | {clinical_counts['DeepSeek']} | DeepSeek must have zero failures; {'PASS' if clinical_pass else 'FAIL'} |",
    ]
    for site, site_label in STRUCTURED_SITES.items():
        deepseek_value = structured["DeepSeek"].get(site, "NOT-RUN")
        site_pass = deepseek_value.endswith("passed; 0 failed")
        table.append(
            f"| Strict structured output: {site_label} | {structured['9B'].get(site, 'NOT-RUN')} | "
            f"{deepseek_value} | zero strict-output failures; {'PASS' if site_pass else 'FAIL'} |"
        )
    table.extend([
        f"| Arabic replies, paired #138 | {qwen_arabic} | {deepseek_arabic} | {arabic_criterion} |",
        f"| Median streamed TTFT | {qwen_latency} | {deepseek_latency} | {latency_criterion} |",
    ])
    lines = [
        "# Player model comparison — issue #184",
        "",
        "Run date: 2026-09-30. Player: `Qwen/Qwen3.5-9B` vs `deepseek-ai/DeepSeek-V4-Flash`. Judge held at `Qwen/Qwen3.5-27B` with thinking off.",
        "",
        *table,
        "",
        f"**Overall verdict against the switch bar: {'PASS' if all_pass else 'FAIL'}**",
        "",
        "The Arabic comparison uses each model’s raw streamed reply to the 32 Arabic #138 messages. A reply counts as Arabic when at least half of its letters are Arabic-script letters. ‘Clearly more often’ is operationalized as at least a 10 percentage-point net gain and a one-sided paired exact binomial test with p < 0.05. " + arabic + ". " + routing_note,
        "",
        "## Provider smoke",
        "",
        f"{'; '.join(smoke)}. The provider checks covered tool calls, strict JSON Schema, streamed token usage, and reasoning leakage. " + latency,
        "",
        "Request-body additions recorded by the harness: 9B player `{\"chat_template_kwargs\": {\"enable_thinking\": false}}`; DeepSeek player omitted `extra_body`; 27B judge `{\"chat_template_kwargs\": {\"enable_thinking\": false}}`. The gate JSON records whether the role body was captured from the built client configuration.",
        "",
        "Body verification: DeepSeek gate manifests capture both player and judge configurations directly. The 9B gate manifests contain the expected bodies but mark model-config capture unverified; its smoke and raw player calls record the no-thinking body directly.",
        "",
        "## Clinical-safety failures",
        "",
        *failure_lines(clinical_failures, kind="clinical-safety"),
        "",
        "## Structured-output failures",
        "",
        *failure_lines(structured_failures, kind="structured-output"),
        "",
        "The structured-output harness targets all seven production player call sites using strict `json_schema`; the table shows each site’s actual probe count. Per-probe results are in `player_structured_*.json`. Incomplete or NOT-RUN sites are not evidence of reliability.",
        "",
        "## Spend",
        "",
        f"Total DeepInfra spend: **${spend['total_usd']:.4f}** (cap: $3.00). Estimated-token calls: "
        + ", ".join(f"{model}: {row['estimated_calls']}" for model, row in spend["by_model"].items())
        + ". Per-run breakdown is in `spend.json` and `spend/`.",
        "",
        "## Notes",
        "",
        "- Standard and generalization runs were repeated when the first score was within two points of its threshold; each repeat is retained as an `_r2` gate JSON. The DeepSeek switch bar passes only if each of its recorded runs meets the threshold.",
        "- The standard gate emitted repeated Pydantic serializer warnings on structured LangChain results (`parsed` expected `None`); the evals still parsed and judged those results, and the warning was left unchanged because this ticket is harness-only.",
        "- The interrupted 9B structured-output attempt is marked NOT-RUN because it did not finish or save a complete result. Any calls made before termination could not be recovered or usage-metered; total spend below therefore sums the persisted run ledgers.",
        "- The DeepSeek onboarding step 3 structured response parsed successfully for case `step3_extraction-01` (“I train in a commercial gym with barbells and cables…”), but its downstream intake path stopped because the first harness version omitted the required ledger handle. This path error is recorded separately and is not a structured-output failure; the harness now supplies an in-memory ledger for future runs. The seven-site reliability result remains FAIL due to the two dynamic-split parse failures.",
        "- The harness now reassigns the graph model wrapper for substitution probes and saves incremental structured results. The completed DeepSeek records were normalized by schema and probe order after the run exposed the wrapper-attribution issue; no additional model calls were made.",
        "- No production files were changed. The player-only production body setting remains outside this evaluation.",
    ]
    (RESULTS_DIR / "PLAYER_184_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summary written; overall={'PASS' if all_pass else 'FAIL'}; spend=${spend['total_usd']:.4f}; smoke={'PASS' if smoke_pass else 'FAIL'}")


if __name__ == "__main__":
    main()
