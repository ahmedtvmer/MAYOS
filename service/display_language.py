"""Supported account Display languages shared by the service contracts."""

from typing import Literal, get_args

DisplayLanguage = Literal["en", "ar"]
DISPLAY_LANGUAGE_ORDER = get_args(DisplayLanguage)
SUPPORTED_DISPLAY_LANGUAGES = frozenset(DISPLAY_LANGUAGE_ORDER)
