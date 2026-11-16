"""Private per-Player Meal setup, separate from Nutrition plan versions."""

import json


class LedgerMealSetupMixin:
    def get_meal_setup(self):
        row = self.conn.execute("SELECT * FROM meal_setup WHERE id=1").fetchone()
        if row is None:
            return {"meal_count": 3, "training_time": "evening",
                    "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}}
        return {"meal_count": row["meal_count"], "training_time": row["training_time"],
                "restrictions": json.loads(row["restrictions_json"])}

    def save_meal_setup(self, setup):
        self.conn.execute(
            "INSERT INTO meal_setup(id,meal_count,training_time,restrictions_json) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET meal_count=excluded.meal_count, "
            "training_time=excluded.training_time, restrictions_json=excluded.restrictions_json",
            (setup["meal_count"], setup["training_time"], json.dumps(setup["restrictions"])),
        )
