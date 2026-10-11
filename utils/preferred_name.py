"""Validation shared by preferred-name settings, chat capture, and prompts."""

from typing import Any

PREFERRED_NAME_ERROR = (
    "Preferred name must be a nonempty printable string of at most 60 characters"
)


def is_valid_preferred_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 60
        and bool(value.strip())
        and value.isprintable()
    )


def validate_preferred_name(value: Any) -> str:
    if not is_valid_preferred_name(value):
        raise ValueError(PREFERRED_NAME_ERROR)
    return value
