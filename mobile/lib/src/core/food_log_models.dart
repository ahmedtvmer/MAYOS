class FoodNutrients {
  const FoodNutrients({
    required this.kcal,
    required this.protein,
    required this.carbs,
    required this.fat,
  });

  factory FoodNutrients.fromJson(Map<String, dynamic> json) => FoodNutrients(
    kcal: (json['energy_kcal'] as num? ?? 0).toDouble(),
    protein: (json['protein_g'] as num? ?? 0).toDouble(),
    carbs: (json['carbohydrate_g'] as num? ?? 0).toDouble(),
    fat: (json['fat_g'] as num? ?? 0).toDouble(),
  );

  final double kcal;
  final double protein;
  final double carbs;
  final double fat;

  FoodNutrients forGrams(double grams) => FoodNutrients(
    kcal: kcal * grams / 100,
    protein: protein * grams / 100,
    carbs: carbs * grams / 100,
    fat: fat * grams / 100,
  );
}

class FoodLibraryItem {
  const FoodLibraryItem({
    required this.id,
    required this.name,
    this.arabicName,
    required this.nutrients,
    this.portionLabel,
    this.portionGrams,
    this.staple = false,
    this.recipe = false,
    this.loggedCount = 0,
    this.restrictionReasons = const <String>[],
  });

  factory FoodLibraryItem.fromJson(
    Map<String, dynamic> json,
  ) => FoodLibraryItem(
    id: json['id'] as String,
    name: json['name'] as String,
    arabicName: json['reviewed'] == true
        ? json['arabic_name'] as String?
        : null,
    nutrients: FoodNutrients.fromJson(
      json['nutrients'] as Map<String, dynamic>,
    ),
    portionLabel: json['portion_label'] as String?,
    portionGrams: (json['portion_grams'] as num?)?.toDouble(),
    staple: (json['staple_roles'] as List<dynamic>? ?? <dynamic>[]).isNotEmpty,
    recipe: (json['ingredients'] as List<dynamic>? ?? <dynamic>[]).isNotEmpty,
    loggedCount: (json['logged_count'] as num? ?? 0).toInt(),
    restrictionReasons: (json['restriction_reasons'] as List<dynamic>? ?? <dynamic>[]).cast<String>(),
  );

  final String id;
  final String name;
  final String? arabicName;
  final FoodNutrients nutrients;
  final String? portionLabel;
  final double? portionGrams;
  final bool staple;
  final bool recipe;
  final int loggedCount;
  final List<String> restrictionReasons;

  String displayName(bool arabic) => arabic ? arabicName ?? name : name;
}

class FoodLogEntry {
  const FoodLogEntry({
    required this.id,
    required this.food,
    required this.nutrients,
    required this.grams,
    required this.quantity,
    required this.unit,
    required this.mealLabel,
    required this.loggedTime,
    this.mealSlot,
    this.kind = 'library_food',
    this.blankMacros = const <String>{},
  });

  factory FoodLogEntry.fromJson(Map<String, dynamic> json) => FoodLogEntry(
    id: json['id'] as String,
    food: FoodLibraryItem(
      id: json['food_id'] as String? ?? '',
      name: json['name'] as String,
      arabicName: json['arabic_name'] as String?,
      nutrients: FoodNutrients.fromJson(
        json['nutrients_per_100g'] as Map<String, dynamic>? ?? <String, dynamic>{},
      ),
      portionLabel: json['portion_label'] as String?,
      portionGrams: (json['portion_grams'] as num?)?.toDouble(),
    ),
    nutrients: FoodNutrients.fromJson(
      json['nutrients'] as Map<String, dynamic>,
    ),
    grams: (json['grams'] as num? ?? 0).toDouble(),
    quantity: (json['quantity'] as num? ?? 0).toDouble(),
    unit: json['unit'] as String? ?? 'grams',
    mealLabel: json['meal_label'] as String,
    loggedTime: json['logged_time'] as String,
    mealSlot: json['meal_slot'] as String?,
    kind: json['kind'] as String? ?? 'library_food',
    blankMacros: <String>{
      for (final String key in <String>['protein_g', 'carbohydrate_g', 'fat_g'])
        if ((json['nutrients'] as Map<String, dynamic>)[key] == null) key,
    },
  );

  final String id;
  final FoodLibraryItem food;
  final FoodNutrients nutrients;
  final double grams;
  final double quantity;
  final String unit;
  final String mealLabel;
  final String loggedTime;
  final String? mealSlot;
  final String kind;
  final Set<String> blankMacros;
}

class FoodLogDay {
  const FoodLogDay({
    required this.date,
    required this.today,
    required this.editable,
    required this.entries,
    required this.totals,
    this.cardioBurnedKcal = 0,
    this.remaining,
    this.targets,
  });

  factory FoodLogDay.fromJson(Map<String, dynamic> json) => FoodLogDay(
    date: DateTime.parse(json['date'] as String),
    today: DateTime.parse(json['today'] as String),
    editable: json['editable'] == true,
    entries: (json['entries'] as List<dynamic>)
        .map(
          (dynamic entry) =>
              FoodLogEntry.fromJson(entry as Map<String, dynamic>),
        )
        .toList(),
    totals: FoodNutrients.fromJson(json['totals'] as Map<String, dynamic>),
    cardioBurnedKcal: (json['cardio_burned_kcal'] as num? ?? 0).toInt(),
    remaining: json['remaining'] == null
        ? null
        : FoodNutrients.fromJson(json['remaining'] as Map<String, dynamic>),
    targets: json['targets'] as Map<String, dynamic>?,
  );

  final DateTime date;
  final DateTime today;
  final bool editable;
  final List<FoodLogEntry> entries;
  final FoodNutrients totals;
  final int cardioBurnedKcal;
  final FoodNutrients? remaining;
  final Map<String, dynamic>? targets;
}
