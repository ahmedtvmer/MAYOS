"""Deterministic goal-text suggestions for the Weak point vocabulary."""

import re
import unicodedata

from core.weak_points import WEAK_POINT_MUSCLES


# Specific phrases precede broad terms so upper chest and side delts stay
# distinct from chest and shoulders.
WEAK_POINT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("upper_chest", ("upper chest", "upper pecs", "أعلى الصدر", "الجزء العلوي من الصدر")),
    ("side_delts", ("side delts", "lateral delts", "side shoulders", "الأكتاف الجانبية", "الكتف الجانبي", "كتف جانبي")),
    ("chest", ("chest", "chests", "pec", "pecs", "صدر", "الصدر", "صدري", "صدور")),
    ("lats", ("lats", "lat", "latissimus dorsi", "back", "backs", "ظهر", "الظهر", "ضهر", "ضهري", "الظهر العريض", "لاتس", "اللاتس")),
    ("traps", ("traps", "trap", "trapezius", "upper trapezius", "mid trapezius", "middle trapezius", "lower trapezius", "upper traps", "mid traps", "middle traps", "lower traps", "rhomboids", "rhomboid", "upper back", "upper-back", "mid back", "mid-back", "middle back", "middle-back", "الترابيس", "ترابيس", "العضلات المعينية")),
    ("shoulders", ("shoulder", "shoulders", "كتف", "كتفي", "كتافي", "كتاف", "الأكتاف", "الأكتفين", "الكتفين")),
    ("biceps", ("biceps", "bicep", "arms", "arm", "بايسبس", "البايسبس", "عضلة الذراع", "دراع", "دراعي", "دراعات", "دراعاتي", "ذراع", "ذراعي")),
    ("triceps", ("triceps", "tricep", "arms", "arm", "ترايسبس", "الترايسبس", "دراع", "دراعي", "دراعات", "دراعاتي", "ذراع", "ذراعي")),
    ("forearms", ("forearms", "forearm", "ساعد", "الساعد", "الساعدين")),
    ("quads", ("quads", "quadriceps", "quad", "الفخذ الأمامي", "عضلات الفخذ الأمامية")),
    ("hamstrings", ("hamstrings", "hamstring", "الفخذ الخلفي", "عضلات الفخذ الخلفية")),
    ("glutes", ("glutes", "glute", "butt", "الأرداف", "المؤخرة", "مؤخرتي", "عضلات المؤخرة")),
    ("adductors", ("adductors", "adductor", "المقربات", "العضلات المقربة")),
    ("calves", ("calves", "calf", "السمانة", "بطة الساق")),
    ("abs", ("abs", "abdominal", "abdominals", "بطن", "البطن", "بطني")),
)
_WORD = r"\w"
_INJURY_WORDS = re.compile(
    r"\b(?:pain|hurts?|aches?|aching|sore|injur(?:y|ed)|strains?|strained|"
    r"tweaks?|tweaked|surgery|rehab)\b|(?:ألم|وجع|بيوجعني|إصابة|مصاب|شد)"
)
_BACK_IDIOM = re.compile(
    r"\b(?:get\s+)?back\s+(?:in\s+shape|to\s+the\s+gym|to\s+my\s+old\s+weight|on\s+track)\b|"
    r"\b(?:come|bounce)\s+back\b|\bback\s+to\s+the\s+gym\b"
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def suggest_weak_points(goal_text: str | None) -> list[str]:
    """Return named Weak point keys in first-mention order, without broad legs."""
    if not isinstance(goal_text, str) or not goal_text.strip():
        return []
    text = _normalize(goal_text)
    text = _BACK_IDIOM.sub(lambda match: " " * len(match.group()), text)
    matches: list[tuple[int, int, str]] = []
    aliases: list[tuple[int, int, str]] = []
    for muscle, words in WEAK_POINT_ALIASES:
        for word in words:
            normalized = _normalize(word)
            forms = (normalized, "و" + normalized) if "\u0600" <= normalized[0] <= "\u06ff" else (normalized,)
            for form in forms:
                for match in re.finditer(rf"(?<!{_WORD}){re.escape(form)}(?!{_WORD})", text):
                    start = match.start() + (1 if form != normalized else 0)
                    aliases.append((start, match.end(), muscle))
    # Resolve overlapping aliases by longest phrase at each starting position.
    for start, end, muscle in sorted(aliases, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(
            start < prior_end and end > prior_start
            and (start, end) != (prior_start, prior_end)
            for prior_start, prior_end, _ in matches
        ):
            continue
        matches.append((start, end, muscle))
    # A symptom suppresses nearby muscles in its clause. A clear growth goal
    # before the muscle mention remains actionable ("bigger shoulders after
    # my injury healed").
    clauses = re.split(r"[.!?؟،؛;\n]+", text)
    clause_ranges: list[tuple[int, int, str]] = []
    offset = 0
    for clause in clauses:
        clause_ranges.append((offset, offset + len(clause), clause))
        offset += len(clause) + 1
    result: list[str] = []
    for start, end, muscle in sorted(matches):
        clause = next((part for left, right, part in clause_ranges if left <= start < right), "")
        relative_start = start - next((left for left, right, _ in clause_ranges if left <= start < right), start)
        if _INJURY_WORDS.search(clause):
            growth_before = re.search(r"\b(?:grow|bigger|build|increase|أكبر|اكبر)\b[^.؟!،؛]*$", clause[:relative_start])
            if growth_before is None:
                continue
        if muscle not in result:
            result.append(muscle)
    return [muscle for muscle in result if muscle in WEAK_POINT_MUSCLES]


def suggest_weak_points_for_goals(
    current_goal: str | None, long_term_goal: str | None
) -> list[str]:
    return list(dict.fromkeys(
        suggest_weak_points(current_goal) + suggest_weak_points(long_term_goal)
    ))
