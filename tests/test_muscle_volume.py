from types import SimpleNamespace

from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
)
from agent.focus_muscles import FOCUS_REVIEW_MUSCLES
from agent.program_generator import _focus_baseline_sets, _focus_exposure_count
from agent.player_tools import ActiveProgramArgs, _read_active_program
from agent.progression_engine import get_weekly_muscle_volume
from core.muscle_volume import (
    MAIN_MUSCLE_GROUPS,
    default_muscle_credits,
    main_group_for_focus,
    normalize_main_muscle,
)
from database.exercise_library.curation import load_exercise_curation


def test_subregions_map_to_one_main_group_and_helpers_are_deduplicated():
    assert normalize_main_muscle("Upper Chest") == "chest"
    assert normalize_main_muscle("Lats") == "lats"
    assert all(
        normalize_main_muscle(muscle) == "traps"
        for muscle in (
            "Upper Back", "Mid Back", "Mid-Back", "Middle Back", "Rhomboid", "Rhomboids",
            "Trapezius", "Upper Traps", "Mid Traps", "Lower Traps",
        )
    )
    assert normalize_main_muscle("Back") is None
    assert default_muscle_credits("Back") == {}
    assert main_group_for_focus("back") == "lats"
    assert main_group_for_focus("lats") == "lats"
    assert main_group_for_focus("traps") == "traps"
    assert normalize_main_muscle("Front Delts") == "shoulders"
    assert normalize_main_muscle("Side Delts") == "shoulders"
    assert normalize_main_muscle("Rear Delts") == "rear delts"
    assert normalize_main_muscle("Obliques") == "core"
    assert normalize_main_muscle("Lower Back") is None
    assert all(len(groups) <= 1 for groups in FOCUS_REVIEW_MUSCLES.values())
    assert len(MAIN_MUSCLE_GROUPS) == 12
    assert "back" not in MAIN_MUSCLE_GROUPS
    assert FOCUS_REVIEW_MUSCLES["lats"] == {"lats"}
    assert FOCUS_REVIEW_MUSCLES["traps"] == {"traps"}

    assert default_muscle_credits(
        "Upper Chest", ["Chest", "Front Delts", "Side Delts", "Triceps"]
    ) == {"chest": 1.0, "shoulders": 0.5, "triceps": 0.5}


def test_reviewed_credits_and_defaults_are_materialized_per_exercise(
    fresh_store, seed_exercise_curation
):
    seed_exercise_curation(fresh_store, {
        "mayos:1": {"primary_muscle": "Traps"},
        "mayos:2": {
            "primary_muscle": "Biceps",
            "muscle_credits": "biceps=0.75",
        },
        "mayos:3": {
            "primary_muscle": "Traps",
            "muscle_credits": "shoulders=1|traps=0.75",
        },
    })

    credits = fresh_store.ledger.volume_review_exercise_credits(
        ["mayos:1", "mayos:2", "mayos:3"]
    )
    assert credits["mayos:2"]["biceps"] == {
        "credit": 0.75, "is_primary": True, "source": "reviewed",
    }
    assert credits["mayos:1"] == {
        "traps": {"credit": 1.0, "is_primary": True, "source": "default"},
    }
    assert credits["mayos:3"] == {
        "shoulders": {"credit": 1.0, "is_primary": True, "source": "reviewed"},
        "traps": {"credit": 0.75, "is_primary": False, "source": "reviewed"},
    }


def test_starting_reviewed_overrides_match_program_design_table():
    curation = load_exercise_curation()
    expected = {
        "3541": {"shoulders": 1.0, "traps": 0.75},
        "584": {"shoulders": 1.0, "traps": 0.25},
        "571": {"traps": 1.0, "lats": 0.5, "rear delts": 0.5, "biceps": 0.5},
        "3562": {"glutes": 1.0, "hamstrings": 0.25},
        "739": {"quads": 1.0, "glutes": 0.5},
        "2368": {"quads": 1.0, "glutes": 0.75},
    }

    actual = {
        exercise_id: dict(curation[exercise_id].muscle_credits)
        for exercise_id in expected
    }
    assert actual == expected


def test_pull_row_shrug_and_reverse_fly_credits_follow_the_split():
    curation = load_exercise_curation()
    pull_credits = {
        exercise_id: default_muscle_credits(
            curation[exercise_id].primary_muscle,
            exercise_name=curation[exercise_id].source_name,
        )
        for exercise_id in ("15", "150")
    }
    assert pull_credits == {"15": {"lats": 1.0}, "150": {"lats": 1.0}}
    assert default_muscle_credits("Lats", ["Biceps"]) == {
        "lats": 1.0, "biceps": 0.5,
    }
    assert default_muscle_credits("Traps") == {"traps": 1.0}
    assert default_muscle_credits(
        "Upper Back", ["Lats", "Rear Delts", "Biceps"], exercise_name="Cable Row"
    ) == {
        "traps": 1.0, "lats": 0.5, "rear delts": 0.5, "biceps": 0.5,
    }
    assert default_muscle_credits(
        "Lats", ["Biceps"], exercise_name="Machine High Row"
    ) == {"traps": 1.0, "lats": 0.5, "rear delts": 0.5, "biceps": 0.5}
    assert default_muscle_credits("Traps", exercise_name="Barbell Shrug") == {
        "traps": 1.0,
    }
    assert dict(curation["184"].muscle_credits) == {"lats": 1.0, "triceps": 0.25}
    assert dict(curation["602"].muscle_credits) == {"rear delts": 1.0, "traps": 0.5}
    assert dict(curation["571"].muscle_credits) == {
        "traps": 1.0, "lats": 0.5, "rear delts": 0.5, "biceps": 0.5,
    }


def test_active_program_volume_uses_reviewed_credits_once_per_main_group(
    fresh_store, seed_exercise_curation
):
    seed_exercise_curation(fresh_store, {
        "3541": {
            "primary_muscle": "Traps",
            "muscle_credits": "shoulders=1|traps=0.75",
        },
    })
    program = PersistedProgramSchema(
        program_name="Reviewed credits",
        split_type="Custom",
        weekly_frequency=1,
        days=[PersistedProgramDaySchema(
            day_name="Shoulders",
            day_order=1,
            exercises=[PersistedProgramExerciseSchema(
                exercise_id="3541",
                exercise_name="Incline Y-Raise (Dumbbell)",
                target_sets=2,
                target_reps_min=8,
                target_reps_max=12,
                target_rpe=8,
            )],
        )],
    )
    fresh_store.ledger.save_training_program(program.model_dump())

    result = _read_active_program(fresh_store.ledger, ActiveProgramArgs())

    assert result["weekly_sets_by_muscle"]["shoulders"] == 2
    assert result["weekly_sets_by_muscle"]["traps"] == 0
    assert result["weekly_volume_by_muscle"]["shoulders"] == {
        "direct": 2, "indirect": 0, "total": 2,
    }
    assert result["weekly_volume_by_muscle"]["traps"] == {
        "direct": 0, "indirect": 1.5, "total": 1.5,
    }
    assert result["days"] == [{"day": "Shoulders", "muscles": ["shoulders", "traps"]}]
    shoulder_scope = _read_active_program(
        fresh_store.ledger, ActiveProgramArgs(muscle="shoulders")
    )
    assert shoulder_scope["days"][0]["exercises"][0]["name"] == "Incline Y-Raise (Dumbbell)"
    from service.chat_program_edit import _exercise_ids_for_muscles

    assert "3541" in _exercise_ids_for_muscles(fresh_store, ["shoulders"])


def test_focus_volume_and_frequency_use_main_group_credits():
    exercises = {
        "press": SimpleNamespace(exercise_id="press", working_sets=2),
        "row": SimpleNamespace(exercise_id="row", working_sets=3),
        "raise": SimpleNamespace(exercise_id="raise", working_sets=4),
    }
    focus_plan = SimpleNamespace(
        target_group="shoulders",
        exercise_credits={
            "press": {"shoulders": {"credit": 1.0}},
            "row": {"shoulders": {"credit": 0.5}},
            "raise": {"shoulders": {"credit": 1.0}},
        },
    )
    week = {1: (exercises["press"],), 2: (exercises["row"], exercises["raise"])}

    assert _focus_baseline_sets("shoulders", week, focus_plan.exercise_credits) == 7.5
    assert _focus_exposure_count(focus_plan, week) == 2


def test_logged_volume_preserves_reviewed_quarter_credit():
    class SetCursor:
        def execute(self, _query, _params):
            return None

        def fetchall(self):
            return [("y_raise",)]

    credits = {
        "y_raise": {
            "shoulders": {"credit": 1.0},
            "traps": {"credit": 0.75},
        },
    }
    ledger = SimpleNamespace(
        conn=SimpleNamespace(cursor=lambda: SetCursor()),
        volume_review_exercise_credits=lambda _ids: credits,
    )

    volume = get_weekly_muscle_volume(ledger)

    assert volume["Shoulders"] == 1.0
    assert volume["Traps"] == 0.75
