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


EMPTY_RESPONSE_FALLBACK = "I couldn't produce a clear answer. Could you rephrase your question?"
PIPELINE_ERROR_RESPONSE = "I couldn't complete that request. Please try again."


class CoachOutputScrubber:
    MAX_BUFFER = 512
    CONTROL_TOKENS = ("<think>", "</think>", "<|im_end|>", "<|eot_id|>", "<|end|>", "<|endoftext|>", "</s>", "[end]")
    GUARDED_PREFIX = re.compile(
        r"^\s*(?:you|sounds|diagnosed|push|work|train|take|prescribe|try|"
        r"sure|certainly|absolutely|of|great|happy|here|as|in|welcome|let|let's|"
        r"hope|keep|stay|remember)\b", re.IGNORECASE,
    )

    def __init__(self):
        self.control = ""
        self.buffer = ""
        self.thinking = 0
        self.stopped = False
        self.started = False
        self.spacing = ""

    def _clean(self, text: str) -> str:
        cleaned = _scrub_segment(text, capitalize=not self.started)
        if not cleaned:
            return ""
        prefix = re.sub(r"\n{3,}", "\n\n", self.spacing) if self.started else ""
        self.spacing = text[len(text.rstrip()):]
        self.started = True
        return prefix + cleaned

    def _drain(self, final: bool = False) -> str:
        output = []
        while self.buffer:
            boundary = re.search(r"[.!?](?=\s)", self.buffer)
            if boundary:
                end = boundary.end()
            elif len(self.buffer) >= self.MAX_BUFFER:
                end = self.MAX_BUFFER - 128
                space = self.buffer.rfind(" ", 0, end)
                if space > 0:
                    end = space + 1
                for pattern in UNSAFE_MEDICAL_PATTERNS:
                    for match in pattern.finditer(self.buffer):
                        if match.start() < end < match.end():
                            end = match.start() or match.end()
            elif final:
                end = len(self.buffer)
            elif not self.GUARDED_PREFIX.search(self.buffer):
                word = re.match(r"\s*\S+\s+", self.buffer)
                if not word:
                    break
                end = word.end()
            else:
                break
            segment, self.buffer = self.buffer[:end], self.buffer[end:]
            if self.started:
                self.spacing += segment[:len(segment) - len(segment.lstrip())]
            output.append(self._clean(segment))
        return "".join(output)

    def feed(self, text: str) -> str:
        output = []
        for char in text:
            if self.stopped:
                break
            self.control += char
            while self.control:
                lowered = self.control.lower()
                if lowered in self.CONTROL_TOKENS:
                    if lowered == "<think>":
                        self.thinking += 1
                    elif lowered == "</think>":
                        self.thinking = max(0, self.thinking - 1)
                    else:
                        self.stopped = True
                    self.control = ""
                    break
                if any(token.startswith(lowered) for token in self.CONTROL_TOKENS):
                    break
                if not self.thinking:
                    self.buffer += self.control[0]
                    output.append(self._drain())
                self.control = self.control[1:]
        return "".join(output)

    def finish(self) -> str:
        self.control = ""
        return self._drain(final=True)


def scrub_coach_output(text: str) -> str:
    scrubber = CoachOutputScrubber()
    return scrubber.feed(text or "") + scrubber.finish()


def finalize_coach_output(text: str) -> str:
    return scrub_coach_output(text) or EMPTY_RESPONSE_FALLBACK


def _scrub_segment(text: str, capitalize: bool = True) -> str:
    """Sanitizes generation by removing medical diagnostics and conversational padding."""
    if not text:
        return ""

    cleaned = text.strip()
    for pattern in UNSAFE_MEDICAL_PATTERNS:
        cleaned = pattern.sub("[Consult a sports physician regarding joint pain]", cleaned)

    while True:
        prev = cleaned
        for pattern in BANNED_LEAD_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        for pattern in BANNED_TRAIL_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        if cleaned == prev:
            break

    return cleaned[0].upper() + cleaned[1:] if capitalize and cleaned and cleaned[0].islower() else cleaned
