# agent/telemetry_reconciler.py
import re

RE_HISTORICAL_INDICATORS = re.compile(
    r"\b("
    r"yesterday|last\s+(?:workout|session|week|month)|"
    r"this\s+(?:week|month)|"
    r"past\s+\d+\s+sessions?|"
    r"between\s+\w+\s+and\s+\w+|"
    r"did\s+i\s+(?:hit|lift|do|complete)|"
    r"what\s+weight\s+did\s+i|"
    r"how\s+did\s+my|"
    r"did\s+my\s+.+?\s+(?:improve|advance)|"
    r"how\s+much\s+did\s+my\s+.+?\s+advance|"
    r"why\s+was\s+my\s+rpe\s+so\s+high|"
    r"compare\s+my|"
    r"my\s+(?:e1rm|performance|sets|top\s+set|reps)"
    r")\b",
    re.IGNORECASE,
)

ENTITY_EXTRACTION_PATTERNS = [
    re.compile(
        r"(?:how\s+did\s+my|did\s+my|compare\s+my)\s+(?P<ex>.+?)\s+(?:look|improve|advance|performance|e1rm|top\s+set|between|compared|\?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:on|for|in|with)\s+(?P<ex>[a-zA-Z0-9\s\-]+?)(?:\s+(?:yesterday|last|this|today|\?|$))",
        re.IGNORECASE,
    ),
    re.compile(r"how\s+much\s+did\s+my\s+(?P<ex>.+?)\s+(?:top\s+set|advance|improve|\?)", re.IGNORECASE),
]

STOP_WORDS = {
    "my", "the", "a", "an", "all", "prescribed", "sets", "set", "reps",
    "workout", "session", "yesterday", "performance", "top", "e1rm", "rpe",
}

STANCE_MODIFIERS = {
    "assisted", "standing", "seated", "lying", "incline", "decline", "flat",
    "machine", "cable", "barbell", "dumbbell", "lever", "plate", "weighted",
    "neutral", "grip", "wide", "close", "single", "arm", "leg",
}


def clean_extracted_entity(raw_entity: str) -> str:
    tokens = [w for w in re.findall(r"\w+", raw_entity.lower()) if w not in STOP_WORDS]
    return " ".join(tokens).strip()


def clean_movement_stem(name: str) -> str:
    tokens = re.findall(r"\w+", name.lower())
    core = [t for t in tokens if t not in STANCE_MODIFIERS]
    return " ".join(core) if core else name.lower()


def exercise_exists_in_telemetry(entity: str, telemetry: str) -> bool:
    if not entity or not telemetry:
        return False

    t_lower = telemetry.lower()
    if entity in t_lower:
        return True

    entity_tokens = set(entity.split())
    for line in t_lower.split("\n"):
        line_tokens = set(re.findall(r"\w+", line))
        if "dumbbell" in entity_tokens and "barbell" in line_tokens and "dumbbell" not in line_tokens:
            continue
        if "barbell" in entity_tokens and "dumbbell" in line_tokens and "barbell" not in line_tokens:
            continue

        intersection = entity_tokens.intersection(line_tokens)
        if len(entity_tokens) > 0 and (len(intersection) / len(entity_tokens)) >= 0.75:
            return True

    return False


def reconcile_telemetry_query(query: str, telemetry: str) -> str | None:
    """Reconciles historical training queries against the telemetry ledger."""
    if not RE_HISTORICAL_INDICATORS.search(query):
        return None

    t_clean = telemetry.strip() if telemetry else ""

    if "baseline" in t_clean.lower() or "no recorded sessions" in t_clean.lower():
        return "Baseline loads are currently being established; no historical comparison data exists in your ledger."

    set_query_match = re.search(
        r"complete(?:d)?\s+(?:all\s+)?(?P<claimed>\d+)?\s*(?:prescribed\s+)?sets",
        query,
        re.IGNORECASE,
    )
    if set_query_match:
        logged_sets_match = re.search(r"(\d+)\s+sets?\s+logged", t_clean, re.IGNORECASE)
        if logged_sets_match:
            actual_count = logged_sets_match.group(1)
            return f"Your session log records exactly {actual_count} completed sets for this movement."

        set_count = len(re.findall(r"\bSet\s+\d+:", t_clean, re.IGNORECASE))
        if set_count > 0:
            return f"Your session log records exactly {set_count} completed sets for this movement."

    extracted_target = None
    for pattern in ENTITY_EXTRACTION_PATTERNS:
        match = pattern.search(query)
        if match:
            candidate = match.group("ex").strip()
            cleaned = clean_extracted_entity(candidate)
            if cleaned:
                extracted_target = cleaned
                break

    if extracted_target:
        if not exercise_exists_in_telemetry(extracted_target, t_clean):
            return f"No log entry exists for {extracted_target} in your logged session history."

    return None
