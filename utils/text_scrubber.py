import re
import regex as partial_regex

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


_PARTIAL_UNSAFE_PATTERNS = tuple(
    partial_regex.compile(pattern.pattern, pattern.flags) for pattern in UNSAFE_MEDICAL_PATTERNS
)
_PARTIAL_LEAD_PATTERNS = tuple(
    partial_regex.compile(pattern.pattern, pattern.flags) for pattern in BANNED_LEAD_PATTERNS
)
_PARTIAL_TRAIL_PATTERNS = tuple(
    partial_regex.compile(pattern.pattern, pattern.flags) for pattern in BANNED_TRAIL_PATTERNS
)
_TRAIL_CONTINUATION_PATTERNS = tuple(
    re.compile(pattern.pattern.removesuffix("$"), pattern.flags) for pattern in BANNED_TRAIL_PATTERNS
)


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
        # A guarded prefix historically kept one scrub segment open to its sentence boundary.
        self.guarded_segment = False
        self.guarded_segment_cleaned = False

    def _clean(self, text: str) -> str:
        leading_patterns = () if self.guarded_segment_cleaned else BANNED_LEAD_PATTERNS
        cleaned = _scrub_segment(text, capitalize=not self.started, leading_patterns=leading_patterns)
        if not cleaned:
            return ""
        prefix = re.sub(r"\n{3,}", "\n\n", self.spacing) if self.started else ""
        self.spacing = text[len(text.rstrip()):]
        self.started = True
        if self.guarded_segment:
            self.guarded_segment_cleaned = True
        return prefix + cleaned

    def _possible_pattern_start(self, patterns):
        for start in range(len(self.buffer)):
            if self._matches_pattern_suffix(patterns, self.buffer[start:]):
                return start
        return None

    @staticmethod
    def _matches_pattern_suffix(patterns, suffix):
        return any(
            (match := pattern.fullmatch(suffix, partial=True)) is not None and match.end() == len(suffix)
            for pattern in patterns
        )

    def _possible_opening_start(self):
        text = self.buffer.lstrip()
        offset = len(self.buffer) - len(text)
        return offset if self._matches_pattern_suffix(_PARTIAL_LEAD_PATTERNS, text) else None

    def _possible_trail_start(self):
        for start in range(len(self.buffer)):
            suffix = self.buffer[start:]
            skipped = len(suffix) - len(suffix.lstrip())
            suffix = suffix[skipped:]
            if not suffix:
                continue
            start += skipped
            if self._matches_pattern_suffix(_PARTIAL_TRAIL_PATTERNS, suffix):
                return start
            trimmed = suffix.rstrip()
            if trimmed != suffix and self._complete_pattern_match(_PARTIAL_TRAIL_PATTERNS, trimmed):
                return start
        return None

    @staticmethod
    def _complete_pattern_match(patterns, text):
        return any(
            (match := pattern.fullmatch(text, partial=True)) is not None
            and not match.partial
            and match.end() == len(text)
            for pattern in patterns
        )

    def _guard_start(self):
        starts = [
            self._possible_pattern_start(_PARTIAL_UNSAFE_PATTERNS),
            self._possible_opening_start(),
            self._possible_trail_start(),
        ]
        prefix = self.GUARDED_PREFIX.match(self.buffer)
        if prefix is not None and not self.buffer[prefix.end():].strip():
            starts.append(0)
        starts = [start for start in starts if start is not None]
        return min(starts) if starts else None

    def _unfinished_trail_start(self):
        starts = []
        for pattern in _TRAIL_CONTINUATION_PATTERNS:
            for match in pattern.finditer(self.buffer):
                suffix = self.buffer[match.end():]
                if suffix.strip() and not re.search(r"\S+\s+", suffix):
                    starts.append(match.start())
        return min(starts) if starts else None

    def _word_ends(self, limit: int):
        ends = []
        cursor = 0
        while cursor < limit:
            word = re.match(r"\s*\S+\s+", self.buffer[cursor:limit])
            if not word:
                break
            cursor += word.end()
            ends.append(cursor)
        return ends

    def _expand_unsafe_matches(self, end: int, word_ends):
        while end:
            expanded = end
            for pattern in UNSAFE_MEDICAL_PATTERNS:
                for match in pattern.finditer(self.buffer):
                    if match.start() < end < match.end():
                        next_end = next((word_end for word_end in word_ends if word_end >= match.end()), None)
                        if next_end is None:
                            return 0
                        expanded = max(expanded, next_end)
            if expanded == end:
                return end
            end = expanded
        return 0

    def _release_end(self, limit=None):
        guard_start = self._guard_start()
        safe_limit = len(self.buffer) if guard_start is None else guard_start
        trail_start = self._unfinished_trail_start()
        if trail_start is not None:
            safe_limit = min(safe_limit, trail_start)
        if limit is not None:
            safe_limit = min(safe_limit, limit)
        word_ends = self._word_ends(safe_limit)
        if not word_ends:
            return 0
        end = word_ends[-1]
        lead_end = self._opening_match_end()
        if lead_end is not None and lead_end < len(self.buffer):
            safe_lead_end = next((word_end for word_end in word_ends if word_end >= lead_end), None)
            if safe_lead_end is not None:
                end = max(end, safe_lead_end)
        return self._expand_unsafe_matches(end, word_ends)

    def _opening_match_end(self):
        leading_text = self.buffer.lstrip()
        offset = len(self.buffer) - len(leading_text)
        for pattern in BANNED_LEAD_PATTERNS:
            match = pattern.match(leading_text)
            if match is not None:
                return match.end() + offset
        return None

    def _drain(self, final: bool = False) -> str:
        output = []
        while self.buffer:
            boundary = re.search(r"[.!?](?=\s)", self.buffer)
            forced_boundary = False
            if boundary:
                end = boundary.end()
            elif final:
                end = len(self.buffer)
            else:
                if self.GUARDED_PREFIX.search(self.buffer):
                    self.guarded_segment = True
                limit = self.MAX_BUFFER - 128 if len(self.buffer) >= self.MAX_BUFFER else None
                end = self._release_end(limit)
                if not end and limit is not None:
                    end = self._release_end()
                if not end:
                    break
                forced_boundary = limit is not None
            segment, self.buffer = self.buffer[:end], self.buffer[end:]
            if self.started:
                self.spacing += segment[:len(segment) - len(segment.lstrip())]
            output.append(self._clean(segment))
            if boundary or forced_boundary:
                self.guarded_segment = False
                self.guarded_segment_cleaned = False
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


def _scrub_segment(text: str, capitalize: bool = True, leading_patterns=None) -> str:
    """Sanitizes generation by removing medical diagnostics and conversational padding."""
    if not text:
        return ""

    if leading_patterns is None:
        leading_patterns = BANNED_LEAD_PATTERNS
    cleaned = text.strip()
    for pattern in UNSAFE_MEDICAL_PATTERNS:
        cleaned = pattern.sub("[Consult a sports physician regarding joint pain]", cleaned)

    while True:
        prev = cleaned
        for pattern in leading_patterns:
            cleaned = pattern.sub("", cleaned).strip()
        for pattern in BANNED_TRAIL_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        if cleaned == prev:
            break

    return cleaned[0].upper() + cleaned[1:] if capitalize and cleaned and cleaned[0].islower() else cleaned
