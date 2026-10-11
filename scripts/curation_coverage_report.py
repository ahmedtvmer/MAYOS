"""Print Staple and curated signature coverage for every movement slot."""

import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.curation_coverage import (  # noqa: E402
    CurationCoverage,
    build_curation_coverage_report,
    read_curation_coverage_rows,
)
from database.database_manager import DEFAULT_CATALOG_PATH  # noqa: E402


def _read_exercise_rows(catalog_path: str | Path) -> list[dict[str, object]]:
    connection = sqlite3.connect(f"file:{Path(catalog_path)}?mode=ro", uri=True)
    try:
        return read_curation_coverage_rows(connection)
    finally:
        connection.close()


def _print_report(rows: tuple[CurationCoverage, ...]) -> None:
    print(
        f"{'Slot':<20} {'Equipment access':<18} {'Primary actions':<32} "
        f"{'Primary muscles':<20} {'Staples':>7} {'Signature matches':>18} "
        f"{'Staples ∪ signature':>21}"
    )
    for row in rows:
        print(
            f"{row.slot:<20} {row.equipment_access:<18} "
            f"{', '.join(row.primary_actions):<32} "
            f"{', '.join(row.primary_muscles):<20} {row.staple_count:>7} "
            f"{row.curated_signature_count:>18} {row.candidate_count:>21}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print Staple and curated signature candidates by movement slot and Equipment access."
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH))
    args = parser.parse_args(argv)
    _print_report(build_curation_coverage_report(_read_exercise_rows(args.catalog)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
