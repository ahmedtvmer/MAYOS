from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.curation_coverage import (
    build_curation_coverage_report,
    read_curation_coverage_rows,
)
from agent.program_blueprints import SLOT_SPECS
from scripts.curation_coverage_report import main
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, HOME_GYM


def test_coverage_counts_visible_matches_allowed_by_equipment_access():
    report = build_curation_coverage_report(
        [
            {
                "id": "314",
                "equipment": "dumbbell",
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Upper Chest",
            },
            {
                "id": "other",
                "equipment": "cable",
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Upper Chest",
            },
            {
                "id": "wrong-action",
                "equipment": "cable",
                "primary_action": "Knee Flexion",
                "primary_muscle": "Upper Chest",
            },
            {
                "id": "wrong-muscle",
                "equipment": "cable",
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
            },
            {
                "id": "bodyweight",
                "equipment": "body weight",
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Upper Chest",
            },
        ]
    )
    by_access = {
        row.equipment_access: row
        for row in report
        if row.slot == "incline_press"
    }

    assert by_access[COMMERCIAL_GYM].staple_count == 1
    assert by_access[COMMERCIAL_GYM].curated_signature_count == 2
    assert by_access[COMMERCIAL_GYM].candidate_count == 2
    assert by_access[HOME_GYM].staple_count == 1
    assert by_access[HOME_GYM].curated_signature_count == 2
    assert by_access[BODYWEIGHT_ONLY].staple_count == 0
    assert by_access[BODYWEIGHT_ONLY].curated_signature_count == 1


def test_visibility_query_excludes_a_hidden_staple_defensively(fresh_store):
    updated = fresh_store.catalog_conn.execute(
        "UPDATE exercise_curated_fields SET hidden = 1 WHERE exercise_id = '757'"
    )
    # Defensive coverage: curation rejects Hidden Staples, but the report query must exclude one.
    assert updated.rowcount == 1

    visible_ids = {
        str(row["id"]) for row in read_curation_coverage_rows(fresh_store.catalog_conn)
    }

    assert "757" not in visible_ids


def test_every_slot_has_commercial_gym_staple_or_signature_candidate(fresh_store):
    report = build_curation_coverage_report(
        read_curation_coverage_rows(fresh_store.catalog_conn)
    )
    commercial = [row for row in report if row.equipment_access == COMMERCIAL_GYM]

    assert len(commercial) == len(SLOT_SPECS)
    for coverage in commercial:
        assert coverage.staple_count or coverage.curated_signature_count, (
            f"Slot '{coverage.slot}' has no Commercial gym Staple or signature candidates"
        )


def test_coverage_command_prints_all_slots_and_equipment_access_values(
    fresh_store, capsys
):
    exit_code = main(["--catalog", str(fresh_store.catalog_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Primary actions" in output
    assert "Signature matches" in output
    assert "Staples ∪ signature" in output
    assert len(output.splitlines()) == 1 + len(SLOT_SPECS) * 3
