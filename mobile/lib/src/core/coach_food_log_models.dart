/// Read-only Coach snapshots preserve missing amounts and Macros on Quick add.
class CoachFoodLogEntry {
  CoachFoodLogEntry.fromJson(Map<String, dynamic> json)
      : kind = json['kind'] as String,
        foodId = json['food_id'] as String?,
        name = json['name'] as String,
        arabicName = json['arabic_name'] as String?,
        meal = json['meal_label'] as String,
        quantity = json['quantity'] as num?,
        unit = json['unit'] as String?,
        portionLabel = json['portion_label'] as String?,
        nutrients = Map<String, num?>.from(json['nutrients'] as Map);

  final String kind;
  final String? foodId;
  final String name;
  final String? arabicName;
  final String meal;
  final num? quantity;
  final String? unit;
  final String? portionLabel;
  final Map<String, num?> nutrients;
}

class CoachFoodLogDay {
  CoachFoodLogDay.fromJson(Map<String, dynamic> json)
      : date = DateTime.parse(json['date'] as String),
        today = DateTime.parse(json['today'] as String),
        entries = (json['entries'] as List<dynamic>)
            .map((dynamic row) => CoachFoodLogEntry.fromJson(row as Map<String, dynamic>))
            .toList(),
        totals = Map<String, num>.from(json['totals'] as Map),
        targets = json['targets'] as Map<String, dynamic>?,
        adherence = json['adherence'] as Map<String, dynamic>?;

  final DateTime date;
  final DateTime today;
  final List<CoachFoodLogEntry> entries;
  final Map<String, num> totals;
  final Map<String, dynamic>? targets;
  final Map<String, dynamic>? adherence;
}
