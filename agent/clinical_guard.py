# agent/clinical_guard.py
import os
import re
import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip("'\"")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu").strip("'\"")

EMBED_MODEL = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL_NAME,
    model_kwargs={"device": MODEL_DEVICE},
    encode_kwargs={"normalize_embeddings": True},
)

RE_BENIGN_FATIGUE = re.compile(
    r"\b(fatigue|fatigued|tired|exhaustion|exhausted|sluggish|lethargic|drained|wiped|"
    r"run[\s-]?down|sore|soreness|burn|burning|pump|systemic\s+fatigue)\b"
    r"|\blow\s+readiness\b"
    r"|\breadiness\s*(?:is|at|:)?\s*[12]\s*/\s*5\b",
    re.IGNORECASE,
)
RE_TRAUMA_SENSATIONS = re.compile(
    r"\b(tear|tearing|ripping|pins\s+and\s+needles|tingling|numb|numbness|electric|shock|glass|loose|slipping|crunching|grinding|giving\s+way|impingement|sharp|pop|popping|dislocat|hernia)\b",
    re.IGNORECASE,
)
#: Symptom words that must keep the benign-fatigue bypass closed. Body-part nouns
#: (knee, shoulder, joint) are deliberately excluded: "every joint feels cold and
#: sluggish" is systemic fatigue, not an injury. Fail-closed on pain/neural signs.
RE_ACUTE_PAIN_SIGNALS = re.compile(
    r"\b(pain|painful|hurts?|aching|ache|sharp|shooting|radiat(?:ing|es|ed)|numb|numbness|"
    r"tingling|pins\s+and\s+needles|pop(?:ping|ped)?|tear(?:ing|s)?|torn|tore|ripping|"
    r"grinding|clicking|pinch(?:ed)?|crunch(?:ing)?|dislocat\w*|impingement|giving\s+way|"
    r"electric|shock|glass|swollen|swelling|unstable|instability)\b",
    re.IGNORECASE,
)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculates cosine similarity between two dense embedding vectors."""
    if not v1 or not v2:
        return 0.0
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


CLINICAL_ANCHOR_DESCRIPTIONS: list[str] = [
    "Felt like velcro tearing or ripping deep inside the muscle fiber during the stretch.",
    "Pins and needles, tingling, or ice cold sensation radiating into fingers or extremities.",
    "Deep searing pain, hot glass sensation, or sharp electric shock inside the joint capsule.",
    "Joint feels loose, unstable, or like the bone is slipping out of its socket.",
    "Dull, persistent toothache-like gnawing ache deep inside the bone or hip capsule.",
    "Audible crunching, grinding, or loud clicking accompanied by immediate joint weakness.",
    "Sudden loss of motor control, limb giving way, or unable to bear load.",
    "Sharp structural joint impingement followed by immediate loss of tension and localized swelling.",
]

CLINICAL_ANCHOR_VECTORS: list[list[float]] = [
    EMBED_MODEL.embed_query(desc) for desc in CLINICAL_ANCHOR_DESCRIPTIONS
]


_CLINICAL_LEXICAL_TOKENS = re.compile(
    r"\b(pain|hurt|ache|aching|sharp|pop|popping|tear|tearing|torn|tore|numb|numbness|tingling|"
    r"joint|shoulder|knee|elbow|hip|wrist|pec|tendon|disc|spine|hernia|swollen|swell|swelling|"
    r"shooting|radiating|grinding|clicking|pinch|pinched|crunch|crunching|dislocat|impingement|"
    r"glass|giving\s+way|loose|slipping|electric|shock|ripping)\b",
    re.IGNORECASE,
)


def evaluate_clinical_semantic_guard(query: str, threshold: float = 0.70) -> tuple[bool, float]:
    has_acute_signal = bool(RE_TRAUMA_SENSATIONS.search(query) or RE_ACUTE_PAIN_SIGNALS.search(query))
    if RE_BENIGN_FATIGUE.search(query) and not has_acute_signal:
        return False, 0.0

    word_count = len(query.split())
    has_clinical_token = bool(_CLINICAL_LEXICAL_TOKENS.search(query) or RE_TRAUMA_SENSATIONS.search(query))
    if word_count < 6 and not has_clinical_token:
        return False, 0.0

    query_vec = EMBED_MODEL.embed_query(query)
    max_sim = max(cosine_similarity(query_vec, anchor) for anchor in CLINICAL_ANCHOR_VECTORS)
    return (max_sim >= threshold), float(max_sim)
