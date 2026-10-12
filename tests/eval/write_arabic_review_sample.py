"""Write the ten-reply judge calibration sample from a live gate report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.eval.suites.arabic_replies import REVIEW_FILE, write_review_sample  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="A live report written by run_evaluation.py")
    args = parser.parse_args(argv)
    try:
        sample_path = write_review_sample(args.report)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Review sample written: {sample_path}")
    print(f"Review record: {REVIEW_FILE} (pending owner review)")
    print("After review, set review_status, reviewed_by, and reviewed_on in REVIEW.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
