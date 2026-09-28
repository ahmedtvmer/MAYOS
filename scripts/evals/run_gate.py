"""Runs the existing player eval gate (tests/eval/run_evaluation.py) on a hosted model.

Gemma-doc item 1: the standard (62/65) and generalization (15/15) gates, with
the Qwen3.5-27B function-calling judge held fixed, for each player candidate.
Metering is captured through the production ``utils.model_metering`` recorder
seam so the run's spend is counted.

Usage:
  MAYOS_DATA_DIR=<scratch dir with catalog.db> \
    python scripts/evals/run_gate.py --player Qwen/Qwen3.5-27B [--generalize]
"""

from __future__ import annotations

import argparse
import json
import sys

from _common import SPEND, configure_cloud_env, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--generalize", action="store_true")
    args = parser.parse_args()
    configure_cloud_env(player_model=args.player)
    import os

    os.environ["JUDGE_MODEL"] = "Qwen/Qwen3.5-27B"

    from utils import model_metering

    model_metering.set_recorder(
        lambda **kw: SPEND.add(kw["model"], int(kw["input_tokens"]), int(kw["output_tokens"]))
    )
    from tests.eval import run_evaluation

    sys.argv = ["run_evaluation.py"] + (["--generalize"] if args.generalize else [])
    exit_code = 0
    try:
        run_evaluation.main()
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    reports = sorted(run_evaluation.REPORTS_DIR.glob(("gen_" if args.generalize else "") + "eval_run_*.json"))
    report = json.loads(reports[-1].read_text(encoding="utf-8")) if reports else {}
    tag = f"gate_{'gen' if args.generalize else 'std'}_{args.player.split('/')[-1]}"
    write_json(f"{tag}.json", {"player": args.player, "judge": "Qwen/Qwen3.5-27B", "exit_code": exit_code,
                               "gate": report.get("gate"), "spend": SPEND.rows, "runs": report.get("runs")})
    SPEND.save(tag)
    print(tag, "exit", exit_code, "gate", json.dumps(report.get("gate"))[:400], f"spend ${SPEND.total():.4f}")


if __name__ == "__main__":
    main()
