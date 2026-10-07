"""Android app build policy configuration and request-header parsing."""

import os
import re

DEFAULT_ANDROID_STORE_URL = (
    "https://play.google.com/store/apps/details?id=com.mayos.mayos_mobile"
)
ANDROID_BUILD_HEADER = "X-MAYOS-Build"
_INTEGER_HEADER = re.compile(r"^[0-9]+$")
_NONNEGATIVE_SETTING = re.compile(r"^\+?[0-9]+$")
_CLIENT_HEADER = re.compile(r"^(android|web)/([0-9][0-9A-Za-z.+_-]{0,31})$")


def minimum_android_build() -> int:
    """Returns the configured minimum build, treating bad values as disabled."""
    raw = os.getenv("MIN_ANDROID_BUILD", "0").strip()
    if not _NONNEGATIVE_SETTING.fullmatch(raw):
        return 0
    return int(raw)


def android_store_url() -> str:
    """Returns the Play Store URL shown to clients that need an update."""
    return os.getenv("ANDROID_STORE_URL", DEFAULT_ANDROID_STORE_URL).strip() or DEFAULT_ANDROID_STORE_URL


def parse_android_build(header_value: str | None) -> int | None:
    """Parses a decimal Android versionCode; malformed headers act as absent."""
    if header_value is None:
        return None
    raw = header_value.strip()
    if not _INTEGER_HEADER.fullmatch(raw):
        return None
    return int(raw)


def parse_client_header(client_header: str | None) -> tuple[str, str] | None:
    """Parses the canonical platform/version value sent by the apps."""
    if not client_header:
        return None
    match = _CLIENT_HEADER.fullmatch(client_header.strip())
    return match.groups() if match is not None else None


def is_web_client(client_header: str | None) -> bool:
    """Recognizes a valid web platform/version value from ``X-MAYOS-Client``."""
    parsed = parse_client_header(client_header)
    return parsed is not None and parsed[0] == "web"
