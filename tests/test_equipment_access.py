"""Equipment access free-text mapping and ledger migration (#228)."""

import json
import sqlite3
from contextlib import closing

import pytest

from database.migration_manager import apply_lazy_migrations, get_ledger_schema_version
from service.intake import validate_answer
from utils.equipment_access import (
    BODYWEIGHT_ONLY,
    COMMERCIAL_GYM,
    HOME_GYM,
    map_equipment_access,
)


@pytest.mark.parametrize(
    ("free_text", "expected"),
    [
        ("a big gym", COMMERCIAL_GYM),
        ("commercial gym", COMMERCIAL_GYM),
        ("my gym", COMMERCIAL_GYM),
        ("the gym", COMMERCIAL_GYM),
        ("commercial gym near my home", COMMERCIAL_GYM),
        ("my garage", HOME_GYM),
        ("home gym", HOME_GYM),
        ("no gym, just dumbbells at home", HOME_GYM),
        ("dumbbells and a bench", HOME_GYM),
        ("bands only", HOME_GYM),
        ("I workout at home with nothing", BODYWEIGHT_ONLY),
        ("hotel room, no equipment", BODYWEIGHT_ONLY),
        ("no equipment", BODYWEIGHT_ONLY),
        ("nothing", BODYWEIGHT_ONLY),
        ("bodyweight only", BODYWEIGHT_ONLY),
        ("unmapped training place", COMMERCIAL_GYM),
    ],
)
def test_equipment_access_mapping(free_text, expected):
    assert map_equipment_access(free_text) == expected
    assert validate_answer("equipment_access", free_text) == expected


@pytest.mark.parametrize(
    ("legacy_value", "expected"),
    [
        ("a big gym", COMMERCIAL_GYM),
        ("commercial gym", COMMERCIAL_GYM),
        ("my garage", HOME_GYM),
        ("hotel room, no equipment", BODYWEIGHT_ONLY),
        ("unmapped legacy value", COMMERCIAL_GYM),
    ],
)
def test_v16_migration_maps_legacy_profiles_and_intake(legacy_value, expected, tmp_path):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(
            "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, equipment_access TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE intake_answers (field TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO user_profile VALUES (1, ?)", (legacy_value,))
        conn.execute(
            "INSERT INTO intake_answers VALUES ('equipment_access', ?)",
            (json.dumps(legacy_value),),
        )
        conn.execute("PRAGMA user_version = 16")
        conn.commit()

        apply_lazy_migrations(
            conn,
            username="equipment-access-test",
            ledgers_dir=tmp_path / "ledgers",
            backups_dir=tmp_path / "backups",
            target_version=17,
        )

        profile_access = conn.execute(
            "SELECT equipment_access FROM user_profile"
        ).fetchone()[0]
        intake_access = conn.execute("SELECT value FROM intake_answers").fetchone()[0]
        assert profile_access == expected
        assert json.loads(intake_access) == expected
        assert get_ledger_schema_version(conn) == 17
        with pytest.raises(sqlite3.IntegrityError, match="Invalid Equipment access"):
            conn.execute("UPDATE user_profile SET equipment_access = 'fourth option'")
