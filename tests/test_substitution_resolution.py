"""Swap target resolution: catalog-name-first installs, hallucinated-name refusals, muscle mismatches."""

import shutil
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph
from agent.assistant_graph import exercise_substitution_node
from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

CHEST_SLOT = "577"  # machine chest press (pectorals | chest)
REVERSE_LAT_SLOT = "673"  # reverse grip machine lat pulldown (lats | back)
CABLE_LAT_SLOT = "150"  # cable bar lateral pulldown (lats | back)

HALLUCINATED_TARGET = "Machine Two-Arm Lateral Pulldown"


def _exercise(exercise_id: str) -> dict:
    return {
        "exercise_id": exercise_id,
        "target_sets": 3,
        "target_reps_min": 8,
        "target_reps_max": 12,
        "target_rpe": 8.5,
    }


@pytest.fixture
def sub_db(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="default",
    )
    try:
        monkeypatch.setattr(assistant_graph, "db", db)
        db.save_training_program(
            {
                "program_name": "Resolution Test Split",
                "weekly_frequency": 3,
                "split_type": "Upper/Lower",
                "days": [
                    {
                        "day_name": "Upper 1",
                        "day_order": 1,
                        "exercises": [_exercise(CHEST_SLOT), _exercise(REVERSE_LAT_SLOT), _exercise(CABLE_LAT_SLOT)],
                    }
                ],
            }
        )
        yield db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _state(source: str, target: str) -> dict:
    return {
        "messages": [HumanMessage(content=f"swap {source} for {target}")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": source, "target_exercise": target},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }


def _slot_name(db, index: int) -> str:
    program = db.get_active_program()
    assert program is not None
    return program.days[0].exercises[index].exercise_name.lower()


def test_catalog_name_resolution_tiers(sub_db):
    db = sub_db
    assert db.find_exercises_by_name("machine chest press")[0]["id"] == "577"
    # Punctuation-insensitive exact: "push up" ≡ "push-up".
    assert db.find_exercises_by_name("push up")[0]["name"] == "push-up"
    # Substring: partial name resolves to the full catalog name.
    assert db.find_exercises_by_name("romanian deadlift")[0]["name"] == "barbell romanian deadlift"
    # Token-AND: scrambled tokens still resolve.
    assert db.find_exercises_by_name("press chest machine")[0]["name"] == "machine chest press"
    # The hallucinated transcript target matches nothing.
    assert db.find_exercises_by_name(HALLUCINATED_TARGET) == []


def test_hallucinated_target_refuses_instead_of_installing_sibling(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", HALLUCINATED_TARGET))
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()
    assert _slot_name(db, 1) == "reverse grip machine lat pulldown"


def test_named_catalog_target_installs_without_semantic_search(sub_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("EMBED_MODEL must not be used for a named catalog match")

    monkeypatch.setattr(assistant_graph, "EMBED_MODEL", SimpleNamespace(embed_query=_boom, embed_documents=_boom))
    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", "machine front pulldown"))
    assert res["program_updated"] is True
    assert "machine front pulldown" in res["response_content"].lower()
    assert _slot_name(sub_db, 1) == "machine front pulldown"


def test_punctuation_normalized_target_installs(sub_db):
    res = exercise_substitution_node(_state("machine chest press", "push up"))
    assert res["program_updated"] is True
    assert "push-up" in res["response_content"].lower()
    assert _slot_name(sub_db, 0) == "push-up"


def test_transcript_replay_second_commit_refuses(sub_db):
    db = sub_db
    first = exercise_substitution_node(_state("reverse grip machine lat pulldown", "machine front pulldown"))
    assert first["program_updated"] is True

    second = exercise_substitution_node(_state("machine front pulldown", HALLUCINATED_TARGET))
    assert second["program_updated"] is False
    assert _slot_name(db, 1) == "machine front pulldown"


def test_muscle_incompatible_named_target_refuses(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", "barbell bench press"))
    assert res["program_updated"] is False
    assert "is in the exercise database" in res["response_content"]
    assert "pectorals" in res["response_content"].lower()
    assert _slot_name(db, 1) == "reverse grip machine lat pulldown"


def test_self_swap_refuses(sub_db):
    db = sub_db
    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", "reverse grip machine lat pulldown"))
    assert res["program_updated"] is False
    assert _slot_name(db, 1) == "reverse grip machine lat pulldown"


@pytest.mark.parametrize("target", ["it", "choice", "one", "two", "three", "first"])
def test_unspecific_target_refuses_without_junk_match(sub_db, target):
    db = sub_db
    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", target))
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()
    assert _slot_name(db, 1) == "reverse grip machine lat pulldown"


def test_followup_hint_uses_real_catalog_name(sub_db, monkeypatch):
    monkeypatch.setattr(DatabaseManager, "find_exercises_by_name", lambda self, query, limit=5: [])
    variants = [
        {
            "id": "9001",
            "name": "machine lateral pulldown",
            "target_muscle": "lats",
            "body_part": "back",
            "equipment": "leverage machine",
            "distance": 0.10,
        },
        {
            "id": "9002",
            "name": "cable lateral pulldown",
            "target_muscle": "lats",
            "body_part": "back",
            "equipment": "cable",
            "distance": 0.11,
        },
    ]
    monkeypatch.setattr(DatabaseManager, "search_similar_exercises", lambda self, vec, limit=5: variants)

    res = exercise_substitution_node(_state("reverse grip machine lat pulldown", "something easier on my elbows"))
    assert res["program_updated"] is True
    assert "swap reverse grip machine lat pulldown for cable lateral pulldown" in res["response_content"]
    assert "swap for cable machine" not in res["response_content"]
