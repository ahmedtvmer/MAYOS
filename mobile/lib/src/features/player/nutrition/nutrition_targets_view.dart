import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import 'food_swap_requests.dart';
import 'meal_setup_screen.dart';
import 'nutrition_tile.dart';

class NutritionTargetsView extends StatelessWidget {
  const NutritionTargetsView(
      {required this.plan,
      required this.copy,
      required this.offers,
      required this.onAdjust,
      required this.onActivity,
      super.key});
  final NutritionPlanState plan;
  final NutritionCopy copy;
  final Widget offers;
  final VoidCallback? onAdjust;
  final VoidCallback? onActivity;

  Map<String, dynamic> get _targets => plan.targets ?? <String, dynamic>{};
  double _amount(String key) => (_targets[key] as num? ?? 0).toDouble();

  @override
  Widget build(BuildContext context) => ListView(
        key: const Key('nutrition_targets_list'),
        padding: const EdgeInsets.all(MayosSpacing.md),
        children: <Widget>[
          offers,
          _goal(context),
          const SizedBox(height: MayosSpacing.md),
          _calories(context),
          const SizedBox(height: MayosSpacing.md),
          Text(copy.macrosTitle,
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: MayosSpacing.xs),
          _macros(context),
          const SizedBox(height: MayosSpacing.xs),
          NutritionTileRow(tiles: <NutritionTile>[
            NutritionTile(
                label: copy.coachFiber,
                amount: copy.fiberValue(_amount('fiber_g').round())),
            NutritionTile(
                label: copy.coachWater,
                amount: copy.waterPrescription(_amount('water_ml').round())),
          ]),
          const SizedBox(height: MayosSpacing.md),
          Text(copy.cardioNote, style: Theme.of(context).textTheme.bodySmall),
          if (plan.cardioBurnedKcal > 0)
            Text(copy.cardioBurned(plan.cardioBurnedKcal)),
          if (plan.cardioAdjustmentKcal > 0)
            Text(copy.cardioAdjustment(plan.cardioAdjustmentKcal)),
          const SizedBox(height: MayosSpacing.md),
          _settings(context),
          const SizedBox(height: MayosSpacing.md),
          _weight(context),
        ],
      );

  Widget _goal(BuildContext context) => NutritionCard(
          child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(copy.coachGoal, style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: MayosSpacing.xs),
          Text(copy.stop(plan.goal ?? 'maintain', plan.intensity ?? 'moderate'),
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: MayosSpacing.xs),
          Text(copy.goalReason(plan.goalReason)),
          if (plan.authority == 'coach')
            Align(
                alignment: AlignmentDirectional.centerStart,
                child: Chip(label: Text(copy.setByCoach))),
          if (plan.authority != 'coach')
            Align(
                alignment: AlignmentDirectional.centerEnd,
                child: OutlinedButton.icon(
                    onPressed: onAdjust,
                    icon: const Icon(Icons.tune),
                    label: Text(copy.adjust))),
        ],
      ));

  List<(String, String, Color, int)> _macroSpecs(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return <(String, String, Color, int)>[
      (copy.protein, 'protein_g', colors.primary, 4),
      (copy.carbsShort, 'carbs_g', colors.tertiary, 4),
      (copy.fat, 'fat_g', colors.secondary, 9),
    ];
  }

  Widget _macros(BuildContext context) =>
      NutritionTileRow(tiles: <NutritionTile>[
        for (final macro in _macroSpecs(context))
          NutritionTile(
              label: macro.$1,
              amount: copy.fiberValue(_amount(macro.$2).round()),
              color: macro.$3,
              detail:
                  '${(_amount(macro.$2) * macro.$4).round()} ${copy.calories}'),
      ]);

  Widget _calories(BuildContext context) {
    final macros = _macroSpecs(context);
    return NutritionCard(
        child: Column(children: <Widget>[
      SizedBox(
          height: 210,
          child: Center(
              child: CustomPaint(
            size: const Size.square(200),
            painter: _CaloriesPainter(macros.map((macro) => macro.$3).toList(),
                macros.map((macro) => _amount(macro.$2) * macro.$4).toList()),
            child: SizedBox(
                width: 200,
                height: 200,
                child: Center(
                    child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Text('${_amount('calories').round()}',
                        style: Theme.of(context).textTheme.headlineLarge),
                    Text(copy.calories),
                  ],
                ))),
          ))),
      Wrap(
          alignment: WrapAlignment.center,
          spacing: MayosSpacing.md,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (final macro in macros)
              Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
                Icon(Icons.circle, size: 10, color: macro.$3),
                const SizedBox(width: MayosSpacing.xxs),
                Text(macro.$1),
              ]),
          ]),
    ]));
  }

  void _mealSetup(BuildContext context) => Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(builder: (_) => const MealSetupScreen()));

  Widget _settings(BuildContext context) => NutritionCard(
          child: Column(children: <Widget>[
        ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.directions_walk),
            title: Text(copy.dailyActivity),
            subtitle: Text(copy.activityLabel(plan.dailyActivity)),
            trailing: plan.authority == 'coach'
                ? null
                : const Icon(Icons.edit_outlined),
            onTap: onActivity),
        const Divider(),
        Row(children: <Widget>[
          Expanded(
              child: ListTile(
                  key: const Key('meal_setup_entry'),
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.restaurant_menu),
                  title: Text(copy.meals),
                  onTap: () => _mealSetup(context),
                  trailing: Icon(copy.isArabic
                      ? Icons.chevron_left
                      : Icons.chevron_right))),
          const FoodSwapRequestsEntry(),
        ]),
        const Divider(),
        ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.no_food_outlined),
            title: Text(copy.foodRestrictions),
            onTap: () => _mealSetup(context),
            trailing:
                Icon(copy.isArabic ? Icons.chevron_left : Icons.chevron_right)),
      ]));

  Widget _weight(BuildContext context) => NutritionCard(
          child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(copy.weight, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: MayosSpacing.sm),
          NutritionTileRow(tiles: <NutritionTile>[
            NutritionTile(
                label: copy.latest, amount: _weightLabel(plan.latestWeight)),
            NutritionTile(
                label: copy.target, amount: _weightLabel(plan.targetWeight)),
          ]),
        ],
      ));

  String _weightLabel(double? kilograms) =>
      kilograms == null ? '—' : '$kilograms ${copy.kilograms}';
}

class _CaloriesPainter extends CustomPainter {
  const _CaloriesPainter(this.colors, this.calories);
  final List<Color> colors;
  final List<double> calories;

  @override
  void paint(Canvas canvas, Size size) {
    final Paint paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 18;
    final double total =
        calories.fold<double>(0, (double sum, double amount) => sum + amount);
    double start = -math.pi / 2;
    for (int index = 0; index < colors.length; index++) {
      paint.color = colors[index];
      final double sweep =
          total <= 0 ? 0 : math.pi * 2 * calories[index] / total;
      canvas.drawArc(
          (Offset.zero & size).deflate(12), start, sweep, false, paint);
      start += sweep;
    }
  }

  @override
  bool shouldRepaint(_CaloriesPainter oldDelegate) =>
      oldDelegate.colors != colors || oldDelegate.calories != calories;
}
