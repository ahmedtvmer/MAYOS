"""Compare two player models over recorded gate and Arabic evaluation runs.

Subcommands:
- ``run``: sequentially invokes the hosted player gate and the real Arabic
  evaluation as child processes per model and run, then writes the comparison.
- ``report``: rebuilds the comparison from already-recorded report files
  without calling any model.
- ``save-baseline``: freezes a model's passing list for later comparisons.
- ``compare``: checks a model's recorded results against a saved baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MODEL_DEVICE", "cpu")
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from tests.eval.run_arabic_evaluation import _has_behavior_failure  # noqa: E402
from tests.eval.run_evaluation import JUDGE_NAMES, _judge_models, _score_case  # noqa: E402
from tests.eval.suites import arabic_replies  # noqa: E402

GATE_RUNNER = Path(__file__).resolve().parent / "run_evaluation.py"
ARABIC_RUNNER = Path(__file__).resolve().parent / "run_arabic_evaluation.py"
COMPARISON_JSON = "comparison.json"
COMPARISON_MD = "comparison.md"
ARABIC_FALLBACK_SUITE = "arabic_reviewed_41"


def model_slug(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model_id)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _sorted_run_files(model_dir: Path, pattern: str) -> list[Path]:
    def run_number(path: Path) -> int:
        match = re.search(r"(\d+)", path.name)
        return int(match.group(1)) if match else 0

    return sorted(model_dir.glob(pattern), key=run_number) if model_dir.is_dir() else []


def _base_commit() -> str:
    pinned = os.environ.get("MAYOS_BASE_COMMIT", "").strip()
    if pinned:
        return pinned
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(BASE_DIR), timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


# --- per-case extraction ---------------------------------------------------


def _judged_case_result(case: dict[str, Any], judge_models: dict[str, str], judge_names: list[str]) -> dict[str, Any]:
    """Coaching/generalization verdict via the gate's own per-case scorer."""
    case_score = _score_case(case, judge_models)
    judges = {}
    for name in judge_names:
        if name in case_score.unscored_judges or name in case_score.unreadable_judges:
            judges[name] = "unscored"
        elif name in case_score.judge_passes:
            judges[name] = "passed" if case_score.judge_passes[name] else "failed"
        else:
            # Readable judges inside an unscored case passed (the unscored condition).
            judges[name] = "passed"
    return {"passed": bool(case_score.passed), "unscored": bool(case_score.unscored_judges), "judges": judges}


def _arabic_reply_case_result(case: dict[str, Any], record: dict[str, Any], judge_models: dict[str, str]) -> dict[str, Any]:
    """Arabic-reply verdict via the suite's own per-case validation and judge checks."""
    _result, case_reasons = arabic_replies._validate_case(case, record, judge_models)
    record_judges = record.get("judges") if isinstance(record.get("judges"), dict) else {}
    judges = {}
    for name in JUDGE_NAMES:
        row_reasons: list[str] = []
        if case:
            arabic_replies._validate_judgment(case, name, record_judges.get(name, {}), judge_models, row_reasons)
            judges[name] = "unscored" if row_reasons else "passed"
        else:
            judges[name] = "unscored"
    return {
        "passed": record.get("mostly_arabic") is True and not case_reasons,
        "unscored": False,
        "judges": judges,
    }


def _suite_case_results(
    suite_name: str,
    cases: list[Any],
    judge_models: dict[str, str],
    judge_names: list[str],
    reply_cases: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    results = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id", "?"))
        if suite_name == "arabic_replies":
            results[case_id] = _arabic_reply_case_result(reply_cases.get(case_id, {}), case, judge_models)
        elif "judges" in case:
            results[case_id] = _judged_case_result(case, judge_models, judge_names)
        else:
            # routing and structured_output record each case's own verdict.
            results[case_id] = {"passed": case.get("passed") is True, "unscored": False}
    return results


def _collapse_suite_results(internal: dict[int, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """One verdict per case per gate invocation from the suite's internal runs.

    A scored failure in any internal run fails the invocation; otherwise any
    unscored internal run leaves the invocation unscored; otherwise it passed.
    """
    collapsed = {}
    for key in sorted({key for results in internal.values() for key in results}):
        run_results = [results[key] for results in internal.values() if key in results]
        if any(result.get("unscored") is not True and result.get("passed") is not True for result in run_results):
            failed, unscored = True, False
        elif any(result.get("unscored") is True for result in run_results):
            failed, unscored = False, True
        else:
            failed, unscored = False, False
        judges = {}
        for name in sorted({name for result in run_results for name in result.get("judges", {})}):
            verdicts = [result["judges"][name] for result in run_results if name in result.get("judges", {})]
            if "failed" in verdicts:
                judges[name] = "failed"
            elif "unscored" in verdicts:
                judges[name] = "unscored"
            else:
                judges[name] = "passed"
        result = {"passed": not failed and not unscored, "unscored": unscored}
        if judges:
            result["judges"] = judges
        collapsed[key] = result
    return collapsed


def _load_reply_cases() -> dict[str, dict[str, Any]]:
    try:
        return {case["id"]: case for case in arabic_replies._load_cases()}
    except ValueError as error:
        print(f"compare_models: arabic_replies dataset unavailable ({error}); its cases score as failures")
        return {}


def _gate_case_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-case verdicts from one player-gate report, reusing each suite's own scoring."""
    judge_models, _metadata_reasons = _judge_models(report)
    judge_names = list(judge_models) or list(JUDGE_NAMES)
    suite_results = report.get("suite_results")
    if not isinstance(suite_results, dict):
        return {}
    reply_cases = _load_reply_cases() if "arabic_replies" in suite_results else {}
    results = {}
    for suite_name, entry in suite_results.items():
        if not isinstance(entry, dict):
            continue
        internal: dict[int, dict[str, dict[str, Any]]] = {}
        if isinstance(entry.get("runs"), list):
            for index, run_summary in enumerate(entry["runs"], start=1):
                if isinstance(run_summary, dict) and isinstance(run_summary.get("cases"), list):
                    internal[index] = _suite_case_results(suite_name, run_summary["cases"], judge_models, judge_names, reply_cases)
        elif isinstance(entry.get("cases"), list):
            internal[1] = _suite_case_results(suite_name, entry["cases"], judge_models, judge_names, reply_cases)
        for key, result in _collapse_suite_results(internal).items():
            results[f"{suite_name}/{key}"] = result
    return results


def _arabic_eval_case_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reviewed-case verdicts from one Arabic evaluation report."""
    suite_name = report.get("suite") if isinstance(report.get("suite"), str) and report.get("suite") else ARABIC_FALLBACK_SUITE
    results = {}
    rows = report.get("runs")
    if not isinstance(rows, list):
        return results
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            continue
        passed = row.get("case_status") == "completed" and not _has_behavior_failure(row)
        results[f"{suite_name}/{row['case_id']}"] = {"passed": passed, "unscored": False}
    return results


def _report_case_results(report: dict[str, Any], eval_type: str) -> dict[str, dict[str, Any]]:
    if eval_type == "gate":
        return _gate_case_results(report)
    return _arabic_eval_case_results(report)


# --- comparison assembly ---------------------------------------------------


def _failed_run_result(meta: dict[str, Any]) -> dict[str, Any]:
    """A failed child (or missing case record) counts as not passed for that run."""
    result = {"passed": False, "unscored": False}
    if meta.get("judged") and meta.get("eval_type") == "gate":
        result["judges"] = {name: "failed" for name in JUDGE_NAMES}
    return result


def _recorded_slugs(out_dir: Path) -> list[str]:
    slugs = set()
    if out_dir.is_dir():
        for child in out_dir.iterdir():
            if child.is_dir() and (any(child.glob("gate_*.json")) or any(child.glob("arabic_*.json"))):
                slugs.add(child.name)
    return sorted(slugs)


def _detect_runs(out_dir: Path) -> int:
    highest = 0
    for path in out_dir.glob("*/*.json"):
        match = re.fullmatch(r"(?:gate|arabic)_(\d+)\.json", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def _extract_model_runs(
    out_dir: Path, slug: str, model_id: str, runs: int
) -> tuple[dict[int, dict[str, dict[str, dict[str, Any]]]], list[dict[str, Any]]]:
    """Run number -> eval type -> {case key: result}; invalid runs are listed, not parsed."""
    model_dir = out_dir / slug
    extracted: dict[int, dict[str, dict[str, dict[str, Any]]]] = {}
    invalid: list[dict[str, Any]] = []
    for run_number in range(1, runs + 1):
        run_results: dict[str, dict[str, dict[str, Any]]] = {}
        for eval_type, template in (("gate", "gate_{n}.json"), ("arabic", "arabic_{n}.json")):
            path = model_dir / template.format(n=run_number)
            report = _load_json(path)
            if report is None:
                invalid.append({
                    "model": model_id,
                    "eval": eval_type,
                    "run": run_number,
                    "reason": "report file is missing" if not path.is_file() else "report is not valid JSON",
                })
                continue
            reason = _run_validity(eval_type, report, model_id)
            if reason is not None:
                invalid.append({"model": model_id, "eval": eval_type, "run": run_number, "reason": reason})
                continue
            run_results[eval_type] = _report_case_results(report, eval_type)
        extracted[run_number] = run_results
    return extracted, invalid


def _aggregate_model_results(
    per_run: dict[int, dict[str, dict[str, dict[str, Any]]]],
    universe: dict[str, dict[str, Any]],
    runs: int,
) -> dict[str, dict[str, Any]]:
    """Majority over scored runs; unscored runs count as neither pass nor fail."""
    aggregated = {}
    for key in sorted(universe):
        meta = universe[key]
        pass_count, scored_runs, unscored_runs = 0, 0, []
        judge_results: dict[str, dict[str, str]] = {}
        for run_number in range(1, runs + 1):
            result = per_run.get(run_number, {}).get(meta["eval_type"], {}).get(key) or _failed_run_result(meta)
            if result.get("unscored") is True:
                unscored_runs.append(run_number)
            else:
                scored_runs += 1
                pass_count += int(result.get("passed") is True)
            for name, verdict in (result.get("judges") or {}).items():
                judge_results.setdefault(name, {})[str(run_number)] = verdict
        entry = {
            "pass_count": pass_count,
            "scored_runs": scored_runs,
            "passes": pass_count * 2 > scored_runs if scored_runs > 0 else None,
            "unscored_runs": unscored_runs,
        }
        if judge_results:
            entry["judges"] = judge_results
        aggregated[key] = entry
    return aggregated


def _gate_judges(out_dir: Path, slugs: list[str]) -> dict[str, str]:
    for slug in slugs:
        for path in _sorted_run_files(out_dir / slug, "gate_*.json"):
            report = _load_json(path)
            records = report.get("judges") if isinstance(report, dict) else None
            if not isinstance(records, list):
                continue
            models = {
                record.get("name"): record.get("model")
                for record in records
                if isinstance(record, dict)
                and isinstance(record.get("name"), str)
                and isinstance(record.get("model"), str)
            }
            if len(models) == len(JUDGE_NAMES):
                return models
    return {}


def _report_model_id(report: dict[str, Any], eval_type: str) -> str | None:
    """The player model id a recorded report was produced for, when it records one."""
    if eval_type == "gate":
        player_model = report.get("player_model")
    else:
        # The Arabic report records the configured player model at model.model.
        model = report.get("model")
        player_model = model.get("model") if isinstance(model, dict) else None
    return player_model if isinstance(player_model, str) and player_model.strip() else None


def _run_validity(eval_type: str, report: dict[str, Any], model_id: str | None) -> str | None:
    """Reason when the report is not a real model run of the expected player model."""
    if eval_type == "gate":
        if report.get("mode") != "live":
            return f"gate report mode is {report.get('mode')!r}, not live"
        if report.get("partial") is True:
            return "gate report is a partial suite run"
    elif report.get("real_model_run") is not True:
        return "arabic report is not a real configured-model run"
    recorded = _report_model_id(report, eval_type)
    if model_id is not None and recorded is not None and recorded != model_id:
        return f"report player model is {recorded!r}, expected {model_id!r}"
    return None


def _model_identity(out_dir: Path, slug: str, fallback: str) -> str:
    for eval_type, pattern in (("gate", "gate_*.json"), ("arabic", "arabic_*.json")):
        for path in _sorted_run_files(out_dir / slug, pattern):
            report = _load_json(path)
            if report is None:
                continue
            model_id = _report_model_id(report, eval_type)
            if model_id is not None:
                return model_id
    return fallback


def _stored_model_ids(out_dir: Path) -> dict[str, str] | None:
    """Slot order recorded by a previous `run` (models.json), when present."""
    stored = _load_json(out_dir / "models.json")
    if not isinstance(stored, dict):
        return None
    model_a = stored.get("model_a")
    if not isinstance(model_a, str) or not model_a.strip():
        return None
    ids = {"a": model_a}
    model_b = stored.get("model_b")
    if isinstance(model_b, str) and model_b.strip():
        ids["b"] = model_b
    return ids


def _slot_order(out_dir: Path, slugs: list[str], model_ids: dict[str, str] | None) -> dict[str, str]:
    if model_ids:
        return {model_slug(model_id): slot for slot, model_id in model_ids.items()}
    stored_ids = _stored_model_ids(out_dir)
    if stored_ids is not None:
        return {model_slug(model_id): slot for slot, model_id in stored_ids.items()}
    return {slug: slot for slot, slug in zip(("a", "b"), slugs)}


def _write_models_json(out_dir: Path, model_ids: dict[str, str], runs: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "models.json"
    path.write_text(
        json.dumps({"model_a": model_ids["a"], "model_b": model_ids.get("b"), "runs": runs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Model slots written: {path}")
    return path


def _build_comparison(out_dir: Path, runs: int, model_ids: dict[str, str] | None = None) -> dict[str, Any]:
    slugs = _recorded_slugs(out_dir)
    stored_ids = _stored_model_ids(out_dir)
    slot_by_slug = _slot_order(out_dir, slugs, model_ids)
    extracted: dict[str, dict[int, dict[str, dict[str, dict[str, Any]]]]] = {}
    invalid_runs: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    for slug in slugs:
        slot = slot_by_slug.get(slug)
        if slot not in {"a", "b"}:
            print(f"compare_models: ignoring recorded model directory without a comparison slot: {slug}")
            continue
        model_id = (model_ids or stored_ids or {}).get(slot) or _model_identity(out_dir, slug, slug)
        per_run, slug_invalid = _extract_model_runs(out_dir, slug, model_id, runs)
        extracted[slug] = per_run
        invalid_runs.extend(slug_invalid)
        identities[slug] = model_id

    universe: dict[str, dict[str, Any]] = {}
    for slug in extracted:
        for run_results in extracted[slug].values():
            for eval_type, keys in run_results.items():
                for key, result in keys.items():
                    meta = universe.setdefault(key, {"eval_type": eval_type, "judged": False})
                    meta["judged"] = meta["judged"] or "judges" in result

    models: dict[str, str | None] = {}
    cases: dict[str, dict[str, Any]] = {}
    for slot in ("a", "b"):
        slug = next(
            (
                candidate
                for candidate, candidate_slot in slot_by_slug.items()
                if candidate_slot == slot and candidate in extracted
            ),
            None,
        )
        if slug is None:
            models[slot] = None
            continue
        models[slot] = identities[slug]
        aggregated = _aggregate_model_results(extracted[slug], universe, runs)
        for key, entry in aggregated.items():
            cases.setdefault(key, {})[slot] = entry

    a_not_b: list[str] = []
    b_not_a: list[str] = []
    if models["b"] is not None:
        for key, entry in cases.items():
            a_passes = entry.get("a", {}).get("passes") is True
            b_passes = entry.get("b", {}).get("passes") is True
            if a_passes and not b_passes:
                a_not_b.append(key)
            elif b_passes and not a_passes:
                b_not_a.append(key)
    return {
        "kind": "model_comparison",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": models,
        "runs": runs,
        "judges": _gate_judges(out_dir, slugs),
        "commit": _base_commit(),
        "invalid_runs": invalid_runs,
        "cases": cases,
        "a_not_b": sorted(a_not_b),
        "b_not_a": sorted(b_not_a),
    }


def _case_cell(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return "n/a"
    if entry.get("passes") is None:
        return "unscored"
    verdict = "passes" if entry["passes"] is True else "fails"
    return f"{verdict} ({entry['pass_count']}/{entry['scored_runs']} scored)"


def _comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Model comparison",
        "",
        f"- Model A: {report['models']['a'] or 'n/a'}",
        f"- Model B: {report['models']['b'] or 'n/a'}",
        f"- Runs: {report['runs']}",
        f"- Judges: {'; '.join(f'{name}={model}' for name, model in report['judges'].items()) or 'unknown'}",
        f"- Commit: {report['commit']}",
        "",
        "| Case | A | B |",
        "| --- | --- | --- |",
    ]
    for key, entry in report["cases"].items():
        lines.append(f"| {key} | {_case_cell(entry.get('a'))} | {_case_cell(entry.get('b'))} |")
    lines.append("")
    lines.append(f"- A not B: {', '.join(report['a_not_b']) or 'none'}")
    lines.append(f"- B not A: {', '.join(report['b_not_a']) or 'none'}")
    if report.get("invalid_runs"):
        lines.append("")
        lines.append("## Invalid runs")
        lines.extend(
            f"- {entry['model']} {entry['eval']} run {entry['run']}: {entry['reason']}"
            for entry in report["invalid_runs"]
        )
    return "\n".join(lines) + "\n"


def _write_comparison(out_dir: Path, comparison: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / COMPARISON_JSON
    md_path = out_dir / COMPARISON_MD
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_comparison_markdown(comparison), encoding="utf-8")
    print(f"Comparison written: {json_path}")
    print(f"Comparison written: {md_path}")
    return json_path, md_path


def _load_or_build_comparison(out_dir: Path) -> dict[str, Any] | None:
    stored = _load_json(out_dir / COMPARISON_JSON)
    if stored is not None:
        return stored
    runs = _detect_runs(out_dir)
    if not _recorded_slugs(out_dir) or runs == 0:
        return None
    print(f"comparison.json not found in {out_dir}; rebuilding from recorded reports")
    return _build_comparison(out_dir, runs)


def _slot_for_model(comparison: dict[str, Any], model_id: str) -> str | None:
    models = comparison.get("models")
    if isinstance(models, dict):
        for slot in ("a", "b"):
            if models.get(slot) == model_id:
                return slot
    return None


# --- commands --------------------------------------------------------------


def _run_child(command: list[str], model_id: str, report_path: Path) -> bool:
    """One sequential child invocation with the player model pinned by LLM_MODEL."""
    env = {**os.environ, "LLM_MODEL": model_id}
    completed = subprocess.run(command, env=env, cwd=str(BASE_DIR))
    return completed.returncode == 0 and report_path.is_file()


def _run_children(out_dir: Path, model_ids: dict[str, str], runs: int) -> None:
    for slot in ("a", "b"):
        model_id = model_ids.get(slot)
        if model_id is None:
            continue
        slug = model_slug(model_id)
        for run_number in range(1, runs + 1):
            for eval_type, runner, prefix in (("gate", GATE_RUNNER, "gate"), ("arabic", ARABIC_RUNNER, "arabic")):
                report_path = out_dir / slug / f"{prefix}_{run_number}.json"
                command = [sys.executable, str(runner)]
                if eval_type == "arabic":
                    command += ["--mode", "real"]
                command += ["--report", str(report_path)]
                if not _run_child(command, model_id, report_path):
                    print(
                        f"compare_models: {slot} ({model_id}) run {run_number} {eval_type} child failed; "
                        "recorded as not passed"
                    )


def _run_command(args: argparse.Namespace) -> int:
    if args.runs < 1:
        return _fail("--runs must be at least 1")
    if args.model_b and args.model_b == args.model_a:
        return _fail("--model-b must differ from --model-a")
    out_dir = args.out
    model_ids = {"a": args.model_a}
    if args.model_b:
        model_ids["b"] = args.model_b
    _write_models_json(out_dir, model_ids, args.runs)
    _run_children(out_dir, model_ids, args.runs)
    comparison = _build_comparison(out_dir, args.runs, model_ids)
    _write_comparison(out_dir, comparison)
    return 0


def _report_command(args: argparse.Namespace) -> int:
    runs = _detect_runs(args.dir)
    if not _recorded_slugs(args.dir) or runs == 0:
        return _fail(f"no recorded gate or arabic reports found in {args.dir}")
    model_ids = {}
    if args.model_a:
        model_ids["a"] = args.model_a
    if args.model_b:
        model_ids["b"] = args.model_b
    comparison = _build_comparison(args.dir, runs, model_ids or None)
    _write_comparison(args.dir, comparison)
    return 0


def _save_baseline_command(args: argparse.Namespace) -> int:
    comparison = _load_or_build_comparison(args.dir)
    if comparison is None or not comparison.get("runs"):
        return _fail(f"no recorded gate or arabic reports found in {args.dir}")
    slot = _slot_for_model(comparison, args.model)
    if slot is None:
        return _fail(f"model {args.model} is not part of the comparison in {args.dir}")
    if args.baseline.exists() and not args.force:
        return _fail(f"baseline already exists (use --force to overwrite): {args.baseline}")
    model_invalid = [entry for entry in comparison.get("invalid_runs", []) if entry.get("model") == args.model]
    if model_invalid and not args.force:
        details = "; ".join(f"{entry['eval']} run {entry['run']}: {entry['reason']}" for entry in model_invalid)
        return _fail(f"model {args.model} has invalid runs; use --force to override: {details}")
    payload = {
        "model": args.model,
        "runs": comparison["runs"],
        "commit": comparison["commit"],
        "judges": comparison["judges"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "invalid_runs": model_invalid,
        "passing": sorted(
            key for key, entry in comparison["cases"].items() if entry.get(slot, {}).get("passes") is True
        ),
    }
    args.baseline.parent.mkdir(parents=True, exist_ok=True)
    args.baseline.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline written: {args.baseline}")
    return 0


def _compare_command(args: argparse.Namespace) -> int:
    comparison = _load_or_build_comparison(args.dir)
    if comparison is None or not comparison.get("runs"):
        return _fail(f"no recorded gate or arabic reports found in {args.dir}")
    slot = _slot_for_model(comparison, args.model)
    if slot is None:
        return _fail(f"model {args.model} is not part of the comparison in {args.dir}")
    baseline = _load_json(args.baseline)
    if baseline is None or not isinstance(baseline.get("passing"), list):
        return _fail(f"baseline is not a saved passing list: {args.baseline}")

    results = {key: entry.get(slot) for key, entry in comparison["cases"].items()}
    passed_now, gaps, unscored, missing = [], [], [], []
    for key in baseline["passing"]:
        entry = results.get(key)
        if entry is None:
            missing.append(key)
        elif entry.get("passes") is True:
            passed_now.append(key)
        elif entry.get("passes") is None:
            unscored.append(key)
        else:
            gaps.append(key)
    baseline_keys = set(baseline["passing"])
    bonus = sorted(
        key for key, entry in results.items() if entry is not None and entry.get("passes") is True and key not in baseline_keys
    )
    invalid_runs = [entry for entry in comparison.get("invalid_runs", []) if entry.get("model") == args.model]
    payload = {
        "model": args.model,
        "baseline": str(args.baseline),
        "baseline_cases_passed": sorted(passed_now),
        "baseline_gaps": sorted(gaps),
        "baseline_unscored": sorted(unscored),
        "baseline_missing": sorted(missing),
        "bonus_cases": bonus,
        "invalid_runs": invalid_runs,
        "passed": not gaps and not unscored and not missing and not invalid_runs,
    }
    json_path = args.dir / f"{model_slug(args.model)}_baseline_comparison.json"
    md_path = args.dir / f"{model_slug(args.model)}_baseline_comparison.md"
    md_lines = [
        "# Baseline comparison",
        "",
        f"- Model: {args.model}",
        f"- Baseline: {args.baseline}",
        f"- Result: {'PASS' if payload['passed'] else 'FAIL'}",
        "",
    ]
    invalid_lines = [
        f"{entry['model']} {entry['eval']} run {entry['run']}: {entry['reason']}" for entry in invalid_runs
    ]
    for title, keys in (
        ("Baseline cases passed", payload["baseline_cases_passed"]),
        ("Baseline gaps", payload["baseline_gaps"]),
        ("Baseline cases unscored", payload["baseline_unscored"]),
        ("Baseline cases missing", payload["baseline_missing"]),
        ("Bonus cases", payload["bonus_cases"]),
        ("Invalid runs", invalid_lines),
    ):
        md_lines.append(f"## {title}")
        md_lines.extend(f"- {key}" for key in keys)
        if not keys:
            md_lines.append("- none")
        md_lines.append("")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Baseline comparison written: {json_path}")
    print(f"Baseline comparison written: {md_path}")
    return 0 if payload["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare player models over recorded gate and Arabic evaluation runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run both evaluations per model and run, then write the comparison.")
    run_parser.add_argument("--model-a", required=True, help="Player model id for slot A.")
    run_parser.add_argument("--model-b", default=None, help="Optional player model id for slot B.")
    run_parser.add_argument("--runs", type=int, default=3, help="Gate/Arabic invocations per model (default 3).")
    run_parser.add_argument("--out", type=Path, required=True, help="Directory for recorded reports and the comparison.")

    report_parser = subparsers.add_parser("report", help="Rebuild the comparison from recorded reports; no model calls.")
    report_parser.add_argument("--dir", type=Path, required=True)
    report_parser.add_argument("--model-a", default=None, help="Optional slot A model id (default: sorted slug order).")
    report_parser.add_argument("--model-b", default=None, help="Optional slot B model id (default: sorted slug order).")

    save_parser = subparsers.add_parser("save-baseline", help="Freeze a model's passing list as the baseline.")
    save_parser.add_argument("--dir", type=Path, required=True)
    save_parser.add_argument("--model", required=True)
    save_parser.add_argument("--baseline", type=Path, required=True)
    save_parser.add_argument("--force", action="store_true", help="Overwrite an existing baseline file.")

    compare_parser = subparsers.add_parser("compare", help="Check a model's recorded results against a baseline.")
    compare_parser.add_argument("--dir", type=Path, required=True)
    compare_parser.add_argument("--model", required=True)
    compare_parser.add_argument("--baseline", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_command(args)
    if args.command == "report":
        return _report_command(args)
    if args.command == "save-baseline":
        return _save_baseline_command(args)
    return _compare_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
