"""One definition of a truthy environment flag.

Every configuration switch in the repo asks this question; keeping the answer
in one place means ``1/true/yes/on`` behave identically for the inference
mock switches, the SMTP toggle, and the coach-AI feature flag.
"""

from __future__ import annotations

import os

TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_flag(name: str, default: bool = False) -> bool:
    """Reads ``name`` as a boolean; an unset variable yields ``default``."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


__all__ = ["TRUTHY", "env_flag"]
