"""Supported account Display languages shared by the service contracts."""

import html
import math
import re
from collections.abc import Mapping
from typing import Any, Literal, get_args

DisplayLanguage = Literal["en", "ar"]
DISPLAY_LANGUAGE_ORDER = get_args(DisplayLanguage)
SUPPORTED_DISPLAY_LANGUAGES = frozenset(DISPLAY_LANGUAGE_ORDER)


def request_language(request: Any, submitted: object = None) -> DisplayLanguage:
    """Use a supported submitted choice, then the request's system preference."""
    if submitted == "en":
        return "en"
    if submitted == "ar":
        return "ar"
    return preferred_display_language(request.headers.get("accept-language"))


def render_localized(
    template: str,
    copy: Mapping[str, str],
    language: DisplayLanguage,
) -> str:
    """Render escaped copy and shared language attributes into an HTML template."""
    replacements = {key: html.escape(value) for key, value in copy.items()}
    replacements.update(
        lang=language,
        dir="rtl" if language == "ar" else "ltr",
        en_selected="selected" if language == "en" else "",
        ar_selected="selected" if language == "ar" else "",
    )
    return re.sub(
        r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}",
        lambda match: replacements.get(match.group(1), match.group(0)),
        template,
    )


def preferred_display_language(accept_language: str | None) -> DisplayLanguage:
    """Select the best supported language from an ``Accept-Language`` header."""
    if not accept_language:
        return "en"

    preferences: list[tuple[float, int, DisplayLanguage]] = []
    for position, preference_text in enumerate(accept_language.split(",")):
        preference = _supported_language_preference(preference_text)
        if preference is not None:
            quality, language = preference
            preferences.append((-quality, position, language))

    if not preferences:
        return "en"
    return min(preferences)[2]


def _supported_language_preference(
    preference_text: str,
) -> tuple[float, DisplayLanguage] | None:
    parts = preference_text.strip().split(";")
    language_tag = parts[0].strip().lower().split("-", maxsplit=1)[0]
    if language_tag == "ar":
        language: DisplayLanguage = "ar"
    elif language_tag == "en":
        language = "en"
    else:
        return None

    quality = _language_quality(parts[1:])
    if quality is None:
        return None
    return quality, language


def _language_quality(parameters: list[str]) -> float | None:
    quality = 1.0
    for parameter in parameters:
        parameter_name, separator, value = parameter.strip().partition("=")
        if separator and parameter_name.strip().lower() == "q":
            try:
                quality = float(value.strip())
            except ValueError:
                quality = 0.0
            break
    if not math.isfinite(quality) or not 0 < quality <= 1:
        return None
    return quality
