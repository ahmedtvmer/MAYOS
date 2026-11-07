"""Synthetic catalog seeds shared by pytest and standalone evaluation harnesses.

The manifest cites the tracked source of every retained id and name. Other ids
and names use the fixture namespace. No licensed dataset is a source for this
builder; media paths and instructions are invented.
"""

import atexit
import csv
import json
import re
import shutil
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
EXERCISE_CURATION = ROOT / "data" / "exercise_curation.csv"
IMPORT_FIXTURE = ROOT / "tests/eval/datasets/program_import/01_english_strength_week.json"
SUBSTITUTION_TEST = ROOT / "tests/test_substitution_resolution.py"


def _csv_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _equipment_from_tracked_name(name, load_type):
    lowered = name.casefold()
    if "smith" in lowered:
        return "smith machine"
    if "sled" in lowered:
        return "sled machine"
    if load_type or "machine" in lowered:
        return "leverage machine"
    for word in ("dumbbell", "ez barbell", "barbell", "cable", "band"):
        if word in lowered:
            return word
    if "wheel" in lowered:
        return "wheel roller"
    # This is an invented default for names without an equipment word, not a
    # claim about the absent library. Explicit invented overrides are in CSV.
    return "body weight"


def _muscle_fields(muscle):
    """Map tracked curation muscle labels into test-only seed categories."""
    if muscle in {"Chest", "Upper Chest"}:
        return "chest", "pectorals"
    if muscle in {"Front Delts", "Side Delts", "Rear Delts"}:
        return "shoulders", "delts"
    if muscle in {"Lats", "Upper Back", "Traps", "Lower Back"}:
        return "back", muscle.lower()
    if muscle in {"Biceps", "Triceps"}:
        return "upper arms", muscle.lower()
    if muscle == "Forearms":
        return "lower arms", "forearms"
    if muscle == "Calves":
        return "lower legs", "calves"
    if muscle in {"Abs", "Obliques"}:
        return "waist", muscle.lower()
    return "upper legs", muscle.lower()


def _fixture_rows():
    curated = {row["id"]: row for row in _csv_rows(EXERCISE_CURATION)}
    mock = {row["id"]: row for row in _csv_rows(FIXTURES / "mock_exercises.csv")}
    with IMPORT_FIXTURE.open(encoding="utf-8") as stream:
        imported = json.load(stream)["expected_rows"]
    test_names = {}
    for line in SUBSTITUTION_TEST.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r'(STIFF_LEG_DEADLIFT) = "([^"]+)"\s+# (.+)', line)
        if match:
            test_names[match[1]] = (match[2], match[3])

    for row in _csv_rows(FIXTURES / "catalog_exercises.csv"):
        exercise_id, source, key = row["id"], row["source"], row["source_key"]
        if source != "invented" and row["name"]:
            raise ValueError(f"Name for {exercise_id} must come from its cited source")
        if source in {"curation", "curation-display"}:
            original = curated[key]
            # Two kept ids occur as duplicate_of targets in tracked curation;
            # their names/muscles come from those explicitly related rows.
            if exercise_id != key and original["duplicate_of"] != exercise_id:
                raise ValueError(f"Curation does not supply id {exercise_id}")
            name_field = "display_name" if source == "curation-display" else "source_name"
            name, muscle = original[name_field], original["primary_muscle"]
            equipment = row["equipment"] or _equipment_from_tracked_name(name, original["load_type"])
        elif source == "mock":
            original = mock[key]
            if original["id"] != exercise_id:
                raise ValueError(f"Mock fixture does not supply id {exercise_id}")
            yield {field: original[field] for field in ("id", "name", "bodyPart", "target", "equipment")}
            continue
        elif source == "program-import":
            names = {entry["exercise_name"] for entry in imported if entry.get("expected_exercise_id") == key}
            if key != exercise_id or len(names) != 1:
                raise ValueError(f"Program import fixture does not supply a unique name for {exercise_id}")
            name, muscle, equipment = names.pop(), row["muscle"], row["equipment"]
        elif source == "substitution-test":
            source_id, name = test_names[key]
            if source_id != exercise_id:
                raise ValueError(f"Substitution test does not supply id {exercise_id}")
            muscle, equipment = row["muscle"], row["equipment"]
        elif source == "invented":
            if not exercise_id.startswith("fixture-") or not row["name"].startswith("Fixture "):
                raise ValueError("Invented rows must use fixture ids and names")
            name, muscle, equipment = row["name"], row["muscle"], row["equipment"]
        else:
            raise ValueError(f"Unsupported catalog fixture source {source!r}")
        body_part, target = _muscle_fields(muscle)
        yield {"id": exercise_id, "name": name, "bodyPart": body_part, "target": target, "equipment": equipment}


def invented_exercise_curation():
    """Explicit test-owned signatures make invented rows eligible for generation."""
    for row in _csv_rows(FIXTURES / "catalog_exercises.csv"):
        if row["source"] == "invented" and row["primary_action"]:
            yield {
                "id": row["id"], "source_name": row["name"],
                "primary_action": row["primary_action"],
                "primary_muscle": row["muscle"], "hidden": "false",
            }


def write_exercise_curation(directory: Path) -> Path:
    """Keep tracked curation and invented fixture signatures in one seed file."""
    path = directory / "synthetic-exercise-curation.csv"
    tracked = _csv_rows(EXERCISE_CURATION)
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(tracked[0]))
        writer.writeheader()
        writer.writerows(tracked)
        writer.writerows(invented_exercise_curation())
    return path


def write_exercise_seed(directory: Path) -> Path:
    path = directory / "synthetic-exercises.csv"
    fields = ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in _fixture_rows():
            exercise_id = row["id"]
            writer.writerow({
                **row,
                "image_path": f"images/synthetic-{exercise_id}.jpg",
                "gif_path": f"videos/synthetic-{exercise_id}.gif",
                "instructions": f"Synthetic test instruction for exercise {exercise_id}.",
            })
    return path


def seed_catalog(store, *, csv_path=None, **kwargs):
    """Use fixture defaults while retaining every explicitly supplied seed path."""
    defaults = {
        "curation_path": store.curation_path,
        "food_path": FIXTURES / "smoke_food_library.csv",
        "portion_path": FIXTURES / "smoke_food_portions.csv",
        "food_curation_path": ROOT / "data" / "food_curation.csv",
        "recipe_path": ROOT / "data" / "food_recipes.csv",
    }
    defaults.update({key: value for key, value in kwargs.items() if value is not None})
    if csv_path is None:
        csv_path = write_exercise_seed(store.catalog_path.parent)
    store.initialize_and_seed(csv_path=csv_path, **defaults)


@cache
def _catalog_template() -> Path:
    """Keep a closed seed database, not live SQLite handles, for this process."""
    from database.database_manager import DatabaseManager

    temporary = tempfile.TemporaryDirectory(prefix="mayos-test-catalog-")
    atexit.register(temporary.cleanup)
    directory = Path(temporary.name)
    store = DatabaseManager(
        catalog_path=directory / "catalog.db",
        ledgers_dir=directory / "users",
        backups_dir=directory / "backups",
        curation_path=write_exercise_curation(directory),
    )
    try:
        seed_catalog(store)
        checkpoint = store.catalog_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint[0] != 0:
            raise RuntimeError("Synthetic catalog checkpoint was blocked")
    finally:
        close_catalog_store(store)
    return store.catalog_path


def create_catalog_store(directory: Path, **kwargs):
    from database.database_manager import DatabaseManager

    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_catalog_template(), directory / "catalog.db")
    kwargs.setdefault("curation_path", write_exercise_curation(directory))
    store = DatabaseManager(
        catalog_path=directory / "catalog.db",
        ledgers_dir=directory / "users",
        backups_dir=directory / "backups",
        **kwargs,
    )
    return store


def close_catalog_store(store):
    """Close all store-owned connections, including the deletion journal."""
    ledger = getattr(store, "ledger", None)
    if ledger is not None:
        ledger.close()
    try:
        store.catalog_conn.close()
    finally:
        store.deletions_conn.close()
