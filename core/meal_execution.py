"""Run CPU-heavy meal search outside the request process's GIL."""

import multiprocessing
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from copy import deepcopy
from threading import Lock

from core.meal_generator import MealGenerationInput, generate_meals

_CACHE_LIMIT = 128
_generation_pool = ProcessPoolExecutor(
    max_workers=1, mp_context=multiprocessing.get_context("spawn"),
)
_generation_lock = Lock()
_in_flight: dict[str, Future] = {}
_completed: OrderedDict[str, dict] = OrderedDict()


def _generation_finished(key, future):
    with _generation_lock:
        if _in_flight.get(key) is future:
            del _in_flight[key]
        if future.cancelled() or future.exception() is not None:
            return
        _completed[key] = deepcopy(future.result())
        _completed.move_to_end(key)
        while len(_completed) > _CACHE_LIMIT:
            _completed.popitem(last=False)


def generate_meals_bounded(request: MealGenerationInput, key: str):
    with _generation_lock:
        if key in _completed:
            _completed.move_to_end(key)
            return deepcopy(_completed[key])
        future = _in_flight.get(key)
        if future is None:
            future = _generation_pool.submit(generate_meals, request)
            _in_flight[key] = future
            submitted = True
        else:
            submitted = False
    if submitted:
        future.add_done_callback(lambda completed: _generation_finished(key, completed))
    return deepcopy(future.result())
