import pytest

from agent.program_blueprints import SLOT_SPECS
from agent.program_weeks import ProgramPosition
from service.program_substitution import (
    ProgramSubstitution,
    SubstitutionErrorCode,
    substitute_program_exercise,
)


class FakeCatalog:
    def __init__(self, entries):
        self.entries = entries

    def get_exercise_library_entry(self, exercise_id):
        return self.entries.get(exercise_id)

    def is_exercise_library_exercise_visible(self, exercise_id):
        exercise = self.entries.get(exercise_id)
        return exercise is not None and not exercise.get("hidden", False)


class FakeLedger:
    def __init__(self):
        self.saved = []

    def get_player_profile(self):
        return {"rep_preference": "balanced"}

    def get_program_position(self, _program):
        return ProgramPosition(current_week=1, week_count=1, next_day_order=1)

    def save_training_program(
        self,
        program_data,
        published_by_coach_account_id=None,
        *,
        starting_position=None,
    ):
        self.saved.append((program_data, published_by_coach_account_id))


def _program_for_slots(slot_keys, exercise_id):
    exercises = []
    for slot_key in slot_keys:
        spec = SLOT_SPECS[slot_key]
        exercises.append(
            {
                "exercise_id": exercise_id,
                "exercise_name": "Library exercise",
                "slot_key": slot_key,
                "warmup_sets": spec.warmup_sets,
                "target_sets": 2,
                "target_reps_min": spec.reps[0],
                "target_reps_max": spec.reps[1],
                "target_rpe": 8.0,
                "rest_seconds": spec.rest_seconds,
                "notes": "Catalog steps",
                "suggested_substitutes": [],
            }
        )
    return {
        "program_name": "Plan",
        "weekly_frequency": 1,
        "split_type": "Full Body",
        "days": [{"day_name": "Full A", "day_order": 1, "exercises": exercises}],
    }


@pytest.fixture
def program_data():
    exercise = {
        "exercise_id": "squat",
        "exercise_name": "Squat",
        "slot_key": "squat_pattern",
        "warmup_sets": 2,
        "target_sets": 3,
        "target_reps_min": 6,
        "target_reps_max": 9,
        "target_rpe": 8.0,
        "rest_seconds": 120,
        "notes": "Old cue",
        "image_path": "old.png",
        "gif_path": "old.gif",
        "suggested_substitutes": [
            {"exercise_id": "leg_press_alt", "exercise_name": "Alternative Leg Press"}
        ],
    }
    return {
        "program_name": "Plan",
        "weekly_frequency": 2,
        "split_type": "Full Body",
        "created_at": "old-timestamp",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "warmup_exercises": [{"exercise_name": "Dead Bug", "sets": 2, "reps": 10}],
                "exercises": [exercise],
            },
            {
                "day_name": "Full B",
                "day_order": 2,
                "warmup_exercises": [{"exercise_name": "Glute Bridge", "sets": 2, "reps": 10}],
                "exercises": [{**exercise}],
            },
        ],
    }


@pytest.fixture
def replacement():
    return {
        "id": "leg_press",
        "name": "Leg Press",
        "instructions": "Lower the platform under control.",
        "image_path": "leg-press.png",
        "gif_path": "leg-press.gif",
    }


def test_substitution_all_occurrences_preserves_program_structure(program_data, replacement):
    ledger = FakeLedger()
    catalog = FakeCatalog({"leg_press": replacement})

    result = substitute_program_exercise(
        ledger,
        catalog,
        program_data,
        ProgramSubstitution("Full A", "squat", "leg_press", all_occurrences=True),
    )

    assert result["ok"] is True
    assert result["replaced_count"] == 2
    assert result["day_names"] == ["Full A", "Full B"]
    assert len(ledger.saved) == 1
    saved, provenance = ledger.saved[0]
    assert provenance is None
    assert "created_at" not in saved
    assert [day["exercises"][0]["exercise_id"] for day in saved["days"]] == ["leg_press", "leg_press"]
    for day in saved["days"]:
        exercise = day["exercises"][0]
        assert (exercise["exercise_name"], exercise["notes"], exercise["image_path"], exercise["gif_path"]) == (
            "Leg Press",
            "Lower the platform under control.",
            "leg-press.png",
            "leg-press.gif",
        )
        assert exercise["suggested_substitutes"] == []
        assert (
            exercise["slot_key"],
            exercise["warmup_sets"],
            exercise["target_sets"],
            exercise["target_reps_min"],
            exercise["target_reps_max"],
            exercise["target_rpe"],
            exercise["rest_seconds"],
        ) == ("squat_pattern", 2, 3, 6, 9, 8.0, 120)
    assert saved["days"][0]["warmup_exercises"] == program_data["days"][0]["warmup_exercises"]


def test_substitution_class_change_uses_slot_archetype_and_swap_back_restores_slot(fresh_store):
    ledger = FakeLedger()
    program = _program_for_slots(["vertical_pull"], "150")

    result = substitute_program_exercise(
        ledger,
        fresh_store,
        program,
        ProgramSubstitution("Full A", "150", "237"),
    )

    assert result["ok"] is True
    changed = ledger.saved[-1][0]
    exercise = changed["days"][0]["exercises"][0]
    assert exercise["exercise_id"] == "237"
    assert (exercise["target_reps_min"], exercise["target_reps_max"], exercise["rest_seconds"]) == (10, 15, 150)
    assert exercise["warmup_sets"] == SLOT_SPECS["vertical_pull"].warmup_sets
    assert exercise["target_rpe"] == 8.0

    result = substitute_program_exercise(
        ledger,
        fresh_store,
        changed,
        ProgramSubstitution("Full A", "237", "150"),
    )

    assert result["ok"] is True
    restored = ledger.saved[-1][0]["days"][0]["exercises"][0]
    spec = SLOT_SPECS["vertical_pull"]
    assert restored["exercise_id"] == "150"
    assert (restored["target_reps_min"], restored["target_reps_max"]) == spec.reps
    assert restored["rest_seconds"] == spec.rest_seconds


def test_substitution_default_changes_only_first_matching_slot(program_data, replacement):
    program_data["days"][0]["exercises"].append({"exercise_id": "squat", "exercise_name": "Second Squat"})
    ledger = FakeLedger()

    result = substitute_program_exercise(
        ledger,
        FakeCatalog({"leg_press": replacement}),
        program_data,
        ProgramSubstitution("Full A", "squat", "leg_press"),
    )

    assert result["ok"] is True
    assert result["replaced_count"] == 1
    saved = ledger.saved[0][0]
    assert [exercise["exercise_id"] for exercise in saved["days"][0]["exercises"]] == ["leg_press", "squat"]
    assert saved["days"][1]["exercises"][0]["exercise_id"] == "squat"


def test_single_swap_adjusts_only_first_duplicate_exercise_on_day(fresh_store):
    ledger = FakeLedger()
    program = _program_for_slots(["vertical_pull", "horizontal_row"], "150")

    result = substitute_program_exercise(
        ledger,
        fresh_store,
        program,
        ProgramSubstitution("Full A", "150", "237"),
    )

    assert result["ok"] is True
    exercises = ledger.saved[-1][0]["days"][0]["exercises"]
    assert [exercise["exercise_id"] for exercise in exercises] == ["237", "150"]
    assert (exercises[0]["target_reps_min"], exercises[0]["target_reps_max"], exercises[0]["rest_seconds"]) == (
        10,
        15,
        150,
    )
    second_slot = SLOT_SPECS["horizontal_row"]
    assert (
        exercises[1]["target_reps_min"],
        exercises[1]["target_reps_max"],
        exercises[1]["rest_seconds"],
    ) == (*second_slot.reps, second_slot.rest_seconds)


def test_week_coordinate_targets_matching_day_in_two_week_program(replacement):
    ledger = FakeLedger()
    first = {
        "day_name": "Full A",
        "day_order": 1,
        "week_order": 1,
        "exercises": [{"exercise_id": "squat", "exercise_name": "Squat"}],
    }
    second = {
        "day_name": "Full A",
        "day_order": 1,
        "week_order": 2,
        "exercises": [{"exercise_id": "squat", "exercise_name": "Squat"}],
    }
    program = {
        "program_name": "Two-week plan",
        "weekly_frequency": 1,
        "split_type": "Full Body",
        "days": [first, second],
        "weeks": [
            {"week_name": "Base", "week_order": 1, "days": [first]},
            {"week_name": "Build", "week_order": 2, "days": [second]},
        ],
    }

    result = substitute_program_exercise(
        ledger,
        FakeCatalog({"leg_press": replacement}),
        program,
        ProgramSubstitution(
            "Full A", "squat", "leg_press", week_order=2, day_order=1
        ),
    )

    assert result["ok"] is True
    weeks = ledger.saved[0][0]["weeks"]
    assert weeks[0]["days"][0]["exercises"][0]["exercise_id"] == "squat"
    assert weeks[1]["days"][0]["exercises"][0]["exercise_id"] == "leg_press"


def test_abs_slot_accepts_real_hanging_leg_raise_with_calf_abs_prescription(fresh_store):
    ledger = FakeLedger()
    program = _program_for_slots(["abs"], "274")

    result = substitute_program_exercise(
        ledger,
        fresh_store,
        program,
        ProgramSubstitution("Full A", "274", "472"),
    )

    assert result["ok"] is True
    exercise = ledger.saved[-1][0]["days"][0]["exercises"][0]
    spec = SLOT_SPECS["abs"]
    assert exercise["exercise_id"] == "472"
    assert (exercise["target_reps_min"], exercise["target_reps_max"]) == spec.reps
    assert exercise["rest_seconds"] == spec.rest_seconds
    assert exercise["warmup_sets"] == spec.warmup_sets


def test_substitution_rejects_hidden_replacement_without_publishing(program_data, replacement):
    ledger = FakeLedger()
    hidden_replacement = {**replacement, "hidden": True}

    result = substitute_program_exercise(
        ledger,
        FakeCatalog({"leg_press": hidden_replacement}),
        program_data,
        ProgramSubstitution("Full A", "squat", "leg_press"),
    )

    assert result["ok"] is False
    assert result["code"] is SubstitutionErrorCode.REPLACEMENT_NOT_FOUND
    assert ledger.saved == []


@pytest.mark.parametrize(
    ("substitution_request", "entries", "code", "message"),
    [
        (
            ProgramSubstitution("Full A", "squat", "squat"),
            {"squat": {"id": "squat"}},
            SubstitutionErrorCode.REPLACEMENT_IS_SOURCE,
            "Choose a different replacement exercise.",
        ),
        (
            ProgramSubstitution("Full A", "squat", "missing"),
            {},
            SubstitutionErrorCode.REPLACEMENT_NOT_FOUND,
            "That replacement exercise was not found.",
        ),
        (
            ProgramSubstitution("Missing", "squat", "leg_press"),
            {"leg_press": {"id": "leg_press"}},
            SubstitutionErrorCode.DAY_NOT_FOUND,
            "That day is not part of your current program.",
        ),
        (
            ProgramSubstitution("Full A", "missing", "leg_press"),
            {"leg_press": {"id": "leg_press"}},
            SubstitutionErrorCode.SOURCE_NOT_ON_DAY,
            "That exercise is not in that day of your current program.",
        ),
        (
            ProgramSubstitution("Full A", "squat", "leg_press"),
            {"leg_press": {"id": "leg_press"}},
            SubstitutionErrorCode.REPLACEMENT_ALREADY_ON_DAY,
            "That replacement exercise is already on the target day.",
        ),
    ],
)
def test_substitution_validation_errors_do_not_publish(program_data, substitution_request, entries, code, message):
    ledger = FakeLedger()
    catalog = FakeCatalog(entries)
    if message == "That replacement exercise is already on the target day.":
        program_data["days"][0]["exercises"].append({"exercise_id": "leg_press"})

    result = substitute_program_exercise(ledger, catalog, program_data, substitution_request)

    assert result["ok"] is False
    assert result["error"] == message
    assert result["code"] is code
    assert ledger.saved == []


def test_substitution_reports_coach_provenance(program_data, replacement):
    ledger = FakeLedger()

    result = substitute_program_exercise(
        ledger,
        FakeCatalog({"leg_press": replacement}),
        program_data,
        ProgramSubstitution(
            "Full A",
            "squat",
            "leg_press",
            published_by_coach_account_id="coach-account",
        ),
    )

    assert result["ok"] is True
    assert ledger.saved[0][1] == "coach-account"
