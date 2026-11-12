"""Bounded day search; score the complete finite portion grid in array batches."""

from dataclasses import dataclass
from itertools import islice, product

import numpy as np

from core.meal_portions import portion_amounts, portion_normality

TOLERANCES = (.05, .05, .10, .10)
MEAL_CANDIDATES = 64
DAY_BEAM = 256
BATCH_SIZE = 4096


@dataclass(frozen=True)
class Candidate:
    totals: tuple
    normality: float
    order: tuple
    choices: tuple


def fit_error(totals, targets):
    relative = [abs(amount - target) / max(target, 1) for amount, target in zip(totals, targets)]
    gap = sum(max(0, error - tolerance - 1e-9) ** 2 for error, tolerance in zip(relative, TOLERANCES))
    return gap, sum(error ** 2 for error in relative)


def _rank(candidate, targets):
    return (*fit_error(candidate.totals, targets), candidate.normality, candidate.order)


def _shortlist(candidates, targets, limit):
    # Equal nutrient totals are interchangeable for day fit; prefer normal
    # amounts, then curation order. Keep deficit directions and extremes as well
    # as local fits so complementary meals can offset each other across the day.
    unique = {}
    for candidate in candidates:
        key = tuple(round(value, 8) for value in candidate.totals)
        previous = unique.get(key)
        if previous is None or (candidate.normality, candidate.order) < (previous.normality, previous.order):
            unique[key] = candidate
    ordered = sorted(unique.values(), key=lambda candidate: _rank(candidate, targets))
    return _retain_diversity(ordered, targets, limit)


def _retain_diversity(ordered, targets, limit):
    selected = {candidate.order: candidate for candidate in ordered[:limit]}
    directions = {}
    for candidate in ordered:
        direction = tuple(amount >= target for amount, target in zip(candidate.totals, targets))
        if directions.get(direction, 0) < 2:
            selected[candidate.order] = candidate
            directions[direction] = directions.get(direction, 0) + 1
    for index in range(4):
        for sign in (-1, 1):
            extreme = min(ordered, key=lambda candidate: sign * candidate.totals[index])
            selected[extreme.order] = extreme
    return sorted(selected.values(), key=lambda candidate: _rank(candidate, targets))


def _batch_indices(totals, normality, targets):
    relative = np.abs(totals - targets) / np.maximum(targets, 1)
    gaps = np.maximum(relative - TOLERANCES - np.full(4, 1e-9), 0)
    order = np.lexsort((np.arange(len(totals)), normality, (relative ** 2).sum(axis=1), (gaps ** 2).sum(axis=1)))
    indices = set(order[:MEAL_CANDIDATES].tolist())
    directions = ((totals >= targets) * (1 << np.arange(4))).sum(axis=1)
    for direction in np.unique(directions):
        indices.update(order[directions[order] == direction][:2].tolist())
    indices.update(np.argmin(totals, axis=0).tolist())
    indices.update(np.argmax(totals, axis=0).tolist())
    return sorted(indices)


def _options(foods, nutrient_keys):
    options = []
    for food in foods:
        values = [food["nutrients"].get(key) for key in nutrient_keys]
        if any(value is None or not np.isfinite(value) or value < 0 for value in values) or not any(values):
            continue
        for grams in portion_amounts(food):
            options.append((food, grams, tuple(value * grams / 100 for value in values),
                            portion_normality(food, grams)))
    return options


def meal_candidates(choices, targets, nutrient_keys):
    options = [_options(foods, nutrient_keys) for foods in choices]
    if not all(options):
        return []
    # Batch the two final roles; arrays never grow with the full three-role
    # Cartesian product. Only retained candidates become Python meal snapshots.
    pairs = product(range(len(options[1])), range(len(options[2])))
    retained = []
    while batch := list(islice(pairs, BATCH_SIZE)):
        for candidate in _batch_candidates(options, batch, targets):
            retained.append(candidate)
            if len(retained) >= BATCH_SIZE:
                retained = _shortlist(retained, targets, MEAL_CANDIDATES)
    return _shortlist(retained, targets, MEAL_CANDIDATES)


def _batch_candidates(options, batch, targets):
    vectors = np.array([np.add(options[1][b][2], options[2][c][2]) for b, c in batch])
    normality = np.array([options[1][b][3] + options[2][c][3] for b, c in batch])
    for a, first in enumerate(options[0]):
        totals = vectors + first[2]
        normals = normality + first[3]
        for index in _batch_indices(totals, normals, targets):
            b, c = batch[index]
            yield Candidate(tuple(float(amount) for amount in totals[index]), float(normals[index]), (a, b, c),
                            (first[:2], options[1][b][:2], options[2][c][:2]))


def choose_day(candidates, targets, shares):
    states = [Candidate((0.,) * 4, 0., (), ())]
    consumed_targets = [0.] * 4
    for meals, share in zip(candidates, shares):
        consumed_targets = [amount + target for amount, target in zip(consumed_targets, share)]
        combined = (Candidate(tuple(a + b for a, b in zip(state.totals, meal.totals)),
                              state.normality + meal.normality, state.order + (index,), state.choices + (meal,))
                    for state in states for index, meal in enumerate(meals))
        states = _shortlist(combined, consumed_targets, DAY_BEAM)
    return min(states, key=lambda candidate: _rank(candidate, targets))
