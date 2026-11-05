"""Prescription limits match the logger without rejecting stored programs (#505)."""

import json

import pytest
from pydantic import ValidationError

from agent.ProgramState import CardioPrescriptionSchema
from svc.schemas import (
    ActiveProgramOut,
    CoachProgramDraftIn,
    ProgramImportDraftRowIn,
    ProgramTemplateIn,
    StoredProgramDraftOut,
)


@pytest.mark.parametrize("setting", ["speed_kmh", "incline_pct"])
@pytest.mark.parametrize("new_value", [40, 40.1, 45])
def test_new_cardio_prescription_limits_across_authoring_paths(setting, new_value):
    cardio = {"machine": "treadmill", "minutes": 25, setting: new_value}
    draft = {"days": [{"day_name": "Day 1", "day_order": 1, "cardio": cardio}]}
    import_row = {
        "source_row": 1, "day": 1, "order": 1,
        "exercise_name": "Squat", "exercise_id": "sq", "sets": 3,
        "reps_min": 5, "reps_max": 8, "target_rir": 2, "rest_seconds": 120,
        "cardio": cardio,
    }
    for schema, payload in (
        (CardioPrescriptionSchema, cardio),
        (CoachProgramDraftIn, draft),
        (ProgramTemplateIn, {"name": "Cardio template", "program": draft}),
        (ProgramImportDraftRowIn, import_row),
    ):
        if new_value <= 40:
            schema.model_validate(payload)
        else:
            with pytest.raises(ValidationError, match=setting):
                schema.model_validate(payload)


@pytest.fixture
def legacy_cardio_program(fresh_store):
    ledger = fresh_store.ledger
    fresh_store.catalog_conn.execute(
        "INSERT OR IGNORE INTO exercises(id, name, body_part, target_muscle, equipment)"
        " VALUES ('cardio-squat', 'Squat', 'Upper Legs', 'Quads', 'barbell')"
    )
    fresh_store.catalog_conn.commit()
    ledger.save_training_program({
        "program_name": "Stored cardio", "weekly_frequency": 1,
        "days": [{"day_name": "Day 1", "day_order": 1,
                  "cardio": {"machine": "treadmill", "minutes": 25, "incline_pct": 40},
                  "exercises": [{"exercise_id": "cardio-squat", "target_sets": 3,
                                 "target_reps_min": 5, "target_reps_max": 8}]}],
    })
    # Simulate a prescription saved before the authoring limit changed.
    old_cardio = {"machine": "treadmill", "minutes": 25, "speed_kmh": 45, "incline_pct": 45}
    ledger.conn.execute("UPDATE program_days SET cardio = ?", (json.dumps(old_cardio),))
    ledger.conn.commit()
    return ledger, old_cardio


def test_legacy_program_above_logger_limit_still_loads(legacy_cardio_program):
    ledger, old_cardio = legacy_cardio_program
    loaded = ledger.get_active_program_view()
    assert loaded.days[0].cardio.model_dump(exclude_none=True) == old_cardio
    historical = ledger.get_program_by_version(loaded.version)
    assert historical.days[0].cardio.incline_pct == 45
    response = ActiveProgramOut.model_validate({
        **loaded.model_dump(), "player_controls_program": True,
    })
    assert response.days[0].cardio.incline_pct == 45
    saved_draft = StoredProgramDraftOut.model_validate({
        "days": [{"day_name": "Day 1", "day_order": 1, "cardio": old_cardio}],
    })
    assert saved_draft.days[0].cardio.incline_pct == 45


def test_resaving_legacy_program_preserves_cardio_above_logger_limit(legacy_cardio_program):
    ledger, old_cardio = legacy_cardio_program
    loaded = ledger.get_active_program_view()

    ledger.save_training_program(loaded.model_dump())

    resaved = ledger.get_active_program_view()
    assert resaved.version != loaded.version
    assert resaved.days[0].cardio.model_dump(exclude_none=True) == old_cardio
    historical = ledger.get_program_by_version(loaded.version)
    assert historical.days[0].cardio.model_dump(exclude_none=True) == old_cardio
