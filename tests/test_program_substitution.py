import pytest

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


class FakeLedger:
    def __init__(self):
        self.saved = []

    def save_training_program(self, program_data, published_by_coach_account_id=None):
        self.saved.append((program_data, published_by_coach_account_id))


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
