"""Public-surface contract for DatabaseManager after the #78 split.

Compares the refactored class against the pre-split snapshot committed at
``tests/data/database_manager_public_surface.json``. Fails on any missing,
extra, or changed public method so callers outside the API tests (operational
scripts, agent graphs) stay protected.
"""
import importlib
import inspect
import json

SNAPSHOT = "tests/data/database_manager_public_surface.json"


def _load_snapshot():
    with open(SNAPSHOT) as f:
        return json.load(f)


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
                signature = str(inspect.signature(getattr(cls, name)))
            except (TypeError, ValueError):
                signature = ""
            methods[name] = {"kind": kind, "signature": signature}
        else:
            attributes[name] = repr(raw)
    return methods, attributes


def test_public_methods_unchanged_since_snapshot():
    snapshot = _load_snapshot()
    mod = importlib.import_module("database.database_manager")
    methods, _ = _current_surface(mod.DatabaseManager)

    expected = snapshot["methods"]
    missing = sorted(set(expected) - set(methods))
    extra = sorted(set(methods) - set(expected))
    changed = sorted(k for k in expected if k in methods and methods[k] != expected[k])

    assert not missing, f"public methods disappeared: {missing}"
    assert not extra, f"new public methods appeared: {extra}"
    assert not changed, f"public method signatures changed: {changed}"


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
