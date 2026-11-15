"""Shared Food library and Personal food text matching."""

from core.arabic import normalize_arabic_text
from database.shared import _normalize_exercise_name


def normalize_food_query(text):
    return normalize_arabic_text(_normalize_exercise_name(text or ""))


def _food_forms(text):
    words = text.split()
    forms = {text}
    for index, word in enumerate(words):
        if word.endswith("y") and len(word) > 2:
            alternate = word[:-1] + "ie"
        elif word.endswith("ie"):
            alternate = word[:-2] + "y"
        else:
            continue
        alternate_words = list(words)
        alternate_words[index] = alternate
        forms.add(" ".join(alternate_words))
    return forms


def food_match_rank(names, aliases, query):
    query_forms = _food_forms(query)
    name_forms = {form for name in names for form in _food_forms(name)}
    alias_forms = {form for alias in aliases for form in _food_forms(alias)}
    if query_forms & name_forms:
        return 0
    if any(
        name.startswith(query_form)
        for name in name_forms
        for query_form in query_forms
    ):
        return 1
    if any(
        query_form in alias
        for alias in alias_forms
        for query_form in query_forms
    ):
        return 2
    if any(
        query_form in name
        for name in name_forms
        for query_form in query_forms
    ):
        return 3
    return None
