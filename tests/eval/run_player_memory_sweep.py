"""Run the hosted player-memory sweep and write JSON and Markdown results.

This is an explicit live command. It runs coaching_qa twice and arabic_replies
once for each of six history settings; it does not run during pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("MODEL_DEVICE", "cpu")
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE_DIR / ".env")

from agent.player_prompt import (  # noqa: E402
    ASSISTANT_HISTORY_REPLY_MAX_CHARS,
    STATIC_SYSTEM_CORE,
    TAIL_WINDOW_SIZE,
    override_player_prompt_history,
)
from tests.eval import run_evaluation as evaluation  # noqa: E402
from tests.eval.suites import arabic_replies  # noqa: E402
from utils.model_metering import scoped_usage_recorder  # noqa: E402
from utils.model_pricing import compute_cost  # noqa: E402

MEMORY_DATASET = BASE_DIR / "tests" / "eval" / "datasets" / "player_memory_sweep_cases.json"
COACHING_CASES = "coaching_qa_cases.json"
COACHING_REPETITIONS = 2
WINDOWS = (6, 10, 16)
TRUNCATION_LIMITS = (ASSISTANT_HISTORY_REPLY_MAX_CHARS, None)
SUITES = ("coaching_qa", "arabic_replies")
EXPECTED_RUNTIME = (
    "About 4–5 hours for all six settings at current provider latency; retries and extra routing calls add time. "
    "Each setting generates 87 player turns and requests 174 judge verdicts."
)


@dataclass
class TurnMeasurements:
    ttft_samples: list[float]
    turns: list[dict[str, Any]]


@dataclass
class SweepSession:
    assistant_graph: Any
    original_llm: Any
    player_model: str
    backend: str
    evaluation_context: Any
    ttft_samples: list[float]


class StreamingInvokeAdapter:
    """Measures first content time while preserving the graph's invoke interface."""

    def __init__(self, model: Any, ttft_samples: list[float]):
        self._model = model
        self._ttft_samples = ttft_samples

    def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
        is_player_reply = (
            isinstance(prompt, list) and bool(prompt) and STATIC_SYSTEM_CORE in str(getattr(prompt[0], "content", ""))
        )
        started = time.perf_counter()
        response = None
        measured = False
        for chunk in self._model.stream(prompt, *args, **kwargs):
            if is_player_reply and not measured and getattr(chunk, "content", None):
                self._ttft_samples.append(time.perf_counter() - started)
                measured = True
            response = chunk if response is None else response + chunk
        if response is None:
            raise RuntimeError("The hosted player model returned no streamed response chunks.")
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def load_memory_cases(path: Path = MEMORY_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"Expected a non-empty synthetic memory dataset at {path}.")
    for case in cases:
        _validate_memory_case(case)
    return cases


def _validate_memory_case(case: Any) -> None:
    if not isinstance(case, dict):
        raise ValueError("Memory sweep cases must be objects.")
    if case.get("kind") != "synthetic_multi_turn" or case.get("review_status") != "not_required_english_fixture":
        raise ValueError("Memory sweep fixtures must be marked as English synthetic multi-turn cases.")
    if not isinstance(case.get("query"), str) or not isinstance(case.get("history"), list):
        raise ValueError(f"Invalid multi-turn memory case: {case.get('id', '?')}")
    for message in case["history"]:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            raise ValueError(f"Invalid conversation message in memory case {case.get('id', '?')}.")
        if not isinstance(message.get("content"), str):
            raise ValueError(f"Invalid conversation text in memory case {case.get('id', '?')}.")


def summarize_usage(events: list[dict[str, Any]], turn_count: int) -> dict[str, Any]:
    """Summarizes player-call metering across generated turns."""
    if not events:
        return _empty_usage_summary()
    input_tokens, cached_tokens, output_tokens = _sum_usage_tokens(events)
    cost_usd = _sum_usage_cost(events)
    return {
        "metered_player_calls": len(events),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "cost_per_turn_usd": cost_usd / turn_count if turn_count else None,
        "cached_input_share": cached_tokens / input_tokens if input_tokens else None,
        "estimated_calls": sum(bool(event.get("estimated")) for event in events),
    }


def _empty_usage_summary() -> dict[str, Any]:
    return {
        "metered_player_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": None,
        "cost_per_turn_usd": None,
        "cached_input_share": None,
        "estimated_calls": 0,
    }


def _sum_usage_tokens(events: list[dict[str, Any]]) -> tuple[int, int, int]:
    input_tokens = sum(max(0, int(event.get("input_tokens", 0))) for event in events)
    cached_tokens = sum(max(0, int(event.get("cached_input_tokens", 0))) for event in events)
    output_tokens = sum(max(0, int(event.get("output_tokens", 0))) for event in events)
    return input_tokens, cached_tokens, output_tokens


def _sum_usage_cost(events: list[dict[str, Any]]) -> float:
    return sum(
        compute_cost(
            str(event.get("model", "")),
            int(event.get("input_tokens", 0)),
            int(event.get("output_tokens", 0)),
            cached_input_tokens=int(event.get("cached_input_tokens", 0)),
        )
        for event in events
    )


def _measure_turn(
    generate: Callable[[], Any],
    *,
    ttft_samples: list[float],
) -> tuple[Any, float, float | None, dict[str, Any]]:
    usage_events: list[dict[str, Any]] = []
    ttft_start = len(ttft_samples)
    started = time.perf_counter()
    with scoped_usage_recorder(lambda **row: usage_events.append(row)):
        generated = generate()
    elapsed = time.perf_counter() - started
    if isinstance(generated, tuple):
        reply = generated[0]
        generation_seconds = float(generated[1])
    else:
        reply = generated
        generation_seconds = elapsed
    turn_ttft = next(iter(ttft_samples[ttft_start:]), None)
    return reply, generation_seconds, turn_ttft, summarize_usage(usage_events, 1)


def _record_turn_metrics(target: list[dict[str, Any]], case_id: str, ttft: float | None, usage: dict[str, Any]) -> None:
    target.append(
        {
            "case_id": case_id,
            "ttft_seconds": ttft,
            "metered_player_calls": usage["metered_player_calls"],
            "input_tokens": usage["input_tokens"],
            "cached_input_tokens": usage["cached_input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_usd": usage["cost_usd"],
            "estimated_calls": usage["estimated_calls"],
        }
    )


def _failed_case(case: dict[str, Any], judges: list[dict[str, Any]], error: Exception) -> dict[str, Any]:
    message = evaluation._safe_error_message(error)
    return {
        "case_id": case.get("id", "?"),
        "query": case.get("query", ""),
        "generated_output": None,
        "generation_error": message,
        "judges": {
            judge["name"]: {
                "model": judge["model"],
                "passed": False,
                "judgment": None,
                "attempts": 0,
                "error": f"Player generation failed: {message}",
            }
            for judge in judges
        },
        "passed": False,
    }


def run_coaching_qa(context: Any, ttft_samples: list[float]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = evaluation.load_suite_cases(COACHING_CASES, 25) + load_memory_cases()
    results = []
    measurements = TurnMeasurements(ttft_samples, [])
    for repetition in range(1, COACHING_REPETITIONS + 1):
        for case in cases:
            results.append(_run_coaching_case(case, repetition, context, measurements))
    return _summarize_coaching(results), measurements.turns


def _run_coaching_case(
    case: dict[str, Any], repetition: int, context: Any, measurements: TurnMeasurements
) -> dict[str, Any]:
    try:
        reply, elapsed, ttft, usage = _measure_turn(
            lambda: evaluation._generate_reply(case), ttft_samples=measurements.ttft_samples
        )
    except Exception as error:
        _record_turn_metrics(measurements.turns, case.get("id", "?"), None, summarize_usage([], 1))
        return _tag_failed_coaching_case(case, repetition, context.judges, error)
    result = evaluation.evaluate_case(case, reply, context.judges, context.retry_policy)
    result.update({"generation_seconds": elapsed, "run": repetition})
    _record_turn_metrics(measurements.turns, case["id"], ttft, usage)
    return result


def _tag_failed_coaching_case(
    case: dict[str, Any], repetition: int, judges: list[dict[str, Any]], error: Exception
) -> dict[str, Any]:
    result = _failed_case(case, judges, error)
    result.update({"generation_seconds": None, "run": repetition})
    return result


def _summarize_coaching(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": results,
        "judge_scores": {name: _summarize_coaching_judge(name, results) for name in evaluation.JUDGE_NAMES},
        "both_judges_passed_cases": sum(result.get("passed") is True for result in results),
        "total_judged_cases": len(results),
    }


def _summarize_coaching_judge(judge_name: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    judgments = [result.get("judges", {}).get(judge_name, {}).get("judgment") for result in results]
    judgments = [judgment for judgment in judgments if isinstance(judgment, dict)]
    return {
        **_coaching_judge_case_scores(judge_name, results),
        "mean_dimension_scores": _mean_coaching_dimensions(judgments),
        "clinical_safety_fives": _clinical_safety_fives(judgments),
    }


def _coaching_judge_case_scores(judge_name: str, results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "passed_cases": sum(result.get("judges", {}).get(judge_name, {}).get("passed") is True for result in results),
        "total_cases": len(results),
    }


def _mean_coaching_dimensions(judgments: list[dict[str, Any]]) -> dict[str, float | None]:
    dimensions = (
        "groundedness",
        "biomechanical_validity",
        "clinical_safety",
        "structural_budget",
        "persona_adherence",
    )
    return {dimension: _mean_dimension_score(judgments, dimension) for dimension in dimensions}


def _clinical_safety_fives(judgments: list[dict[str, Any]]) -> int:
    return sum(
        isinstance(judgment.get("clinical_safety"), dict) and judgment["clinical_safety"].get("score") == 5
        for judgment in judgments
    )


def _mean_dimension_score(judgments: list[dict[str, Any]], dimension: str) -> float | None:
    scores = [judgment[dimension]["score"] for judgment in judgments if isinstance(judgment.get(dimension), dict)]
    return round(statistics.mean(scores), 3) if scores else None


def run_arabic_replies(context: Any, ttft_samples: list[float]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    original_generate = arabic_replies._generate_reply
    measurements = TurnMeasurements(ttft_samples, [])
    arabic_replies._generate_reply = _measured_arabic_generator(original_generate, measurements)
    try:
        entry = arabic_replies.SUITE.run(context)
    finally:
        arabic_replies._generate_reply = original_generate
    return _summarize_arabic_replies(entry), measurements.turns


def _measured_arabic_generator(original_generate: Callable[..., str], measurements: TurnMeasurements):
    def measured_generate(case: dict[str, Any], scenario: dict[str, Any], store: Any, scrub_output: Any) -> str:
        def generate() -> str:
            return original_generate(case, scenario, store, scrub_output)

        try:
            reply, _elapsed, ttft, usage = _measure_turn(generate, ttft_samples=measurements.ttft_samples)
        except Exception:
            _record_turn_metrics(measurements.turns, case["id"], None, summarize_usage([], 1))
            raise
        _record_turn_metrics(measurements.turns, case["id"], ttft, usage)
        return reply

    return measured_generate


def _summarize_arabic_replies(entry: dict[str, Any]) -> dict[str, Any]:
    cases = entry.get("cases", [])
    judge_scores = {name: _summarize_arabic_judge(name, cases) for name in evaluation.JUDGE_NAMES}
    return {
        "cases": cases,
        "mostly_arabic_cases": sum(case.get("mostly_arabic") is True for case in cases),
        "total_cases": len(cases),
        "judge_scores": judge_scores,
        "passed": entry.get("passed"),
    }


def _summarize_arabic_judge(judge_name: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [case for case in cases if isinstance(case.get("judges", {}).get(judge_name), dict)]
    labels = ("egyptian", "standard", "mixed", None)
    return {
        "expected_register_matches": sum(
            case["judges"][judge_name].get("label") == case.get("expected_register") for case in judged
        ),
        "total_cases": len(cases),
        "labels": {label: sum(case["judges"][judge_name].get("label") == label for case in cases) for label in labels},
    }


def _aggregate_turns(turns: list[dict[str, Any]]) -> dict[str, Any]:
    measured_costs = [turn["cost_usd"] for turn in turns if turn["cost_usd"] is not None]
    total_cost = sum(measured_costs) if measured_costs else None
    input_tokens, cached_tokens, output_tokens = _turn_token_totals(turns)
    ttft = [float(turn["ttft_seconds"]) for turn in turns if turn["ttft_seconds"] is not None]
    return {
        "turn_count": len(turns),
        "metered_player_calls": sum(turn["metered_player_calls"] for turn in turns),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "cost_usd": total_cost,
        "cost_per_turn_usd": total_cost / len(turns) if total_cost is not None and turns else None,
        "cached_input_share": cached_tokens / input_tokens if input_tokens else None,
        "estimated_calls": sum(turn["estimated_calls"] for turn in turns),
        "median_ttft_seconds": statistics.median(ttft) if ttft else None,
        "ttft_sample_count": len(ttft),
        "turns_with_metering": sum(turn["metered_player_calls"] > 0 for turn in turns),
        "turns": turns,
    }


def _turn_token_totals(turns: list[dict[str, Any]]) -> tuple[int, int, int]:
    return (
        sum(turn["input_tokens"] for turn in turns),
        sum(turn["cached_input_tokens"] for turn in turns),
        sum(turn["output_tokens"] for turn in turns),
    )


def _setting_label(window_size: int, reply_limit: int | None) -> str:
    truncation = "untruncated" if reply_limit is None else f"truncate-{reply_limit}"
    return f"window-{window_size}_{truncation}"


def _write_reports(json_path: Path, markdown_path: Path, report: dict[str, Any]) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = _markdown_header(report)
    lines.extend(_markdown_measurement_row(setting) for setting in report.get("settings", []))
    lines.extend(["", "## Run details", ""])
    for setting in report.get("settings", []):
        lines.extend(_markdown_setting_details(setting))
    return "\n".join(lines) + "\n"


def _markdown_header(report: dict[str, Any]) -> list[str]:
    return [
        "# Player conversation memory sweep",
        "",
        f"Generated: {report.get('generated_at', 'not recorded')}",
        f"Player model: {report.get('player_model', 'not recorded')}",
        f"Judges: {', '.join(judge.get('model', '?') for judge in report.get('judges', []))}",
        f"Expected runtime: {report.get('expected_runtime', EXPECTED_RUNTIME)}",
        "",
        "The TTFT value is the time from starting the player chat stream to its first content chunk. "
        "The report includes the delta from the 6-message, 500-character baseline. Provider TTFT "
        "has previously been measured around 9 seconds on DeepInfra (#405), so the 2.0-second "
        "criterion is reported for evidence even when the provider floor exceeds it.",
        "",
        "| Window | Earlier reply limit | Coaching QA judges (pass / total) | Arabic register judges (match / total) | Cost / turn (USD) | Cost change vs baseline | Median TTFT | TTFT delta vs baseline | Cached input share |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]


def _markdown_measurement_row(setting: dict[str, Any]) -> str:
    qa_scores = setting.get("coaching_qa", {}).get("judge_scores", {})
    ar_scores = setting.get("arabic_replies", {}).get("judge_scores", {})
    measurements = setting.get("measurements", {})
    limit = setting.get("assistant_reply_max_chars")
    values = (
        setting.get("window_size", "?"),
        "none" if limit is None else limit,
        _judge_score_pair(qa_scores, "passed_cases"),
        _judge_score_pair(ar_scores, "expected_register_matches"),
        _format_metric(measurements.get("cost_per_turn_usd"), "${:.6f}"),
        _format_metric(measurements.get("cost_change_vs_baseline_percent"), "{:+.1f}%"),
        _format_metric(measurements.get("median_ttft_seconds"), "{:.3f}s"),
        _format_metric(measurements.get("ttft_delta_vs_baseline_seconds"), "{:+.3f}s"),
        _format_metric(measurements.get("cached_input_share"), "{:.1%}"),
    )
    return "| " + " | ".join(map(str, values)) + " |"


def _judge_score_pair(scores: dict[str, Any], score_name: str) -> str:
    return " / ".join(
        f"{scores.get(name, {}).get(score_name, 0)}/{scores.get(name, {}).get('total_cases', 0)}"
        for name in evaluation.JUDGE_NAMES
    )


def _format_metric(value: Any, pattern: str) -> str:
    return "n/a" if value is None else pattern.format(value)


def _markdown_setting_details(setting: dict[str, Any]) -> list[str]:
    lines = [f"### {setting.get('label', 'setting')}", ""]
    if setting.get("error"):
        return [*lines, f"Setting error: `{setting['error']}`", ""]
    coaching = setting.get("coaching_qa", {})
    arabic = setting.get("arabic_replies", {})
    measurement = setting.get("measurements", {})
    return [
        *lines,
        f"- Coaching Q&A: {coaching.get('both_judges_passed_cases', 0)}/{coaching.get('total_judged_cases', 0)} cases passed by both judges.",
        f"- Arabic replies: {arabic.get('mostly_arabic_cases', 0)}/{arabic.get('total_cases', 0)} replies passed the mostly-Arabic check.",
        f"- Player usage: {measurement.get('metered_player_calls', 0)} model calls, {measurement.get('input_tokens', 0)} input tokens, {measurement.get('output_tokens', 0)} output tokens, {measurement.get('estimated_calls', 0)} estimated calls.",
        "",
    ]


def run_sweep(output_dir: Path) -> tuple[Path, Path]:
    session = _build_sweep_session()
    session.assistant_graph.llm = StreamingInvokeAdapter(session.original_llm, session.ttft_samples)
    try:
        report_paths = _report_paths(output_dir)
        report = _new_report(session)
        _write_reports(*report_paths, report)
        _run_configurations(report, report_paths, session)
        return report_paths
    finally:
        session.assistant_graph.llm = session.original_llm


def _build_sweep_session() -> SweepSession:
    if os.getenv("LLM_BACKEND", "local").strip().lower() != "openai":
        raise RuntimeError("Set LLM_BACKEND=openai to run the hosted DeepSeek memory sweep.")
    if not os.getenv("LLM_API_KEY", "").strip():
        raise RuntimeError("LLM_API_KEY is required for this live sweep.")
    from agent import assistant_graph
    from utils.model_downloader import model_identity

    player_model, backend = model_identity("production")
    if "deepseek" not in player_model.lower():
        raise RuntimeError(f"The memory sweep expects a DeepSeek player model; got {player_model!r}.")
    return SweepSession(
        assistant_graph,
        assistant_graph.llm,
        player_model,
        backend,
        evaluation._build_live_context(),
        [],
    )


def _report_paths(output_dir: Path) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_dir / f"player_memory_sweep_{timestamp}"
    return basename.with_suffix(".json"), basename.with_suffix(".md")


def _new_report(session: SweepSession) -> dict[str, Any]:
    return {
        "report_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "player_model": session.player_model,
        "backend": session.backend,
        "judges": session.evaluation_context.judge_metadata,
        "suites": list(SUITES),
        "synthetic_dataset": MEMORY_DATASET.name,
        "synthetic_cases": load_memory_cases(),
        "expected_runtime": EXPECTED_RUNTIME,
        "ttft_definition": "Seconds from starting a player chat stream to its first content chunk.",
        "settings": [],
    }


def _run_configurations(report: dict[str, Any], paths: tuple[Path, Path], session: SweepSession) -> None:
    baseline = None
    for window_size in WINDOWS:
        for reply_limit in TRUNCATION_LIMITS:
            setting, measurements = _run_setting(window_size, reply_limit, session)
            if setting["status"] == "complete":
                if window_size == TAIL_WINDOW_SIZE and reply_limit == ASSISTANT_HISTORY_REPLY_MAX_CHARS:
                    baseline = measurements
                setting["measurements"] = _comparison_metrics(measurements, baseline)
            report["settings"].append(setting)
            _write_reports(*paths, report)
            print(f"Reports updated: {paths[0]} and {paths[1]}", flush=True)


def _run_setting(
    window_size: int, reply_limit: int | None, session: SweepSession
) -> tuple[dict[str, Any], dict[str, Any]]:
    label = _setting_label(window_size, reply_limit)
    setting = {
        "label": label,
        "window_size": window_size,
        "assistant_reply_max_chars": reply_limit,
    }
    print(f"\nRunning {label}", flush=True)
    session.ttft_samples.clear()
    try:
        coaching, arabic, measurements = _run_setting_suites(window_size, reply_limit, session)
    except Exception as error:
        setting.update({"status": "failed", "error": evaluation._safe_error_message(error)})
        print(f"Setting failed: {setting['error']}", file=sys.stderr, flush=True)
        return setting, {}
    setting.update({"status": "complete", "coaching_qa": coaching, "arabic_replies": arabic})
    return setting, measurements


def _run_setting_suites(
    window_size: int, reply_limit: int | None, session: SweepSession
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with override_player_prompt_history(window_size=window_size, assistant_reply_max_chars=reply_limit):
        coaching, coaching_turns = run_coaching_qa(session.evaluation_context, session.ttft_samples)
        arabic, arabic_turns = run_arabic_replies(session.evaluation_context, session.ttft_samples)
    return coaching, arabic, _aggregate_turns(coaching_turns + arabic_turns)


def _comparison_metrics(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    base_cost = baseline.get("cost_per_turn_usd")
    current_cost = current.get("cost_per_turn_usd")
    base_ttft = baseline.get("median_ttft_seconds")
    current_ttft = current.get("median_ttft_seconds")
    comparison = {
        "cost_change_vs_baseline_percent": _percent_change(current_cost, base_cost),
        "ttft_delta_vs_baseline_seconds": _difference(current_ttft, base_ttft),
    }
    cost_change = comparison["cost_change_vs_baseline_percent"]
    comparison.update(current)
    comparison["cost_increase_within_20_percent"] = cost_change <= 20 if cost_change is not None else None
    comparison["median_ttft_within_2_seconds"] = current_ttft <= 2.0 if current_ttft is not None else None
    return comparison


def _percent_change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return (current / baseline - 1) * 100


def _difference(current: float | None, baseline: float | None) -> float | None:
    return current - baseline if current is not None and baseline is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the six-setting hosted player-memory sweep.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "reports" / "player-memory-sweep",
        help="Directory for the generated JSON and Markdown report pair.",
    )
    args = parser.parse_args(argv)
    try:
        json_path, markdown_path = run_sweep(args.output_dir)
    except Exception as error:
        print(f"Player-memory sweep could not start: {error}", file=sys.stderr)
        return 1
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    report = json.loads(json_path.read_text(encoding="utf-8"))
    return 0 if all(setting.get("status") == "complete" for setting in report["settings"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
