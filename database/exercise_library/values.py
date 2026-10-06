"""Shared parsing for pipe-delimited Exercise curation values."""


def split_curation_values(cell: str | None) -> tuple[str, ...]:
    return tuple(value.strip() for value in (cell or "").split("|") if value.strip())
