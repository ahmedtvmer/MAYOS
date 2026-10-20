"""Shared normalisation helpers for user-authored text."""

_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_digits(value: str) -> str:
    return value.translate(_DIGIT_TRANSLATION)
