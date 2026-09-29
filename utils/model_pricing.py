"""Per-model hosted-inference pricing for usage metering (ADR 038).

Prices are USD per 1,000,000 tokens and are **DeepInfra Standard-tier list
prices**, not a provider contract: ``MODEL_PRICING_JSON`` (a JSON object mapping
model id to ``{"input": <usd>, "output": <usd>}``) overrides them per
deployment. An unknown model meters its tokens at cost 0 and logs one warning
per model, so a new hosted variant can never silently break metering (it only
under-reports until priced).
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

#: USD per 1M tokens for the configured default hosted models: DeepInfra
#: Standard-tier list prices checked 2026-09-29. ``MODEL_PRICING_JSON`` can
#: override them per deployment. ``cost_usd`` is fixed when each row is
#: written, so a price change only affects rows written after it.
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "Qwen/Qwen3.5-9B": {"input": 0.10, "output": 0.15},
    "Qwen/Qwen3.5-27B": {"input": 0.26, "output": 2.60},
}

#: Models already warned about, so an unpriced model does not spam the log.
_warned_unknown: set[str] = set()


def _parse_pricing_json(raw: str) -> dict[str, dict[str, float]]:
    """Parses ``MODEL_PRICING_JSON``; malformed entries are dropped, never fatal."""
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        logger.warning("Ignoring MODEL_PRICING_JSON (%s): %s", type(exc).__name__, exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("Ignoring MODEL_PRICING_JSON: must be a JSON object.")
        return {}
    pricing: dict[str, dict[str, float]] = {}
    for model, entry in parsed.items():
        if not isinstance(entry, dict):
            continue
        try:
            pricing[str(model)] = {"input": float(entry["input"]), "output": float(entry["output"])}
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring MODEL_PRICING_JSON entry for %r (needs numeric input/output).", model)
    return pricing


def load_pricing() -> dict[str, dict[str, float]]:
    """Defaults overlaid with any valid ``MODEL_PRICING_JSON`` overrides."""
    pricing = {model: dict(entry) for model, entry in DEFAULT_MODEL_PRICING.items()}
    raw = os.getenv("MODEL_PRICING_JSON", "").strip()
    if raw:
        pricing.update(_parse_pricing_json(raw))
    return pricing


def price_for(model: str, pricing: dict[str, dict[str, float]] | None = None) -> dict[str, float] | None:
    """Returns ``{"input", "output"}`` for ``model``, or ``None`` when unpriced.

    Local GGUF models (``local:*``) are intentionally cost 0 and never warned.
    """
    if model.startswith("local:"):
        return {"input": 0.0, "output": 0.0}
    table = pricing if pricing is not None else load_pricing()
    entry = table.get(model)
    if entry is None:
        if model not in _warned_unknown:
            _warned_unknown.add(model)
            logger.warning("No pricing configured for model %r; metering its cost as $0.", model)
        return None
    return entry


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, dict[str, float]] | None = None,
) -> float:
    """USD cost for one call; 0.0 for an unknown model (tokens are still metered)."""
    entry = price_for(model, pricing)
    if entry is None:
        return 0.0
    return (max(0, int(input_tokens)) / 1_000_000.0) * entry["input"] + (
        max(0, int(output_tokens)) / 1_000_000.0
    ) * entry["output"]
