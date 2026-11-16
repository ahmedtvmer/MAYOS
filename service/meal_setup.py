"""Player-owned Meal setup; does not change Nutrition authority or targets."""

from core.meal_setup import MEAL_LAYOUTS
from service.meals import refresh_setup


def read(db, ledger):
    setup = ledger.get_meal_setup()
    disliked_foods = []
    for food_id in setup["restrictions"]["dislikes"]:
        food = _food(db, ledger, food_id)
        disliked_foods.append({"id": food_id, "name": food["name"] if food else food_id,
                               "arabic_name": food.get("arabic_name") if food else None})
    return {**setup, "slots": list(MEAL_LAYOUTS[setup["meal_count"]]), "disliked_foods": disliked_foods}


def _food(db, ledger, food_id):
    return (ledger.get_personal_food(food_id) if food_id.startswith("personal:")
            else db.get_food_library_food(food_id))


def save(db, ledger, setup):
    for food_id in setup["restrictions"]["dislikes"]:
        food = _food(db, ledger, food_id)
        if food is None:
            raise ValueError("Choose disliked foods from the Food library or your Personal foods.")
    with ledger.ledger_transaction():
        previous = ledger.get_meal_setup()
        ledger.save_meal_setup(setup)
        if previous != setup:
            refresh_setup(ledger)
    return read(db, ledger)
