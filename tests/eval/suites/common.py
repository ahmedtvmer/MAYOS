"""Shared dataset, report, and isolated catalog helpers for model-gate suites."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.eval.parity_gate import ScoreBar


def load_case_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Evaluation dataset must be a JSON object: {path}")
    return payload


def load_case_group(
    payload: dict[str, Any], group_name: str, label: str, requirements: dict[str, Any]
) -> list[dict[str, Any]]:
    _validate_dataset_status(payload, label, requirements.get("status"))
    cases = payload.get(group_name)
    _validate_group_size(cases, label, requirements.get("count"))
    _validate_case_identifiers(cases, label)
    return cases


def _validate_dataset_status(payload: dict[str, Any], label: str, required_status: Any) -> None:
    if required_status is not None and payload.get("status") != required_status:
        raise ValueError(f"{label} requires dataset status '{required_status}'.")


def _validate_group_size(cases: Any, label: str, expected_count: Any) -> None:
    if (
        not isinstance(cases, list)
        or not cases
        or (expected_count is not None and len(cases) != expected_count)
    ):
        count = len(cases) if isinstance(cases, list) else "invalid"
        expectation = f"exactly {expected_count}" if expected_count is not None else "at least one"
        raise ValueError(f"{label} must contain {expectation} cases; got {count}.")


def _validate_case_identifiers(cases: list[Any], label: str) -> None:
    if any(not isinstance(case, dict) for case in cases):
        raise ValueError(f"{label} cases must be JSON objects.")
    identifiers = [case.get("id") for case in cases]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError(f"{label} case ids must be non-empty strings.")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{label} case ids must be unique.")


def suite_summary(fields: dict[str, Any], bar: ScoreBar) -> dict[str, Any]:
    return {**fields, "bar": bar.as_dict()}


def empty_suite_summary(
    bar: ScoreBar, total: int, reasons: list[str], suite_fields: dict[str, Any]
) -> dict[str, Any]:
    return suite_summary(
        {
            "score": 0,
            "total": total,
            "passed": False,
            "failure_reasons": list(reasons),
            **suite_fields,
        },
        bar,
    )


@contextmanager
def isolated_catalog_store():
    from tests.catalog import close_catalog_store, create_catalog_store

    with tempfile.TemporaryDirectory(prefix="mayos-player-eval-") as temp_root:
        root = Path(temp_root)
        store = create_catalog_store(root)
        try:
            yield store
        finally:
            close_catalog_store(store)
