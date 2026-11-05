"""Visible Food library lookup; usage is supplied by the service, never read here."""

import json
import sqlite3
from dataclasses import dataclass

from core.arabic import normalize_arabic_text
from database.shared import _normalize_exercise_name


def _normalized(text):
    return normalize_arabic_text(_normalize_exercise_name(text or ""))


def _food(row):
    food = dict(row)
    for field in ("nutrients", "portions", "aliases_en", "aliases_ar", "staple_roles", "ingredients"):
        food[field] = json.loads(food.pop(f"{field}_json") or "[]")
    food["reviewed"] = bool(food["reviewed"])
    if not food["reviewed"]:
        food["name"] = food["source_name"]
        food["arabic_name"] = None
        food["aliases_ar"] = []
    food.pop("hidden")
    return food


@dataclass(frozen=True, slots=True)
class _IndexedFood:
    names: tuple[str, ...]
    aliases: tuple[str, ...]
    staple: bool
    reviewed: bool


def _index_food(row):
    reviewed = bool(row["reviewed"])
    names = [_normalized(row["name"] if reviewed else row["source_name"])]
    aliases = json.loads(row["aliases_en_json"])
    if reviewed:
        names.append(_normalized(row["arabic_name"]))
        aliases.extend(json.loads(row["aliases_ar_json"]))
    return _IndexedFood(tuple(names), tuple(_normalized(alias) for alias in aliases),
                        bool(json.loads(row["staple_roles_json"])), reviewed)


def _match_rank(food, query):
    if query in food.names:
        return 0
    if any(name.startswith(query) for name in food.names):
        return 1
    if any(query in alias for alias in food.aliases):
        return 2
    if any(query in name for name in food.names):
        return 3
    return None


def _recent_food_ids(index, usage, limit):
    usage = {key: value for key, value in usage.items() if key in index}
    recent = sorted(usage, key=lambda key: (usage[key]["last_logged"], key), reverse=True)[:10]
    frequent = sorted(usage, key=lambda key: (-usage[key]["count"], key))[:10]
    return list(dict.fromkeys([*recent, *frequent]))[:limit]


def _matching_food_ids(index, query, limit):
    matches = []
    for food_id, food in index.items():
        match = _match_rank(food, query)
        if match is not None:
            matches.append((not food.staple, not food.reviewed, match, food.names[0], food_id))
    return [match[-1] for match in sorted(matches)[:limit]]


def _named_rows(connection, sql, parameters=()):
    # The catalog connection returns plain tuples; food rows are read by column name.
    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute(sql, parameters).fetchall()


def _revision(connection):
    return connection.execute("SELECT counter FROM food_search_revision WHERE id=1").fetchone()[0]


class FoodLookupMixin:
    def _get_food_search_index(self):
        # Builders serialize independently of the catalog; normalization never
        # keeps other catalog readers waiting on this store's connection.
        with self._food_search_lock:
            while True:
                with self._catalog_lock:
                    revision = _revision(self.catalog_conn)
                    cached = self._food_search_cache
                    if cached is not None and cached[0] == revision:
                        return cached
                    rows = _named_rows(
                        self.catalog_conn,
                        "SELECT id, name, source_name, arabic_name, aliases_en_json, "
                        "aliases_ar_json, staple_roles_json, reviewed FROM foods WHERE hidden=0",
                    )
                index = {row["id"]: _index_food(row) for row in rows}
                with self._catalog_lock:
                    if _revision(self.catalog_conn) != revision:
                        continue
                    self._food_search_cache = (revision, index)
                    return self._food_search_cache

    def get_food_library_food(self, food_id):
        with self._catalog_lock:
            rows = _named_rows(
                self.catalog_conn, "SELECT * FROM foods WHERE id=? AND hidden=0", (food_id,),
            )
        return _food(rows[0]) if rows else None

    def search_food_library(self, query, usage=None, limit=50):
        usage = usage or {}
        query = _normalized(query)
        while True:
            revision, index = self._get_food_search_index()
            ids = (_matching_food_ids(index, query, limit) if query
                   else _recent_food_ids(index, usage, limit))
            with self._catalog_lock:
                if _revision(self.catalog_conn) != revision:
                    continue
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                rows = _named_rows(
                    self.catalog_conn, f"SELECT * FROM foods WHERE id IN ({placeholders}) AND hidden=0", ids,
                )
                if _revision(self.catalog_conn) != revision:
                    continue
            foods = {row["id"]: _food(row) for row in rows}
            return [{**foods[key], "logged_count": usage.get(key, {}).get("count", 0)}
                    for key in ids if key in foods]
