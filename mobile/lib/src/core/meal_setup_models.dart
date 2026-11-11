class MealSetupState {
  const MealSetupState({required this.mealCount, required this.trainingTime,
    required this.allergies, required this.vegetarian, required this.dislikes});

  factory MealSetupState.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> restrictions = json['restrictions'] as Map<String, dynamic>;
    final Map<String, Map<String, dynamic>> names = <String, Map<String, dynamic>>{
      for (final Map<String, dynamic> food in
          (json['disliked_foods'] as List<dynamic>? ?? <dynamic>[]).cast<Map<String, dynamic>>())
        food['id'] as String: food,
    };
    return MealSetupState(mealCount: (json['meal_count'] as num).toInt(),
      trainingTime: json['training_time'] as String,
      allergies: (restrictions['allergies'] as List<dynamic>).cast<String>().toSet(),
      vegetarian: restrictions['vegetarian'] as bool,
      dislikes: <String, Map<String, dynamic>>{
        for (final String id in (restrictions['dislikes'] as List<dynamic>).cast<String>())
          id: names[id] ?? <String, dynamic>{'id': id, 'name': id},
      });
  }

  final int mealCount;
  final String trainingTime;
  final Set<String> allergies;
  final bool vegetarian;
  final Map<String, Map<String, dynamic>> dislikes;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'meal_count': mealCount, 'training_time': trainingTime,
    'restrictions': <String, dynamic>{'allergies': allergies.toList(),
      'vegetarian': vegetarian, 'dislikes': dislikes.keys.toList()},
  };
}
