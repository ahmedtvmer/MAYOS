"""Canonical fixture and owner-review helpers for Program import evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

PENDING_REVIEW_RECORD = {
    "reviewed": False,
    "reviewed_by": "",
    "reviewed_on": "",
    "reviewed_dataset_hash": "",
}
REVIEW_FILENAME = "REVIEW.json"


def list_fixture_files(directory: Path | str) -> list[Path]:
    """Lists fixture JSON files in canonical filename order."""
    return sorted(path for path in Path(directory).glob("*.json") if path.name != REVIEW_FILENAME)


def canonical_fixture_entry(filename: str, fixture: dict[str, Any]) -> bytes:
    payload = json.dumps(
        fixture,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return filename.encode("utf-8") + b"\0" + payload + b"\n"


def fixture_entries_hash(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["filename"]):
        digest.update(canonical_fixture_entry(entry["filename"], entry["fixture"]))
    return digest.hexdigest()


def load_fixture_entries(directory: Path | str) -> list[dict[str, Any]]:
    entries = []
    for path in list_fixture_files(directory):
        entries.append(
            {
                "filename": path.name,
                "fixture": json.loads(path.read_text(encoding="utf-8")),
            }
        )
    if not entries:
        raise ValueError(f"no Program import evaluation fixtures found in {directory}")
    return entries


def dataset_hash_for_directory(directory: Path | str) -> str:
    return fixture_entries_hash(load_fixture_entries(directory))


def valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def valid_review_record(review: Any) -> bool:
    if not isinstance(review, dict) or review.get("reviewed") is not True:
        return False
    reviewer = review.get("reviewed_by")
    reviewed_on = review.get("reviewed_on")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return False
    if not isinstance(reviewed_on, str):
        return False
    try:
        date.fromisoformat(reviewed_on)
    except ValueError:
        return False
    return valid_sha256(review.get("reviewed_dataset_hash"))


def review_matches_dataset(review: Any, dataset_hash: str) -> bool:
    return valid_review_record(review) and review["reviewed_dataset_hash"] == dataset_hash
