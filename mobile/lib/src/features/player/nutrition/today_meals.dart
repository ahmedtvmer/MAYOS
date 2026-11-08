import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/planned_meals_copy.dart';
import '../../../core/planned_meals_models.dart';
import '../../../providers.dart';
import 'meal_setup_screen.dart';

class TodayMeals extends ConsumerStatefulWidget {
  const TodayMeals({required this.onLogged, this.revision = 0, super.key});
  final VoidCallback onLogged;
  final int revision;

  @override
  ConsumerState<TodayMeals> createState() => _TodayMealsState();
}

class _TodayMealsState extends ConsumerState<TodayMeals> {
  PlannedMeals? _plan;
  String? _error;
  bool _busy = false;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(TodayMeals oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.revision != widget.revision) _load();
  }

  Future<void> _load({bool enable = false}) async {
    final int request = ++_request;
    setState(() { _busy = true; _error = null; });
    try {
      final PlannedMeals plan = await ref.read(apiClientProvider).plannedMeals(enable: enable);
      if (mounted && request == _request) setState(() => _plan = plan);
    } on ApiException catch (error) {
      if (mounted && request == _request) setState(() => _error = error.message);
    } finally {
      if (mounted && request == _request) setState(() => _busy = false);
    }
  }

  Future<void> _log(String slot, PlannedMealsCopy copy) async {
    if (_busy || _plan == null) return;
    setState(() { _busy = true; _error = null; });
    try {
      await ref.read(apiClientProvider).logPlannedMeal(_plan!, slot);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(copy.logged)));
      widget.onLogged();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _setup() async {
    await Navigator.of(context).push<bool>(MaterialPageRoute<bool>(builder: (_) => const MealSetupScreen()));
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final PlannedMealsCopy copy = PlannedMealsCopy(ref.watch(displayLanguageProvider));
    return Directionality(textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
      child: Card(child: Padding(padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
          Text(copy.title, style: Theme.of(context).textTheme.titleLarge),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) ...<Widget>[
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            TextButton(onPressed: _busy ? null : _load, child: Text(copy.retry)),
          ],
          if (_plan != null) ..._contents(copy),
        ]))));
  }

  List<Widget> _contents(PlannedMealsCopy copy) {
    final PlannedMeals plan = _plan!;
    return <Widget>[
      if (plan.author == 'Coach') Text(copy.coach),
      if (plan.targetsChanged) Text(copy.targetsChanged),
      if (plan.status == 'unavailable') Text(plan.reason == 'targets' ? copy.targetsNeeded : copy.unavailable),
      if (plan.status == 'disabled') ...<Widget>[
        Text(copy.introduction),
        if (plan.canEnable) FilledButton(key: const Key('enable_meals'),
          onPressed: _busy ? null : () => _load(enable: true), child: Text(copy.turnOn)),
      ],
      if (plan.status == 'ready') ...<Widget>[
        Text(plan.dayType == 'training_day' ? copy.trainingDay : copy.restDay),
        for (final PlannedMeal meal in plan.meals) _meal(meal, copy),
      ],
      TextButton(onPressed: _busy ? null : _setup, child: Text(copy.setup)),
    ];
  }

  Widget _meal(PlannedMeal meal, PlannedMealsCopy copy) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: <Widget>[
      Text('${copy.slot(meal.slot)} · ${copy.calories(meal.calories)}',
        style: Theme.of(context).textTheme.titleMedium),
      for (final PlannedFood food in meal.foods)
        Text('${copy.arabic ? food.arabicName ?? food.name : food.name} · ${copy.amount(food.grams)}'
          '${food.portionGrams == null ? '' : ' (${(food.grams / food.portionGrams!).toStringAsFixed(1)} ${food.portionLabel})'}'),
      OutlinedButton(key: Key('log_planned_${meal.slot}'),
        onPressed: _busy ? null : () => _log(meal.slot, copy), child: Text(copy.log)),
    ]),
  );
}
