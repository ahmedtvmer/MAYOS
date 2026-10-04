"""Privacy-safe normalization for first-touch acquisition data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit
from typing import Any

from database.registry.accounts import FIRST_TOUCH_ACQUISITION_FIELDS


_UTM_VALUE = re.compile(r"[a-z0-9._-]{1,64}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def is_normalized_utm_label(label: Any) -> bool:
    return isinstance(label, str) and _UTM_VALUE.fullmatch(label) is not None


def is_normalized_referrer_host(host: Any) -> bool:
    return (
        isinstance(host, str)
        and len(host) <= 253
        and all(part and _HOST_LABEL.fullmatch(part) for part in host.split("."))
    )


def _utm_value(raw_label: Any) -> str | None:
    if not isinstance(raw_label, str):
        return None
    normalized_label = raw_label.strip().lower()
    return normalized_label if is_normalized_utm_label(normalized_label) else None


def _referrer_host(raw_referrer: Any) -> str | None:
    """Returns a hostname only, including when an untrusted URL was supplied."""
    if not isinstance(raw_referrer, str):
        return None
    candidate = raw_referrer.strip()
    if not candidate or len(candidate) > 2048:
        return None
    if "://" not in candidate:
        candidate = f"//{candidate}"
    try:
        parsed = urlsplit(candidate)
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return None
    if is_normalized_referrer_host(host):
        return host
    return None


def normalize_first_touch(payload: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Returns only catalogue-safe fields; raw URLs and invalid labels are dropped."""
    payload = payload or {}
    return {
        "utm_source": _utm_value(payload.get("utm_source")),
        "utm_medium": _utm_value(payload.get("utm_medium")),
        "utm_campaign": _utm_value(payload.get("utm_campaign")),
        "referrer_host": _referrer_host(payload.get("referrer_host")),
    }


def first_touch_person_properties(first_touch: Mapping[str, str | None]) -> dict[str, str]:
    """Returns populated values for the set-once PostHog person update."""
    return {
        key: value
        for key in FIRST_TOUCH_ACQUISITION_FIELDS
        if (value := first_touch.get(key)) is not None
    }
