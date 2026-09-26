"""Android App Link association: builds ``/.well-known/assetlinks.json`` from env.

The statement proves domain ownership so Android can open the reset link
directly in the installed app (ADR 037). Configuration is env-driven so a
deployment sets its own signing fingerprints without a code change.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

DEFAULT_ANDROID_PACKAGE = "com.mayos.mayos_mobile"
_HEX64 = re.compile(r"^[0-9A-F]{64}$")


def android_package() -> str:
    package = os.getenv("ANDROID_APP_PACKAGE", DEFAULT_ANDROID_PACKAGE).strip()
    return package or DEFAULT_ANDROID_PACKAGE


def normalize_fingerprint(value: str) -> str | None:
    """Normalises one SHA-256 fingerprint, or returns ``None`` when invalid.

    Accepts upper/lower case and colons or no separators; emits the canonical
    uppercase, colon-separated 32-byte form Android expects
    (``AA:BB:…`` — 64 hex digits in 32 pairs). Anything else is invalid.
    """
    if not isinstance(value, str):
        return None
    hex_digits = value.replace(":", "").strip().upper()
    if not _HEX64.match(hex_digits):
        return None
    return ":".join(hex_digits[i : i + 2] for i in range(0, 64, 2))


def android_cert_fingerprints() -> list[str]:
    """Normalised fingerprints from ``ANDROID_APP_SHA256_CERT_FINGERPRINTS``.

    Invalid entries are skipped with a warning (fingerprints are public, so a
    warning leaks nothing); duplicates are dropped in first-seen order.
    """
    raw = os.getenv("ANDROID_APP_SHA256_CERT_FINGERPRINTS", "")
    normalized: list[str] = []
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        normalized_entry = normalize_fingerprint(entry)
        if normalized_entry is None:
            logger.warning("Ignoring invalid Android cert fingerprint entry %r", entry)
            continue
        if normalized_entry not in normalized:
            normalized.append(normalized_entry)
    return normalized


def build_asset_links() -> list[dict[str, object]] | None:
    """The Digital Asset Links statement, or ``None`` when unconfigured.

    ``None`` (and a 404 at the route) is deliberate: a statement with an empty
    fingerprint list is invalid and would fail App Link verification on every
    install, so an unconfigured service must not serve one.
    """
    fingerprints = android_cert_fingerprints()
    if not fingerprints:
        return None
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": android_package(),
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]
