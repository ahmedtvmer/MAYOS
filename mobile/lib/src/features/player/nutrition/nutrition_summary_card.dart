import 'package:flutter/material.dart';

import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../core/theme/mayos_spacing.dart';
import 'nutrition_tile.dart';

class NutritionSummaryCard extends StatelessWidget {
  const NutritionSummaryCard(
      {required this.day, required this.copy, super.key});
  final FoodLogDay day;
  final FoodLogCopy copy;

  @override
  Widget build(BuildContext context) {
    final Map<String, dynamic> targets = day.targets ?? <String, dynamic>{};
    final double calories = (targets['calories'] as num? ?? 0).toDouble();
    final double left = calories - day.totals.kcal;
    final bool today = day.date == day.today;
    final bool hasTargets = day.targets != null;
    final ColorScheme colors = Theme.of(context).colorScheme;
    return NutritionCard(
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
          Text(
              '${hasTargets && today && left >= 0 ? left.round() : day.totals.kcal.round()}',
              style: Theme.of(context).textTheme.displaySmall),
          Text(!hasTargets
              ? copy.caloriesEaten
              : today && left >= 0
                  ? copy.leftOf(calories)
                  : copy.eatenOf(calories)),
          if (hasTargets && left < 0) Text(copy.caloriesOver(-left)),
          const SizedBox(height: MayosSpacing.sm),
          LinearProgressIndicator(
              value: calories <= 0
                  ? 0
                  : (day.totals.kcal / calories).clamp(0.0, 1.0),
              borderRadius: MayosRadii.pillRadius),
          const SizedBox(height: MayosSpacing.md),
          NutritionTileRow(tiles: <NutritionTile>[
            _macro(
                copy.protein, 'protein_g', day.totals.protein, colors.primary),
            _macro(
                copy.carbsShort, 'carbs_g', day.totals.carbs, colors.tertiary),
            _macro(copy.fat, 'fat_g', day.totals.fat, colors.secondary),
          ]),
          if (day.cardioBurnedKcal > 0) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(copy.cardioBurned(day.cardioBurnedKcal),
                style: Theme.of(context).textTheme.bodySmall),
          ],
        ]));
  }

  NutritionTile _macro(String label, String key, double eaten, Color color) {
    final double target = (day.targets?[key] as num? ?? 0).toDouble();
    final double left = target - eaten;
    return NutritionTile(
        label: label,
        color: color,
        amount: day.targets == null
            ? copy.fiberValue(eaten.round())
            : day.date == day.today
                ? copy.gramsRemaining(left)
                : copy.gramsEaten(eaten, target),
        progress: target <= 0 ? 0 : eaten / target);
  }
}
