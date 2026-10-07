#!/usr/bin/env python3
"""Schema safety check for a MAYOS image rollback."""

import re
import sys


def _schema_version(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        return None
    return int(value)


def rollback_is_safe(running_version: object, target_version: object) -> bool:
    """Return whether the target image can open ledgers from the running image."""
    running_schema = _schema_version(running_version)
    target_schema = _schema_version(target_version)
    return running_schema is not None and target_schema is not None and target_schema >= running_schema


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: rollback_guard.py RUNNING_SCHEMA TARGET_SCHEMA", file=sys.stderr)
        return 2
    if not rollback_is_safe(argv[1], argv[2]):
        print(
            "Rollback refused: schema versions must be valid integers and the target must be at least the running version.",
            file=sys.stderr,
        )
        return 1
    print("Schema guard allows rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
