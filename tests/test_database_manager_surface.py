"""Public-surface contract for DatabaseManager after the #78 split.

Compares the refactored class against the pre-split snapshot committed at
``tests/data/database_manager_public_surface.json``. Fails on any missing,
extra, or changed public method so callers outside the API tests (operational
scripts, agent graphs) stay protected.
"""
import importlib
import inspect
import json
import os
import sqlite3
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "tests" / "data" / "database_manager_public_surface.json"


def _load_snapshot():
    with SNAPSHOT.open() as f:
        return json.load(f)


def _normalize_path_default(value):
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.is_absolute():
            try:
                relative = Path(os.path.abspath(path)).relative_to(REPO_ROOT)
            except ValueError:
                pass
            else:
                return f"<repo>/{relative.as_posix()}"
    return value


def _current_surface(cls):
    methods = {}
    attributes = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(cls, name)
        if isinstance(raw, property):
            methods[name] = {"kind": "property", "signature": "property"}
        elif callable(raw) or isinstance(raw, (staticmethod, classmethod)):
            if isinstance(raw, staticmethod):
                kind = "staticmethod"
            elif isinstance(raw, classmethod):
                kind = "classmethod"
            else:
                kind = "method"
            try:
                signature = inspect.signature(getattr(cls, name))
                parameters = [
                    parameter.replace(default=_normalize_path_default(parameter.default))
                    for parameter in signature.parameters.values()
                ]
                signature = str(signature.replace(parameters=parameters))
            except (TypeError, ValueError):
                signature = ""
            methods[name] = {"kind": kind, "signature": signature}
        else:
            attributes[name] = repr(raw)
    return methods, attributes


def _assert_methods_match_snapshot(expected, methods):
    missing = sorted(set(expected) - set(methods))
    extra = sorted(set(methods) - set(expected))
    changed = sorted(k for k in expected if k in methods and methods[k] != expected[k])

    assert not missing, f"public methods disappeared: {missing}"
    assert not extra, f"new public methods appeared: {extra}"
    assert not changed, f"public method signatures changed: {changed}"


def test_public_methods_unchanged_since_snapshot():
    snapshot = _load_snapshot()
    mod = importlib.import_module("database.database_manager")
    methods, _ = _current_surface(mod.DatabaseManager)

    _assert_methods_match_snapshot(snapshot["methods"], methods)


def _with_added_method(methods):
    return {**methods, "new_public_method": {"kind": "method", "signature": "(self) -> None"}}


def _without_seed_method(methods):
    return {name: entry for name, entry in methods.items() if name != "initialize_and_seed"}


def _with_changed_seed_signature(methods):
    changed = {**methods["initialize_and_seed"], "signature": "(self, csv_path=None) -> None"}
    return {**methods, "initialize_and_seed": changed}


@pytest.mark.parametrize(
    ("alter", "message"),
    [
        (_with_added_method, "new public methods appeared"),
        (_without_seed_method, "public methods disappeared"),
        (_with_changed_seed_signature, "public method signatures changed"),
    ],
)
def test_public_surface_comparison_detects_method_changes(alter, message):
    expected = _load_snapshot()["methods"]

    with pytest.raises(AssertionError, match=message):
        _assert_methods_match_snapshot(expected, alter(expected))


def test_public_attributes_unchanged_since_snapshot():
    snapshot = _load_snapshot()
    mod = importlib.import_module("database.database_manager")
    _, attributes = _current_surface(mod.DatabaseManager)

    expected = snapshot["attributes"]
    missing = sorted(set(expected) - set(attributes))
    changed = sorted(k for k in expected if k in attributes and attributes[k] != expected[k])
    assert not missing, f"public attributes disappeared: {missing}"
    assert not changed, f"public attribute values changed: {changed}"


def test_module_level_names_still_importable():
    snapshot = _load_snapshot()
    mod = importlib.import_module("database.database_manager")
    for name in snapshot["module_names"]:
        assert hasattr(mod, name), f"module-level name no longer importable: {name}"


def test_existing_coach_invite_catalog_adds_revocation_column(tmp_path: Path):
    catalog_path = tmp_path / "catalog.db"
    legacy = sqlite3.connect(catalog_path)
    legacy.execute(
        "CREATE TABLE coach_invites (token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL,"
        " expires_at TEXT NOT NULL, used_at TEXT, created_at TEXT NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO coach_invites VALUES (?, ?, ?, NULL, ?)",
        ("a" * 64, "account-id", "2030-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()

    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        with db.catalog_locked() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(coach_invites)")}
            invite = conn.execute(
                "SELECT token_hash, revoked_at FROM coach_invites WHERE account_id = ?",
                ("account-id",),
            ).fetchone()
        assert "revoked_at" in columns
        assert invite == ("a" * 64, None)
    finally:
        db.catalog_conn.close()
