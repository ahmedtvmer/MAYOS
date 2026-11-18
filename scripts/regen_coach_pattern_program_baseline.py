"""Rebuild the commercial/home coach-pattern baseline from the full catalog."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.program_generator import generate_program_pipeline  # noqa: E402
from database.database_manager import DatabaseManager  # noqa: E402
from database.exercise_library.curation import DEFAULT_CURATION_CSV_PATH  # noqa: E402
from tests.catalog import close_catalog_store, seed_catalog  # noqa: E402
from tests.test_coach_pattern_rubric import (  # noqa: E402
    COACH_PATTERN_BACK_SLOT_ADDITIONS,
    _program_snapshot,
    _remove_expected_back_slot_additions,
)

DEFAULT_LIBRARY = ROOT / "data" / "processed_exercises.csv"
DEFAULT_SNAPSHOT = ROOT / "tests/fixtures/coach_pattern_program_baseline.json"
EXPERIENCE_AGES = {"advanced": 6.0, "beginner": 0.5, "intermediate": 3.0}
EQUIPMENT_OPTIONS = ("Commercial gym", "Home gym")
BASELINE_SCENARIO_ORDER = tuple(
    f"{experience}|{days}|{equipment}|false"
    for experience in EXPERIENCE_AGES
    for days in (3, 4, 5)
    for equipment in EQUIPMENT_OPTIONS
)


def _profile(experience: str, days: int, equipment: str) -> dict:
    return {
        "gender": "female", "proportions": "balanced", "age": 28,
        "weight_kg": 70.0, "height_cm": 165.0, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "progressive overload",
        "weekly_frequency": days, "training_age_years": EXPERIENCE_AGES[experience],
        "equipment_access": equipment, "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    }


def _snapshot_for_scenario(store, experience: str, days: int, equipment: str) -> dict:
    user = f"coach_rubric_{experience}_{days}_{equipment}"
    with store.open_ledger(user) as ledger:
        ledger.upsert_player_profile(_profile(experience, days, equipment))
        program, _ = generate_program_pipeline(ledger=ledger)
    snapshot = _program_snapshot(program)
    return _remove_expected_back_slot_additions(
        snapshot, COACH_PATTERN_BACK_SLOT_ADDITIONS[days]
    )


def _generate_baseline(store) -> dict:
    snapshots = {}
    for experience in EXPERIENCE_AGES:
        for days in (3, 4, 5):
            for equipment in EQUIPMENT_OPTIONS:
                scenario = f"{experience}|{days}|{equipment}|false"
                snapshots[scenario] = _snapshot_for_scenario(
                    store, experience, days, equipment
                )
    return snapshots


def _build_baseline(library_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="mayos-coach-pattern-baseline-") as temp_name:
        directory = Path(temp_name)
        store = DatabaseManager(
            catalog_path=directory / "catalog.db",
            ledgers_dir=directory / "ledgers",
            backups_dir=directory / "backups",
            deletions_path=directory / "deletions.db",
            curation_path=DEFAULT_CURATION_CSV_PATH,
        )
        try:
            seed_catalog(store, csv_path=library_path)
            return _generate_baseline(store)
        finally:
            close_catalog_store(store)


def _write_baseline(path: Path, baseline: dict) -> None:
    scenarios = [key for key in BASELINE_SCENARIO_ORDER if key in baseline]
    scenarios.extend(key for key in baseline if key not in scenarios)
    scenario_lines = ["{"]
    for index, scenario in enumerate(scenarios):
        compact_snapshot = json.dumps(
            baseline[scenario], ensure_ascii=False, separators=(",", ":")
        )
        comma = "," if index < len(scenarios) - 1 else ""
        scenario_lines.append(
            f"  {json.dumps(scenario, ensure_ascii=False)}: {compact_snapshot}{comma}"
        )
    scenario_lines.append("}")
    path.write_text("\n".join(scenario_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT)
    arguments = parser.parse_args()
    if not arguments.library.is_file():
        parser.error(f"full catalog CSV not found: {arguments.library}")
    baseline = _build_baseline(arguments.library)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    _write_baseline(arguments.output, baseline)
    print(f"Wrote {arguments.output}")


if __name__ == "__main__":
    main()
