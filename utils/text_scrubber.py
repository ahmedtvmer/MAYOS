import re

# 1. Acute Medical / Diagnostic Assertions
UNSAFE_MEDICAL_PATTERNS = [
    re.compile(r"\b(?:you\s+have|sounds\s+like|diagnosed\s+with)\s+(?:tendonitis|bursitis|impingement|a\s+tear|sciatica)\b", re.IGNORECASE),
    re.compile(r"\b(?:push|work|train)\s+through\s+the\s+(?:sharp\s+)?pain\b", re.IGNORECASE),
    re.compile(r"\b(?:take|prescribe|try)\s+(?:ibuprofen|nsaids?|painkillers?|advil)\b", re.IGNORECASE),
]

# 2. Conversational Lead Boilerplate
BANNED_LEAD_PATTERNS = [
    re.compile(r"^(?:sure(?:\s+thing)?|certainly|absolutely|of course|great question|happy to help)[!,\.]?\s*", re.IGNORECASE),
    re.compile(r"^(?:here(?:'s| is) (?:the|your) (?:breakdown|answer|overview|explanation))[!:\.]?\s*", re.IGNORECASE),
    re.compile(r"^(?:as an ai(?: assistant)?|in terms of biomechanics)[!,\.]?\s*", re.IGNORECASE),
    re.compile(r"^(?:welcome back|let's dive (?:right )?in)[!,\.]?\s*", re.IGNORECASE)
]

# 3. Conversational Trail Boilerplate (handles preceding newlines)
BANNED_TRAIL_PATTERNS = [
    re.compile(r"(?:\r?\n|\s)*(?:hope (?:this|that) helps[!.]?)$", re.IGNORECASE),
    re.compile(r"(?:\r?\n|\s)*(?:keep crushing it|keep up the (?:great|hard) work|happy lifting|stay strong)[!.]?$", re.IGNORECASE),
    re.compile(r"(?:\r?\n|\s)*(?:let me know if you (?:have|need) any (?:other|more) questions)[!.]?$", re.IGNORECASE),
    re.compile(r"(?:\r?\n|\s)*(?:remember,? consistency is key)[!.]?$", re.IGNORECASE)
]


def scrub_coach_output(text: str) -> str:
    """
    Sanitizes LLM generation:
    1. Neutralizes dangerous clinical/medical advice.
    2. Iteratively removes leading pleasantries and meta-announcements.
    3. Iteratively strips trailing motivational sign-offs.
    4. Restores proper initial sentence capitalization.
    """
    if not text:
        return ""

    cleaned = text.strip()

    # Step 1: Neutralize medical assertions
    for pattern in UNSAFE_MEDICAL_PATTERNS:
        cleaned = pattern.sub("[Consult a sports physician regarding joint pain]", cleaned)

    # Step 2: Loop to handle stacked leading pleasantries
    changed = True
    while changed:
        changed = False
        for pattern in BANNED_LEAD_PATTERNS:
            new_text = pattern.sub("", cleaned).strip()
            if new_text != cleaned:
                cleaned = new_text
                changed = True

    # Step 3: Loop to handle stacked trailing sign-offs
    changed = True
    while changed:
        changed = False
        for pattern in BANNED_TRAIL_PATTERNS:
            new_text = pattern.sub("", cleaned).strip()
            if new_text != cleaned:
                cleaned = new_text
                changed = True

    # Step 4: Ensure first character remains capitalized
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned