import 'food_log_models.dart';
import 'planned_meals_models.dart';

class FoodSwapTarget {
  const FoodSwapTarget({required this.plan, required this.slot, required this.role});
  final PlannedMeals plan;
  final String slot;
  final String role;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'plan_version_id': plan.planVersionId, 'day_type': plan.dayType,
    'slot': slot, 'role': role,
  };
}

class FoodSwapCandidate {
  const FoodSwapCandidate({required this.food, required this.allowed,
    this.grams, this.calories, this.protein});
  factory FoodSwapCandidate.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic>? totals = json['totals'] as Map<String, dynamic>?;
    final bool allowed = json['allowed'] as bool;
    return FoodSwapCandidate(
      food: FoodLibraryItem.fromJson(json['food'] as Map<String, dynamic>),
      allowed: allowed,
      grams: allowed ? (json['grams'] as num).toDouble() : null,
      calories: allowed ? (totals!['calories'] as num).toDouble() : null,
      protein: allowed ? (totals!['protein_g'] as num).toDouble() : null,
    );
  }
  final FoodLibraryItem food;
  final bool allowed;
  final double? grams;
  final double? calories;
  final double? protein;
}

class FoodSwapCandidates {
  const FoodSwapCandidates({required this.staples, required this.search});
  factory FoodSwapCandidates.fromJson(Map<String, dynamic> json) => FoodSwapCandidates(
    staples: (json['staples'] as List<dynamic>)
      .map((dynamic food) => FoodSwapCandidate.fromJson(food as Map<String, dynamic>)).toList(),
    search: (json['search'] as List<dynamic>)
      .map((dynamic food) => FoodSwapCandidate.fromJson(food as Map<String, dynamic>)).toList(),
  );
  final List<FoodSwapCandidate> staples;
  final List<FoodSwapCandidate> search;
}
