"""Build the Food library seed CSVs from a USDA FoodData Central CSV release.

Keeps the generic-food sources (Foundation Foods, SR Legacy and FNDDS survey
foods) and drops branded and sample rows. Nutrients are per 100 g edible
portion, as FoodData Central reports them. FoodData Central is CC0 1.0.
"""

import argparse
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FOODS_PATH = BASE_DIR / "data" / "food_library.csv"
DEFAULT_PORTIONS_PATH = BASE_DIR / "data" / "food_portions.csv"

SOURCES = {
    "foundation_food": "foundation",
    "sr_legacy_food": "sr_legacy",
    "survey_fndds_food": "fndds",
}

# Output column -> FoodData Central nutrient ids, first present wins.
NUTRIENTS = {
    "energy_kcal": ("1008", "2048", "2047"),
    "protein_g": ("1003",),
    "carbohydrate_g": ("1005", "1050"),
    "fat_g": ("1004",),
    "fiber_g": ("1079",),
    "sugars_g": ("2000",),
    "saturated_fat_g": ("1258",),
    "sodium_mg": ("1093",),
}
REQUIRED = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")
FOOD_COLUMNS = ("id", "source", "name", "category", *NUTRIENTS)
PORTION_COLUMNS = ("food_id", "seq", "label", "gram_weight")
UNDETERMINED_UNIT = "undetermined"


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _read_foods(release: Path) -> dict[str, dict[str, str]]:
    sr_categories = {row["id"]: row["description"] for row in _rows(release / "food_category.csv")}
    wweia_categories = {
        row["wweia_food_category"]: row["wweia_food_category_description"]
        for row in _rows(release / "wweia_food_category.csv")
    }
    fndds_categories = {
        row["fdc_id"]: wweia_categories.get(row["wweia_category_code"], "")
        for row in _rows(release / "survey_fndds_food.csv")
    }
    foods = {}
    for row in _rows(release / "food.csv"):
        source = SOURCES.get(row["data_type"])
        if source is None:
            continue
        fdc_id = row["fdc_id"]
        category = (
            fndds_categories.get(fdc_id, "")
            if source == "fndds"
            else sr_categories.get(row["food_category_id"], "")
        )
        foods[fdc_id] = {
            "id": fdc_id,
            "source": source,
            "name": row["description"].strip(),
            "category": category,
        }
    return foods


def _read_nutrients(release: Path, food_ids: set[str]) -> dict[str, dict[str, str]]:
    wanted = {nutrient_id for ids in NUTRIENTS.values() for nutrient_id in ids}
    amounts: dict[str, dict[str, str]] = {}
    for row in _rows(release / "food_nutrient.csv"):
        if row["fdc_id"] in food_ids and row["nutrient_id"] in wanted and row["amount"]:
            amounts.setdefault(row["fdc_id"], {})[row["nutrient_id"]] = row["amount"]
    return amounts


def _nutrient_values(amounts: dict[str, str]) -> dict[str, str]:
    values = {}
    for column, nutrient_ids in NUTRIENTS.items():
        found = next((amounts[n] for n in nutrient_ids if n in amounts), "")
        values[column] = f"{float(found):g}" if found else ""
    return values


def _portion_label(row: dict[str, str], units: dict[str, str]) -> str:
    if row["portion_description"].strip():
        return row["portion_description"].strip()
    unit = units.get(row["measure_unit_id"], "")
    parts = [f"{float(row['amount']):g}" if row["amount"] else ""]
    parts.append("" if unit == UNDETERMINED_UNIT else unit)
    parts.append(row["modifier"].strip())
    return " ".join(part for part in parts if part)


def _read_portions(release: Path, food_ids: set[str]) -> list[dict[str, str]]:
    units = {row["id"]: row["name"] for row in _rows(release / "measure_unit.csv")}
    portions = []
    for row in _rows(release / "food_portion.csv"):
        if row["fdc_id"] not in food_ids or not row["gram_weight"]:
            continue
        label = _portion_label(row, units)
        if not label or float(row["gram_weight"]) <= 0:
            continue
        portions.append(
            {
                "food_id": row["fdc_id"],
                "seq": row["seq_num"],
                "label": label,
                "gram_weight": f"{float(row['gram_weight']):g}",
            }
        )
    portions.sort(key=lambda p: (int(p["food_id"]), int(p["seq"] or 0)))
    return portions


def _write(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build(release: Path, foods_path: Path, portions_path: Path) -> None:
    foods = _read_foods(release)
    amounts = _read_nutrients(release, set(foods))
    rows = []
    for fdc_id, food in foods.items():
        values = _nutrient_values(amounts.get(fdc_id, {}))
        if all(values[column] for column in REQUIRED):
            rows.append({**food, **values})
    rows.sort(key=lambda row: (row["source"], row["name"].lower()))
    kept_ids = {row["id"] for row in rows}
    portions = _read_portions(release, kept_ids)
    _write(foods_path, FOOD_COLUMNS, rows)
    _write(portions_path, PORTION_COLUMNS, portions)
    print(
        f"{len(rows)} foods ({len(foods) - len(rows)} dropped without full macros), "
        f"{len(portions)} portions"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path, help="Unzipped FoodData Central CSV release directory")
    parser.add_argument("--foods", type=Path, default=DEFAULT_FOODS_PATH)
    parser.add_argument("--portions", type=Path, default=DEFAULT_PORTIONS_PATH)
    args = parser.parse_args()
    build(args.release, args.foods, args.portions)


if __name__ == "__main__":
    main()
