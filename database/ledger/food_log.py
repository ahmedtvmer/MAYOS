"""Food log snapshots belong only to the Player's Training ledger."""

import json


def _entry(row):
    if row is None:
        return None
    entry = dict(row)
    for key in ("nutrients", "nutrients_per_100g"):
        value = entry.pop(f"{key}_json")
        entry[key] = json.loads(value) if value is not None else None
    return entry


class LedgerFoodLogMixin:
    def list_personal_foods(self):
        return [self._personal_food(row) for row in self.conn.execute(
            "SELECT * FROM personal_foods ORDER BY name, id",
        ).fetchall()]

    def get_personal_food(self, food_id):
        row = self.conn.execute("SELECT * FROM personal_foods WHERE id=?", (food_id,)).fetchone()
        return self._personal_food(row) if row is not None else None

    @staticmethod
    def _personal_food(row):
        food = dict(row)
        food["nutrients"] = json.loads(food.pop("nutrients_json"))
        return {**food, "kind": "personal_food", "reviewed": True, "arabic_name": None}

    def insert_personal_food(self, food):
        self.conn.execute(
            "INSERT INTO personal_foods(id,name,nutrients_json,portion_label,portion_grams,created_at) "
            "VALUES(:id,:name,:nutrients_json,:portion_label,:portion_grams,:created_at)",
            {**food, "nutrients_json": json.dumps(food["nutrients"])},
        )

    def list_food_log_entries(self, entry_date):
        return [_entry(row) for row in self.conn.execute(
            "SELECT * FROM food_log_entries WHERE entry_date=? ORDER BY logged_time, created_at, id",
            (str(entry_date),),
        ).fetchall()]

    def list_food_log_nutrients(self, entry_date):
        return [json.loads(row[0]) for row in self.conn.execute(
            "SELECT nutrients_json FROM food_log_entries WHERE entry_date=?",
            (str(entry_date),),
        ).fetchall()]

    def list_food_log_dates(self, start_date, end_date):
        return {str(row[0]) for row in self.conn.execute(
            "SELECT DISTINCT entry_date FROM food_log_entries WHERE entry_date BETWEEN ? AND ?",
            (str(start_date), str(end_date)),
        ).fetchall()}

    def get_food_log_entry(self, entry_id):
        return _entry(self.conn.execute(
            "SELECT * FROM food_log_entries WHERE id=?", (entry_id,),
        ).fetchone())

    def food_log_usage(self):
        return {row[0]: {"count": row[1], "last_logged": row[2]} for row in self.conn.execute(
            "SELECT food_id, COUNT(*), MAX(entry_date || 'T' || logged_time) "
            "FROM food_log_entries WHERE food_id IS NOT NULL GROUP BY food_id",
        ).fetchall()}

    def insert_food_log_entry(self, entry):
        self.conn.execute(
            "INSERT INTO food_log_entries(id, entry_date, logged_time, meal_label, kind, food_id, "
            "name, arabic_name, grams, unit, quantity, portion_label, portion_grams, "
            "nutrients_per_100g_json, nutrients_json, created_at) "
            "VALUES(:id, :entry_date, :logged_time, :meal_label, :kind, :food_id, :name, :arabic_name, "
            ":grams, :unit, :quantity, :portion_label, :portion_grams, :nutrients_per_100g_json, "
            ":nutrients_json, :created_at)",
            {**entry, "nutrients_per_100g_json": (json.dumps(entry["nutrients_per_100g"])
                                                if entry["nutrients_per_100g"] is not None else None),
             "nutrients_json": json.dumps(entry["nutrients"])},
        )

    def update_food_log_entry(self, entry):
        self.conn.execute(
            "UPDATE food_log_entries SET logged_time=:logged_time, meal_label=:meal_label, "
            "grams=:grams, unit=:unit, quantity=:quantity, nutrients_json=:nutrients_json WHERE id=:id",
            {**entry, "nutrients_json": json.dumps(entry["nutrients"])},
        )

    def delete_food_log_entry(self, entry_id):
        self.conn.execute("DELETE FROM food_log_entries WHERE id=?", (entry_id,))
