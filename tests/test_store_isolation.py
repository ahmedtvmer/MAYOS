"""Structural store-isolation test for the split database modules (#78, #79).

The folder a module lives in states which store it may touch:

- ``database/registry/`` and ``database/exercise_library/`` modules may
  reference the registry connection (``catalog_conn`` / ``_catalog_lock`` /
  ``catalog_transaction``) but never the ledger connection or active user.
- ``database/ledger/`` modules may reference the ledger connection
  (``user_conn`` / ``conn`` / ``active_user`` / ``ledger_transaction``) but
  never the registry connection or catalog lock.

Anything that needs both belongs in a top-level operation module named for the
operation (e.g. ``database/account_deletion.py``), which this test does not scan.

Phase B1 (#79): the ``service/`` and ``svc/`` layers must reach the ledger only
through an explicit handle (``get_ledger`` / ``db.open_ledger``), never the
thread-local compatibility mount (``bind_user`` / ``bind_request`` /
``switch_user`` / ``active_user`` / ``unmount_user``). The few call sites that
still hand off to ``agent/`` code are marked ``# Phase B2:`` and are the only
permitted exceptions.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REGISTRY_TOKENS = (".catalog_conn", "._catalog_lock", ".catalog_transaction")
LEDGER_TOKENS = (
    ".user_conn",
    "self.conn",
    "self.active_user",
    ".ledger_transaction",
    "._local",
)

REGISTRY_PACKAGES = ("database/registry", "database/exercise_library")
LEDGER_PACKAGE = "database/ledger"

#: Thread-local ledger seams service/svc must no longer rely on, except on a
#: line explicitly marked ``# Phase B2:`` (the agent hand-off sites).
THREAD_LOCAL_SEAMS = ("bind_user(", "bind_request(", "switch_user(", "active_user", "unmount_user")
LAYER_PACKAGES = ("service", "svc")

#: ``service/_base.py`` is the home of the compatibility primitive itself; its
#: definition is what the other layers may call during the transition.
COMPAT_PRIMITIVE = Path("service/_base.py")

#: Definition sites of the compatibility primitives are allowed; call sites are not.
_COMPAT_DEFINITIONS = ("def bind_user(", "def bind_request(")


def _modules(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def _references(source: str, tokens: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token in source]


@pytest.mark.parametrize("package", REGISTRY_PACKAGES)
def test_registry_and_library_modules_never_touch_the_ledger(package):
    for path in _modules(package):
        source = path.read_text()
        offenders = _references(source, LEDGER_TOKENS)
        assert not offenders, f"{path.relative_to(ROOT)} references ledger state: {offenders}"


def test_ledger_modules_never_touch_the_registry():
    for path in _modules(LEDGER_PACKAGE):
        source = path.read_text()
        offenders = _references(source, REGISTRY_TOKENS)
        assert not offenders, f"{path.relative_to(ROOT)} references registry state: {offenders}"


@pytest.mark.parametrize("package", LAYER_PACKAGES)
def test_service_and_svc_reach_the_ledger_only_through_an_explicit_handle(package):
    for path in _modules(package):
        if path.relative_to(ROOT) == COMPAT_PRIMITIVE:
            continue
        offenders = []
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if "# Phase B2:" in line or any(defn in line for defn in _COMPAT_DEFINITIONS):
                continue
            for token in THREAD_LOCAL_SEAMS:
                if token in line:
                    offenders.append((lineno, token, line.strip()))
        assert not offenders, (
            f"{path.relative_to(ROOT)} uses thread-local ledger state outside a "
            f"`# Phase B2:` line: {offenders}"
        )
