import re

UNSAFE_MEDICAL_PATTERNS = [
    re.compile(
        r"\b(?:you\s+have|sounds\s+like|diagnosed\s+with)\s+(?:tendonitis|bursitis|impingement|a\s+tear|sciatica)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:push|work|train)\s+through\s+the\s+(?:sharp\s+)?pain\b", re.IGNORECASE),
    re.compile(r"\b(?:take|prescribe|try)\s+(?:ibuprofen|nsaids?|painkillers?|advil)\b", re.IGNORECASE),
]

BANNED_LEAD_PATTERNS = [
    re.compile(
        r"^(?:sure(?:\s+thing)?|certainly|absolutely|of course|great question|happy to help)[!,\.]?\s*", re.IGNORECASE
    ),
    re.compile(r"^(?:here(?:'s| is) (?:the|your) (?:breakdown|answer|overview|explanation))[!:\.]?\s*", re.IGNORECASE),
    re.compile(r"^(?:as an ai(?: assistant)?|in terms of biomechanics)[!,\.]?\s*", re.IGNORECASE),
    re.compile(r"^(?:welcome back|let's dive (?:right )?in)[!,\.]?\s*", re.IGNORECASE),
]

BANNED_TRAIL_PATTERNS = [
    re.compile(r"(?:\r?\n|\s)*(?:hope (?:this|that) helps[!.]?)$", re.IGNORECASE),
    re.compile(
        r"(?:\r?\n|\s)*(?:keep crushing it|keep up the (?:great|hard) work|happy lifting|stay strong)[!.]?$",
        re.IGNORECASE,
    ),
    re.compile(r"(?:\r?\n|\s)*(?:let me know if you (?:have|need) any (?:other|more) questions)[!.]?$", re.IGNORECASE),
    re.compile(r"(?:\r?\n|\s)*(?:remember,? consistency is key)[!.]?$", re.IGNORECASE),
]


def scrub_coach_output(text: str) -> str:
    """Sanitizes generation by removing medical diagnostics and conversational padding."""
    if not text:
        return ""

    cleaned = text.strip()
    for pattern in UNSAFE_MEDICAL_PATTERNS:
        cleaned = pattern.sub("[Consult a sports physician regarding joint pain]", cleaned)

    for _ in range(3):
        prev = cleaned
        for pattern in BANNED_LEAD_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        for pattern in BANNED_TRAIL_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        if cleaned == prev:
            break

    return cleaned[0].upper() + cleaned[1:] if cleaned and cleaned[0].islower() else cleaned
