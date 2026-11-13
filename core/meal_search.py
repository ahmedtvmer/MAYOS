"""Bounded day search; score the complete finite portion grid in array batches."""

from dataclasses import dataclass
from math import prod

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


@dataclass(frozen=True)
class CandidateGrid:
    options: tuple
    nutrient_vectors: tuple
    normalities: tuple
    targets: np.ndarray


def fit_error(totals, targets):
    relative = [abs(amount - target) / max(target, 1) for amount, target in zip(totals, targets)]
    gap = sum(max(0, error - tolerance - 1e-9) ** 2 for error, tolerance in zip(relative, TOLERANCES))
    return gap, sum(error ** 2 for error in relative)


def _rank(candidate, targets):
    return (*fit_error(candidate.totals, targets), candidate.normality, candidate.order)


def _shortlist(candidates, targets, limit):
    best_by_totals = {}
    for candidate in candidates:
        key = tuple(round(nutrient_amount, 8) for nutrient_amount in candidate.totals)
        previous = best_by_totals.get(key)
        if previous is None or (candidate.normality, candidate.order) < (previous.normality, previous.order):
            best_by_totals[key] = candidate
    ordered = list(best_by_totals.values())
    if not ordered:
        return []
    totals = np.asarray([candidate.totals for candidate in ordered])
    relative = np.abs(totals - targets) / np.maximum(targets, 1)
    gaps = np.maximum(relative - TOLERANCES - 1e-9, 0)
    curation_order = sorted(range(len(ordered)), key=lambda index: ordered[index].order)
    order_rank = np.empty(len(ordered), dtype=np.int64)
    order_rank[curation_order] = np.arange(len(ordered))
    ranked = np.lexsort((order_rank, [candidate.normality for candidate in ordered],
                         (relative ** 2).sum(axis=1), (gaps ** 2).sum(axis=1)))
    ordered = [ordered[index] for index in ranked]
    return _retain_diversity(ordered, targets, limit)


def _retain_diversity(ordered, targets, limit):
    selected = {candidate.order: candidate for candidate in ordered[:limit]}
    directions = {}
    extremes = {}
    for candidate in ordered:
        direction = tuple(amount >= target for amount, target in zip(candidate.totals, targets))
        if directions.get(direction, 0) < 2:
            selected[candidate.order] = candidate
            directions[direction] = directions.get(direction, 0) + 1
        for index, amount in enumerate(candidate.totals):
            low, high = extremes.get(index, (None, None))
            if low is None or amount < low.totals[index]:
                low = candidate
            if high is None or amount > high.totals[index]:
                high = candidate
            extremes[index] = low, high
    for low_candidate, high_candidate in extremes.values():
        selected[low_candidate.order] = low_candidate
        selected[high_candidate.order] = high_candidate
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
    best_by_nutrients = {}
    portion_order = 0
    for food in foods:
        nutrient_amounts = [food["nutrients"].get(key) for key in nutrient_keys]
        if (any(amount is None or not np.isfinite(amount) or amount < 0 for amount in nutrient_amounts)
                or not any(nutrient_amounts)):
            continue
        for grams in portion_amounts(food):
            nutrients = tuple(amount * grams / 100 for amount in nutrient_amounts)
            normality = portion_normality(food, grams)
            key = tuple(round(nutrient_amount, 8) for nutrient_amount in nutrients)
            role_option = (food, grams, nutrients, normality, portion_order)
            previous = best_by_nutrients.get(key)
            if previous is None or (normality, portion_order) < (previous[3], previous[4]):
                best_by_nutrients[key] = role_option
            portion_order += 1
    return [role_option[:4] for role_option in sorted(
        best_by_nutrients.values(), key=lambda role_option: role_option[4],
    )]


def _candidate_batch(grid, start, stop):
    role_sizes = tuple(len(role) for role in grid.options)
    flat = np.arange(start, stop)
    role_indices = (flat // (role_sizes[1] * role_sizes[2]),
                    (flat // role_sizes[2]) % role_sizes[1], flat % role_sizes[2])
    totals = (grid.nutrient_vectors[0][role_indices[0]] + grid.nutrient_vectors[1][role_indices[1]]
              + grid.nutrient_vectors[2][role_indices[2]])
    normality = (grid.normalities[0][role_indices[0]] + grid.normalities[1][role_indices[1]]
                 + grid.normalities[2][role_indices[2]])
    return [Candidate(tuple(float(amount) for amount in totals[index]), float(normality[index]),
                      tuple(int(role[index]) for role in role_indices),
                      tuple(grid.options[role][role_indices[role][index]][:2] for role in range(3)))
            for index in _batch_indices(totals, normality, grid.targets)]


def _prune_role_options(options, targets):
    vectors = [np.asarray([option[2] for option in role]) for role in options]
    minima = [role.min(axis=0) for role in vectors]
    maxima = [role.max(axis=0) for role in vectors]
    scale = np.maximum(targets, 1)
    lower = targets - (np.asarray(TOLERANCES) + 1e-9) * scale
    upper = targets + (np.asarray(TOLERANCES) + 1e-9) * scale
    viable = []
    for role_index, role_vectors in enumerate(vectors):
        other_minimum = sum(minima[index] for index in range(3) if index != role_index)
        other_maximum = sum(maxima[index] for index in range(3) if index != role_index)
        viable.append(np.all((role_vectors + other_minimum <= upper)
                             & (role_vectors + other_maximum >= lower), axis=1))
    # A slot with no individually viable role still needs its portions for day-level complements.
    if not all(role_viable.any() for role_viable in viable):
        return options
    pruned = []
    for role_index, role_options in enumerate(options):
        extremes = {int(index) for nutrient in range(4)
                    for index in (np.argmin(vectors[role_index][:, nutrient]),
                                  np.argmax(vectors[role_index][:, nutrient]))}
        pruned.append([option for index, option in enumerate(role_options)
                       if viable[role_index][index] or index in extremes])
    return pruned


def meal_candidates(choices, targets, nutrient_keys):
    options = [_options(foods, nutrient_keys) for foods in choices]
    if not all(options):
        return []
    options = _prune_role_options(options, np.asarray(targets))
    vectors = tuple(np.asarray([option[2] for option in role]) for role in options)
    normalities = tuple(np.asarray([option[3] for option in role]) for role in options)
    grid = CandidateGrid(tuple(options), vectors, normalities, np.asarray(targets))
    total = prod(len(role) for role in options)
    retained = []
    for start in range(0, total, BATCH_SIZE):
        batch = _candidate_batch(grid, start, min(start + BATCH_SIZE, total))
        retained = _shortlist((*retained, *batch), targets, MEAL_CANDIDATES)
    return retained


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
