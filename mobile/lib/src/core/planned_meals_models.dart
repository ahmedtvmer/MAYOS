class PlannedMeals {
  const PlannedMeals({required this.status, required this.meals,
    this.reason, this.date, this.planVersionId, this.author,
    this.canEnable = false, this.canSwap = false, this.targetsChanged = false, this.dayType});

  factory PlannedMeals.fromJson(Map<String, dynamic> json) => PlannedMeals(
    status: json['status'] as String,
    reason: json['reason'] as String?,
    date: json['date'] as String?,
    planVersionId: (json['plan_version_id'] as num?)?.toInt(),
    author: json['author'] as String?,
    canEnable: json['can_enable'] as bool? ?? false,
    canSwap: json['can_swap'] as bool? ?? false,
    targetsChanged: json['targets_changed'] as bool? ?? false,
    dayType: json['day_type'] as String?,
    meals: (json['meals'] as List<dynamic>? ?? <dynamic>[])
      .map((dynamic meal) => PlannedMeal.fromJson(meal as Map<String, dynamic>)).toList(),
  );

  final String status;
  final String? reason;
  final String? date;
  final int? planVersionId;
  final String? author;
  final bool canEnable;
  final bool canSwap;
  final bool targetsChanged;
  final String? dayType;
  final List<PlannedMeal> meals;
}

class PlannedMeal {
  const PlannedMeal({required this.slot, required this.foods, required this.calories});
  factory PlannedMeal.fromJson(Map<String, dynamic> json) => PlannedMeal(
    slot: json['slot'] as String,
    foods: (json['foods'] as List<dynamic>)
      .map((dynamic food) => PlannedFood.fromJson(food as Map<String, dynamic>)).toList(),
    calories: (json['totals']['calories'] as num).toDouble(),
  );
  final String slot;
  final List<PlannedFood> foods;
  final double calories;
}

class PlannedFood {
  const PlannedFood({required this.name, required this.grams, this.arabicName,
    this.portionLabel, this.portionGrams, this.id = '', this.role = ''});
  factory PlannedFood.fromJson(Map<String, dynamic> json) => PlannedFood(
    name: json['name'] as String, arabicName: json['arabic_name'] as String?,
    id: json['id'] as String? ?? '', role: json['role'] as String? ?? '',
    grams: (json['grams'] as num).toDouble(),
    portionLabel: json['portion_label'] as String?,
    portionGrams: (json['portion_grams'] as num?)?.toDouble(),
  );
  final String name;
  final String id;
  final String role;
  final String? arabicName;
  final double grams;
  final String? portionLabel;
  final double? portionGrams;
}
