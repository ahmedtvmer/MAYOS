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

    set_query_match = re.fullmatch(
        r"\s*did\s+i\s+complete\s+(?:all\s+)?(?:\d+\s+)?(?:prescribed\s+)?sets"
        r"(?:\s+(?:for|on)\s+(?P<exercise>[\w -]+?))?"
        r"\s+(?:in\s+)?(?:my\s+)?last\s+(?:session|workout)\s*[?.!]?\s*",
        query,
        re.IGNORECASE,
    )
    if not set_query_match:
        return None

    last_sessions = re.findall(r"^Last Session:\s*([^\n]+)", telemetry or "", re.IGNORECASE | re.MULTILINE)
    if len(last_sessions) != 1:
        return None

    exercise = set_query_match.group("exercise")
    target = " ".join(exercise.lower().split()) if exercise else None
    counts = []
    for field in last_sessions[0].split("|"):
        count_match = re.fullmatch(
            r"\s*(?:(?P<exercise>[\w -]+):\s*)?(?P<count>\d+)\s+sets?\s+logged\s*",
            field,
            re.IGNORECASE,
        )
        if not count_match:
            continue
        movement = count_match.group("exercise")
        movement = " ".join(movement.lower().split()) if movement else None
        if movement == target:
            counts.append(int(count_match.group("count")))
    if len(counts) != 1:
        return None
    scope = f"for {exercise} in your last session" if exercise else "across your last session"
    return f"Your session log records exactly {counts[0]} completed sets {scope}."
