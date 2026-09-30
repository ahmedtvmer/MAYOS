"""Runs one hosted player through the production 65-case or 15-case gate.

The harness redirects database, dataset scratch files, logs, and reports to
temporary/evaluation locations. Only the final JSON under scripts/evals/results
is retained. The judge remains Qwen3.5-27B with its production no-thinking
body for both player candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from _common import (
    EVAL_DIR,
    REPO_ROOT,
    RESULTS_DIR,
    SPEND,
    QWEN_JUDGE,
    body_manifest,
    configure_cloud_env,
    install_role_request_bodies,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--generalize", action="store_true")
    parser.add_argument("--replicate", type=int, default=1)
    args = parser.parse_args()
    configure_cloud_env(player_model=args.player)
    os.environ["JUDGE_MODEL"] = QWEN_JUDGE

    # The evaluators create isolated ledgers. Copy the read-only source catalog
    # so initialization and SQLite WAL activity cannot reach db/catalog.db.
    with tempfile.TemporaryDirectory(prefix="mayos-player-gate-") as scratch_name:
        scratch = Path(scratch_name)
        (scratch / "datasets").mkdir()
        data_root = scratch / "data"
        data_root.mkdir()
        for name in (
            "coaching_qa_cases.json",
            "debrief_cases.json",
            "onboarding_cases.json",
            "generalization_cases.json",
        ):
            shutil.copyfile(REPO_ROOT / "tests" / "eval" / "datasets" / name, scratch / "datasets" / name)
        shutil.copyfile(REPO_ROOT / "db" / "catalog.db", data_root / "catalog.db")
        os.environ["MAYOS_DATA_DIR"] = str(data_root)

        from utils import model_metering

        model_metering.set_recorder(
            lambda **kw: SPEND.add(
                kw["model"], int(kw["input_tokens"]), int(kw["output_tokens"]),
                estimated=bool(kw.get("estimated", False)),
            )
        )
        from utils.logger import MyosLogger

        MyosLogger(log_file=str(scratch / "logs" / "myos.log"))
        install_role_request_bodies(args.player)
        reports_path = REPO_ROOT / "tests" / "eval" / "reports"
        reports_path_existed = reports_path.exists()
        from tests.eval import run_evaluation

        original_reports = run_evaluation.REPORTS_DIR
        original_reports_existed = reports_path_existed
        scratch_reports = RESULTS_DIR / "_gate_reports"
        scratch_reports.mkdir(parents=True, exist_ok=True)
        run_evaluation.REPORTS_DIR = scratch_reports
        run_evaluation.datasets_dir = lambda: scratch / "datasets"

        sys.argv = ["run_evaluation.py"] + (["--generalize"] if args.generalize else [])
        exit_code = 0
        try:
            run_evaluation.main()
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
        finally:
            run_evaluation.REPORTS_DIR = original_reports
            if not original_reports_existed:
                original_reports.rmdir()

        reports = sorted(scratch_reports.glob(("gen_" if args.generalize else "") + "eval_run_*.json"))
        report = json.loads(reports[-1].read_text(encoding="utf-8")) if reports else {}
        for path in reports:
            path.unlink(missing_ok=True)
        scratch_reports.rmdir()

    gate = report.get("gate")
    tag = f"gate_{'gen' if args.generalize else 'std'}_{args.player.split('/')[-1]}"
    file_tag = tag if args.replicate == 1 else f"{tag}_r{args.replicate}"
    write_json(
        f"player_{file_tag}.json",
        {
            "player": args.player,
            "judge": QWEN_JUDGE,
            "request_bodies": body_manifest(args.player),
            "suite": "generalization" if args.generalize else "standard",
            "replicate": args.replicate,
            "threshold": 15 if args.generalize else 62,
            "exit_code": exit_code,
            "gate": gate,
            "spend": SPEND.rows,
            "spend_usd": round(SPEND.total(), 6),
            "runs": report.get("runs"),
        },
    )
    SPEND.save(file_tag)
    print(file_tag, "exit", exit_code, "gate", json.dumps(gate)[:400], f"spend ${SPEND.total():.4f}")


if __name__ == "__main__":
    main()
