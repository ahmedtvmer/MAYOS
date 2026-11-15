"""Rebuild the empty-curation coach-pattern snapshot from the full catalog."""

import argparse
import csv
import gzip
import json
import sys
import tempfile
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.program_blueprints import SLOT_SPECS  # noqa: E402
from agent.program_generator import generate_program_pipeline  # noqa: E402
from core.muscle_volume import normalize_main_muscle  # noqa: E402
from database.database_manager import DatabaseManager  # noqa: E402
from database.exercise_library.curation import apply_exercise_curation  # noqa: E402
from tests.catalog import invented_exercise_curation, seed_catalog  # noqa: E402
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, HOME_GYM  # noqa: E402

DEFAULT_LIBRARY = ROOT / "data" / "processed_exercises.csv"
DEFAULT_SNAPSHOT = ROOT / "tests/fixtures/program_generation_empty_curation_coach_patterns.json.gz"
CURATION_COLUMNS = (
    "id", "source_name", "display_name", "aliases", "primary_action",
    "secondary_actions", "primary_muscle", "load_type", "hidden",
    "duplicate_of", "muscle_credits",
)
SCENARIOS = tuple(
    (equipment, frequency, "None")
    for equipment in (COMMERCIAL_GYM, HOME_GYM, BODYWEIGHT_ONLY)
    for frequency in (1, 3, 5)
) + ((COMMERCIAL_GYM, 3, "lower back tightness"),)


def _apply_empty_curation(store, directory: Path) -> None:
    path = directory / "empty-curation.csv"
    support = [
        record for record in invented_exercise_curation()
        if store.get_exercise_library_entry(record["id"]) is not None
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CURATION_COLUMNS)
        writer.writeheader()
        writer.writerows(support)
    with store.catalog_conn:
        apply_exercise_curation(store.catalog_conn.cursor(), path)


def _profile(equipment: str, frequency: int, limitations: str) -> dict:
    return {
        "gender": "male", "proportions": "balanced", "age": 28,
        "weight_kg": 80.0, "height_cm": 175.0, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "progressive overload",
        "weekly_frequency": frequency, "training_age_years": 3.0,
        "equipment_access": equipment, "injuries_or_limitations": limitations,
        "stress_and_sleep": "normal",
    }


def _snapshot_program(program) -> dict:
    snapshot = {
        key: value
        for key, value in program.model_dump(mode="json").items()
        if key not in {"weeks", "program_rationale"}
    }
    snapshot["days"] = [
        {key: value for key, value in day.items() if key != "week_order"}
        for day in snapshot["days"]
    ]
    return snapshot


def _generate_snapshot(store) -> dict:
    snapshots = {}
    for equipment, frequency, limitations in SCENARIOS:
        suffix = limitations.replace(" ", "_") if limitations != "None" else "none"
        ledger_id = f"signature_{equipment}_{frequency}_{suffix}"
        with store.open_ledger(ledger_id) as ledger:
            ledger.upsert_player_profile(_profile(equipment, frequency, limitations))
            program, _ = generate_program_pipeline(
                user_split_override="Full Body", ledger=ledger
            )
        scenario = f"{equipment}|{frequency}|{limitations}"
        snapshots[scenario] = _snapshot_program(program)
    return snapshots


def _muscle_rule(exercise: dict) -> str:
    spec = SLOT_SPECS.get(exercise.get("slot_key"))
    if spec is None:
        return "unknown slot"
    groups = sorted(
        normalize_main_muscle(muscle) or muscle.casefold()
        for muscle in spec.primary_muscles
    )
    return f"{exercise['slot_key']} => {', '.join(groups)}"


def _day_summary(day: dict | None) -> str:
    if day is None:
        return "(no day)"
    exercises = []
    for exercise in day["exercises"]:
        substitutes = ", ".join(
            f"{candidate['exercise_name']} [{candidate['exercise_id']}]"
            for candidate in exercise.get("suggested_substitutes", [])
        ) or "none"
        exercises.append(
            f"{exercise['exercise_name']} [{exercise['exercise_id']}; "
            f"{_muscle_rule(exercise)}; sets {exercise['target_sets']}; "
            f"suggested: {substitutes}]"
        )
    return f"cardio {day.get('cardio')}; " + ("; ".join(exercises) or "no exercises")


def _print_changes(previous: dict, current: dict) -> None:
    for scenario, new_program in current.items():
        old_program = previous.get(scenario)
        if old_program is None:
            print(f"{scenario}: new scenario")
            continue
        days = zip_longest(old_program["days"], new_program["days"])
        for old_day, new_day in days:
            if old_day == new_day:
                continue
            name = (new_day or old_day)["day_name"]
            print(f"{scenario} / {name}")
            print(f"  old: {_day_summary(old_day)}")
            print(f"  new: {_day_summary(new_day)}")


def _load_snapshot(path: Path) -> dict:
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _build_snapshot(library_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="mayos-program-signatures-") as temp_name:
        directory = Path(temp_name)
        store = DatabaseManager(
            catalog_path=directory / "catalog.db",
            ledgers_dir=directory / "ledgers",
            backups_dir=directory / "backups",
            deletions_path=directory / "deletions.db",
            curation_path=directory / "curation.csv",
        )
        try:
            seed_catalog(store, csv_path=library_path)
            _apply_empty_curation(store, directory)
            return _generate_snapshot(store)
        finally:
            store.catalog_conn.close()
            store.deletions_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT)
    arguments = parser.parse_args()
    if not arguments.library.is_file():
        parser.error(f"full catalog CSV not found: {arguments.library}")
    previous = _load_snapshot(arguments.output)
    current = _build_snapshot(arguments.library)
    _print_changes(previous, current)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
    with arguments.output.open("wb") as raw_stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_stream, mtime=0) as stream:
            stream.write(payload.encode("utf-8"))
    print(f"Wrote {arguments.output}")


if __name__ == "__main__":
    main()
