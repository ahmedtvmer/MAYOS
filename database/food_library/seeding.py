"""Persist the shared Food library in the catalog database."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from database.food_library.builder import (
    ALLERGEN_PATH, CURATION_PATH, FOOD_PATH, NUTRIENTS, PORTION_PATH, RECIPE_PATH, build_food_library,
)
from utils.logger import MayosLogger

logger = MayosLogger().get_logger(__name__)


@dataclass(frozen=True)
class FoodLibraryPaths:
    foods: Path = FOOD_PATH
    portions: Path = PORTION_PATH
    curation: Path = CURATION_PATH
    recipes: Path = RECIPE_PATH
    allergens: Path = ALLERGEN_PATH


FOOD_LIBRARY_META_DDL = """CREATE TABLE IF NOT EXISTS food_library_meta (
    id INTEGER PRIMARY KEY CHECK(id=1), input_hash TEXT NOT NULL
)"""


def shipped_food_library_paths() -> FoodLibraryPaths | None:
    """The Food library inputs this deployment ships (issue #844).

    The catalog startup refresh rebuilds the Food library only from these
    files, never from a caller-supplied path. Tests pin this to ``None`` so a
    server that ships the licensed data files cannot rebuild test catalogs;
    tests of the refresh pin explicit paths instead.
    """
    return FoodLibraryPaths()


def food_library_input_hash(paths: FoodLibraryPaths) -> str | None:
    """SHA-256 over the Food library inputs in load order.

    Returns ``None`` when an input is missing or unreadable: a partial
    deployment (e.g. a test catalog path) must not crash startup.
    """
    digest = hashlib.sha256()
    for path in (paths.foods, paths.portions, paths.curation, paths.recipes, paths.allergens):
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            return None
        digest.update(b"\0")
    return digest.hexdigest()


def store_food_library_input_hash(connection, input_hash: str | None) -> None:
    """Record the input hash the catalog's Food library was built from."""
    if input_hash is None:
        return
    connection.execute(FOOD_LIBRARY_META_DDL)
    connection.execute(
        "INSERT INTO food_library_meta(id, input_hash) VALUES(1, ?) "
        "ON CONFLICT(id) DO UPDATE SET input_hash=excluded.input_hash",
        (input_hash,),
    )


def refresh_catalog_food_library(connection) -> bool:
    """Re-seed the shared Food library when its shipped inputs changed (#844).

    Runs at catalog startup next to the exercise curation re-apply: a catalog
    seeded before a Food library update would otherwise never pick up newly
    reviewed staples. Unchanged inputs do no work; missing input files are a
    warning, never a startup failure. Returns True when a rebuild ran.
    """
    paths = shipped_food_library_paths()
    if paths is None:
        return False
    input_hash = food_library_input_hash(paths)
    if input_hash is None:
        missing = next(
            (str(path) for path in (paths.foods, paths.portions, paths.curation, paths.recipes, paths.allergens)
             if not Path(path).is_file()),
            str(paths.foods),
        )
        logger.warning("Food library refresh skipped; shipped input '%s' is missing.", missing)
        return False
    connection.execute(FOOD_LIBRARY_META_DDL)
    row = connection.execute("SELECT input_hash FROM food_library_meta WHERE id = 1").fetchone()
    if row is not None and row[0] == input_hash:
        return False
    count = seed_food_library(connection, paths)
    store_food_library_input_hash(connection, input_hash)
    connection.commit()
    logger.info("Food library refreshed from shipped inputs: %s foods.", count)
    return True


def food_staples_status(connection) -> str:
    """``missing`` when the catalog has foods but no reviewed, visible staple (#844).

    Reviewed staples gate planned meals for Players, so a food library without
    one is an operator-visible problem. An absent or empty foods table is
    ``ok``: the startup refresh owns the rebuild, and there is nothing
    half-loaded to report.
    """
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'foods'"
    ).fetchone() is None:
        return "ok"
    has_foods, has_staple = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM foods), EXISTS("
        "SELECT 1 FROM foods WHERE reviewed = 1 AND hidden = 0 "
        "AND staple_roles_json NOT IN ('', '[]'))"
    ).fetchone()
    return "missing" if has_foods and not has_staple else "ok"


def _create_food_table(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS foods (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, source_name TEXT NOT NULL,
        arabic_name TEXT, nutrients_json TEXT NOT NULL, portions_json TEXT NOT NULL,
        aliases_en_json TEXT NOT NULL, aliases_ar_json TEXT NOT NULL,
        staple_roles_json TEXT NOT NULL, hidden INTEGER NOT NULL,
        reviewed INTEGER NOT NULL, portion_label TEXT, portion_grams REAL,
        ingredients_json TEXT, min_grams REAL, max_grams REAL
    )""")
    ensure_food_meal_limits_schema(connection)
    ensure_food_search_schema(connection)


def ensure_food_meal_limits_schema(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(foods)")}
    for column in ("min_grams", "max_grams"):
        if column not in columns:
            connection.execute(f"ALTER TABLE foods ADD COLUMN {column} REAL")


def ensure_food_search_schema(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(foods)")}
    for name, definition in (
        ("category", "TEXT NOT NULL DEFAULT ''"),
        ("vegetarian", "INTEGER NOT NULL DEFAULT 1"),
        ("allergens_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("allergens_reviewed", "INTEGER NOT NULL DEFAULT 0"),
        ("staple_order", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE foods ADD COLUMN {name} {definition}")
    connection.execute("""CREATE TABLE IF NOT EXISTS food_search_revision (
        id INTEGER PRIMARY KEY CHECK(id=1), counter INTEGER NOT NULL DEFAULT 0
    )""")
    connection.execute("INSERT OR IGNORE INTO food_search_revision(id, counter) VALUES(1, 0)")
    for operation in ("INSERT", "UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS food_search_revision_{operation.lower()} "
            f"AFTER {operation} ON foods BEGIN "
            "UPDATE food_search_revision SET counter=counter+1 WHERE id=1; END"
        )


def _storage_row(row):
    return {
        **row,
        "nutrients_json": json.dumps({key: row[key] for key in NUTRIENTS}, sort_keys=True),
        "portions_json": json.dumps(row["portions"], ensure_ascii=False, sort_keys=True),
        "aliases_en_json": json.dumps(row["aliases_en"], ensure_ascii=False),
        "aliases_ar_json": json.dumps(row["aliases_ar"], ensure_ascii=False),
        "staple_roles_json": json.dumps(row["staple_roles"], ensure_ascii=False),
        "ingredients_json": json.dumps(row.get("ingredients", []), ensure_ascii=False, sort_keys=True),
        "allergens_json": json.dumps(row["allergens"]),
    }


def _upsert_food_rows(connection, rows):
    connection.execute("DELETE FROM foods")
    connection.executemany("""INSERT INTO foods
        (id,name,source_name,arabic_name,nutrients_json,portions_json,aliases_en_json,
         aliases_ar_json,staple_roles_json,hidden,reviewed,portion_label,portion_grams,ingredients_json,
         category,vegetarian,allergens_json,allergens_reviewed,staple_order,min_grams,max_grams)
        VALUES (:id,:name,:source_name,:arabic_name,:nutrients_json,:portions_json,:aliases_en_json,
         :aliases_ar_json,:staple_roles_json,:hidden,:reviewed,:portion_label,:portion_grams,:ingredients_json,
         :category,:vegetarian,:allergens_json,:allergens_reviewed,:staple_order,:min_grams,:max_grams)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name, source_name=excluded.source_name,
         arabic_name=excluded.arabic_name,nutrients_json=excluded.nutrients_json,
         portions_json=excluded.portions_json,aliases_en_json=excluded.aliases_en_json,
         aliases_ar_json=excluded.aliases_ar_json,staple_roles_json=excluded.staple_roles_json,
         hidden=excluded.hidden,reviewed=excluded.reviewed,portion_label=excluded.portion_label,
         portion_grams=excluded.portion_grams,ingredients_json=excluded.ingredients_json,
         category=excluded.category,vegetarian=excluded.vegetarian,
         allergens_json=excluded.allergens_json,allergens_reviewed=excluded.allergens_reviewed,
         staple_order=excluded.staple_order,
         min_grams=excluded.min_grams,max_grams=excluded.max_grams""",
        [_storage_row(row) for row in rows])


def seed_food_library(connection, paths=FoodLibraryPaths()):
    rows = build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes, paths.allergens)
    _create_food_table(connection)
    _upsert_food_rows(connection, rows)
    connection.commit()
    return len(rows)
