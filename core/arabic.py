"""Arabic letter-form matching shared by lexical guards and food search."""

_ARABIC_TRANSLATION = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه",
    **{chr(codepoint): None for codepoint in (*range(0x064B, 0x0660), 0x0670, 0x0640)},
})


def normalize_arabic_text(text: str) -> str:
    return text.translate(_ARABIC_TRANSLATION)
