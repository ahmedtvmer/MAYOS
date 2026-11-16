"""Approximate day fit with fixed food, portion-neighborhood and beam budgets."""

from dataclasses import dataclass
from itertools import product

import numpy as np

from core.meal_portions import portion_grid, portion_limits

TOLERANCES = (.05, .05, .10, .10)
FOODS_PER_ROLE = 4
PORTION_SWEEPS = 12
MEAL_CANDIDATES = 16
DAY_BEAM = 32


@dataclass(frozen=True)
class Candidate:
    totals: tuple
    normality: float
    order: tuple
    choices: tuple


@dataclass(frozen=True)
class PortionFood:
    food: dict
    order: int
    nutrients: tuple
    lower: float
    upper: float
    step: float
    midpoint: float


def fit_error(totals, targets):
    relative = [abs(amount - target) / max(target, 1) for amount, target in zip(totals, targets)]
    gap = sum(max(0, error - tolerance - 1e-9) ** 2 for error, tolerance in zip(relative, TOLERANCES))
    return gap, sum(error ** 2 for error in relative)


def _rank(candidate, targets):
    return (*fit_error(candidate.totals, targets), candidate.normality, candidate.order)


def _shortlist(candidates, targets, limit):
    best_by_totals = {}
    for candidate in candidates:
        key = tuple(round(amount, 8) for amount in candidate.totals)
        previous = best_by_totals.get(key)
        if previous is None or (candidate.normality, candidate.order) < (previous.normality, previous.order):
            best_by_totals[key] = candidate
    ordered = sorted(best_by_totals.values(), key=lambda candidate: _rank(candidate, targets))
    return _retain_diversity(ordered, targets, limit)


def _retain_diversity(ordered, targets, limit):
    selected = {candidate.order: candidate for candidate in ordered[:limit]}
    directions = set()
    extremes = {}
    for candidate in ordered:
        direction = tuple(amount >= target for amount, target in zip(candidate.totals, targets))
        if direction not in directions:
            selected[candidate.order] = candidate
            directions.add(direction)
        for index, amount in enumerate(candidate.totals):
            low, high = extremes.get(index, (candidate, candidate))
            extremes[index] = (candidate if amount < low.totals[index] else low,
                               candidate if amount > high.totals[index] else high)
    for low, high in extremes.values():
        selected[low.order], selected[high.order] = low, high
    return sorted(selected.values(), key=lambda candidate: _rank(candidate, targets))


def _practical_foods(foods, nutrient_keys):
    practical = {}
    for order, food in enumerate(foods):
        nutrients = [food["nutrients"].get(key) for key in nutrient_keys]
        if (any(amount is None or not np.isfinite(amount) or amount < 0 for amount in nutrients)
                or not any(nutrients)):
            continue
        grid = portion_grid(food)
        if grid is not None:
            midpoint = sum(portion_limits(food)) / 2
            key = (tuple(nutrients), grid, midpoint)
            practical.setdefault(key, PortionFood(food, order, tuple(amount / 100 for amount in nutrients),
                                                   *grid, midpoint))
    return list(practical.values())


def _food_fit(option, targets, nutrient):
    vector = np.asarray(option.nutrients)
    grams = np.clip(targets[nutrient] / max(vector[nutrient], 1e-9), option.lower, option.upper)
    relative = (vector * grams - targets) / np.maximum(targets, 1)
    # Other roles can fill a deficit, but cannot undo this food's excess.
    return relative[nutrient] ** 2 + sum(np.maximum(relative, 0) ** 2), option.order


def _select_foods(options, targets, nutrient):
    if len(options) <= FOODS_PER_ROLE:
        return options
    ranked = sorted(options, key=lambda option: _food_fit(option, targets, nutrient))
    selected = {option.order: option for option in ranked[:FOODS_PER_ROLE - 2]}
    # Lean/rich alternatives let another meal compensate for an off-target slot.
    def fat_density(option):
        return option.nutrients[3] / max(option.nutrients[0], 1e-9)

    for option in (min(options, key=lambda option: (fat_density(option), option.order)),
                   min(options, key=lambda option: (-fat_density(option), option.order))):
        selected[option.order] = option
    for option in ranked:
        if len(selected) == FOODS_PER_ROLE:
            break
        selected[option.order] = option
    return sorted(selected.values(), key=lambda option: option.order)


def _continuous_portions(triples, targets):
    vectors = np.asarray([[option.nutrients for option in triple] for triple in triples])
    lower = np.asarray([[option.lower for option in triple] for triple in triples])
    upper = np.asarray([[option.upper for option in triple] for triple in triples])
    grams = (lower + upper) / 2
    scaled = vectors / (np.maximum(targets, 1) * TOLERANCES)
    residual = targets / (np.maximum(targets, 1) * TOLERANCES) - (scaled * grams[:, :, None]).sum(axis=1)
    for _ in range(PORTION_SWEEPS):
        for role in range(3):
            column = scaled[:, role]
            adjustment = (residual * column).sum(axis=1) / np.maximum((column ** 2).sum(axis=1), 1e-12)
            updated = np.clip(grams[:, role] + adjustment, lower[:, role], upper[:, role])
            residual -= column * (updated - grams[:, role])[:, None]
            grams[:, role] = updated
    return vectors, grams


def _nearby_amounts(option, optimum):
    # Fixed intervals collapse to one amount; off-grid bounds stay unavailable.
    unit = optimum / option.step
    nearest = np.floor(unit + .5)
    return sorted({round(float(np.clip(index * option.step, option.lower, option.upper)), 6)
                   for index in (nearest - 1, nearest, nearest + 1)})


def _portion_neighborhood(triple, optimum):
    nearby = [_nearby_amounts(option, grams) for option, grams in zip(triple, optimum)]
    portions = set(product(*nearby))
    snapped = tuple(min(amounts, key=lambda amount: (abs(amount - grams), amount))
                    for amounts, grams in zip(nearby, optimum))
    # Endpoints preserve nutrient extremes without enumerating each portion step.
    for role, option in enumerate(triple):
        for endpoint in (option.lower, option.upper):
            portions.add(snapped[:role] + (endpoint,) + snapped[role + 1:])
    portions.update((tuple(option.lower for option in triple), tuple(option.upper for option in triple)))
    return sorted(portions)


def _portion_arrays(triples, targets):
    vectors, optima = _continuous_portions(triples, targets)
    amounts, totals, normalities, triple_indices = [], [], [], []
    for index, (triple, vector, optimum) in enumerate(zip(triples, vectors, optima)):
        portions = np.asarray(_portion_neighborhood(triple, optimum))
        midpoints = np.asarray([option.midpoint for option in triple])
        amounts.extend(portions)
        totals.extend(portions @ vector)
        normalities.extend((((portions - midpoints) / midpoints) ** 2).sum(axis=1))
        triple_indices.extend([index] * len(portions))
    return np.asarray(amounts), np.asarray(totals), np.asarray(normalities), triple_indices


def _retained_indices(totals, normalities, targets):
    normal_order = np.lexsort((np.arange(len(totals)), normalities))
    _, distinct = np.unique(np.round(totals[normal_order], 8), axis=0, return_index=True)
    indices = normal_order[distinct]
    relative = np.abs(totals[indices] - targets) / np.maximum(targets, 1)
    gaps = np.maximum(relative - TOLERANCES - 1e-9, 0)
    ranked = indices[np.lexsort((indices, normalities[indices], (relative ** 2).sum(axis=1), (gaps ** 2).sum(axis=1)))]
    selected = set(ranked[:MEAL_CANDIDATES].tolist())
    directions = ((totals >= targets) * (1 << np.arange(4))).sum(axis=1)
    for direction in np.unique(directions[ranked]):
        selected.add(int(ranked[directions[ranked] == direction][0]))
    selected.update(indices[np.argmin(totals[indices], axis=0)].tolist())
    selected.update(indices[np.argmax(totals[indices], axis=0)].tolist())
    return sorted(selected)


def _meal_candidates(triples, targets):
    portions, totals, normalities, triple_indices = _portion_arrays(triples, targets)
    candidates = []
    for index in _retained_indices(totals, normalities, targets):
        triple, grams = triples[triple_indices[index]], portions[index]
        candidates.append(Candidate(tuple(float(amount) for amount in totals[index]), float(normalities[index]),
                                    (tuple(option.order for option in triple), tuple(float(amount) for amount in grams)),
                                    tuple((option.food, float(amount)) for option, amount in zip(triple, grams))))
    return _shortlist(candidates, targets, MEAL_CANDIDATES)


def meal_candidates(choices, targets, nutrient_keys):
    targets = np.asarray(targets)
    options = [_select_foods(_practical_foods(foods, nutrient_keys), targets, nutrient)
               for foods, nutrient in zip(choices, (1, 2, 3))]
    if not all(options):
        return []
    return _meal_candidates(list(product(*options)), targets)


def choose_day(candidates, targets, shares):
    states = [Candidate((0.,) * 4, 0., (), ())]
    consumed_targets = [0.] * 4
    for meals, share in zip(candidates, shares):
        consumed_targets = [amount + target for amount, target in zip(consumed_targets, share)]
        combined = (Candidate(tuple(a + b for a, b in zip(state.totals, meal.totals)),
                              state.normality + meal.normality, state.order + (meal.order,), state.choices + (meal,))
                    for state in states for meal in meals)
        states = _shortlist(combined, consumed_targets, DAY_BEAM)
    return min(states, key=lambda candidate: _rank(candidate, targets))
