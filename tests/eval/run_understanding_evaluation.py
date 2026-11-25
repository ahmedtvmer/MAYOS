"""Run the realistic-message understanding cases against the configured player model (#866).

Live model calls on a throwaway store: no real account or Training ledger is
touched. Exit code 0 means the report was written, whatever the score;
``compare_models.py`` and the reader judge the numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MODEL_DEVICE", "cpu")
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from tests.eval import understanding  # noqa: E402

#: The licensed library is not tracked: a checkout may lack it, the production image has it.
LIBRARY_CANDIDATES = (
    BASE_DIR / "data" / "processed_exercises.csv",
    Path("/app/data/processed_exercises.csv"),
)


def _fail(message: str) -> int:
    print(f"run_understanding_evaluation: {message}", file=sys.stderr)
    return 2


def _library_path(explicit: Path | None) -> Path | None:
    candidates = (explicit,) if explicit is not None else LIBRARY_CANDIDATES
    return next((path for path in candidates if path.is_file()), None)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the realistic-message understanding cases (live model).")
    parser.add_argument("--report", type=Path, required=True, help="Where to write the JSON report.")
    parser.add_argument("--exercises", type=Path, default=None, help="The real exercise library CSV.")
    parser.add_argument("--case", action="append", default=None, help="Run only this case id (repeatable).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if not os.getenv("LLM_API_KEY", "").strip():
        return _fail("LLM_API_KEY is not set; the cases need the live player model.")
    library = _library_path(args.exercises)
    if library is None:
        return _fail("the real exercise library (data/processed_exercises.csv) was not found.")
    dataset = understanding.load_dataset()
    cases = [case for case in dataset["cases"] if not args.case or case["id"] in args.case]
    if not cases:
        return _fail("no case matches --case.")
    from tests.eval.compare_models import _base_commit
    from utils.model_downloader import get_llm

    model = str(getattr(get_llm(), "model_name", "") or "")
    results = []
    with understanding.real_library_store(library) as store:
        programs = {name: understanding.build_program(store, spec) for name, spec in dataset["programs"].items()}
        for case in cases:
            result = understanding.run_case(store, case, programs[case["program"]])
            results.append(result)
            mark = "pass" if result.passed else ("error" if not result.scored else "FAIL")
            print(f"  [{mark}] {result.case_id}: {result.outcome} {'; '.join(result.problems)}", flush=True)
    report = understanding.build_report(dataset, results, model=model, real_model_run=True, commit=_base_commit())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"counted: {report['counted']}")
    print(f"all cases: {report['all_cases']}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
