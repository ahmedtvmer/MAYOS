import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/planned_meals_copy.dart';
import '../../../core/planned_meals_models.dart';
import '../../../core/food_swap_models.dart';
import '../../../core/display_language/food_swap_copy.dart';
import '../../../providers.dart';
import '../../../core/food_log_models.dart';
import '../../../core/theme/mayos_spacing.dart';
import 'nutrition_tile.dart';
import 'food_swap_sheet.dart';
import 'food_swap_requests.dart';
import '../../../core/display_language/food_swap_request_copy.dart';

class TodayMeals extends ConsumerStatefulWidget {
  const TodayMeals(
      {required this.onLogged,
      this.revision = 0,
      this.loggedEntries = const <FoodLogEntry>[],
      this.pastPlan,
      super.key});
  final VoidCallback onLogged;
  final int revision;
  final List<FoodLogEntry> loggedEntries;
  final PlannedMeals? pastPlan;

  @override
  ConsumerState<TodayMeals> createState() => _TodayMealsState();
}

class _TodayMealsState extends ConsumerState<TodayMeals> {
  PlannedMeals? _plan;
  String? _error;
  bool _busy = false;
  int _request = 0;
  bool _expanded = false;
  final Set<String> _loggedSlots = <String>{};

  @override
  void initState() {
    super.initState();
    if (widget.pastPlan != null) {
      _plan = widget.pastPlan;
    } else {
      _load();
    }
  }

  @override
  void didUpdateWidget(TodayMeals oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.pastPlan != null) {
      _plan = widget.pastPlan;
    } else if (oldWidget.revision != widget.revision) {
      _loggedSlots.clear();
      _load();
    }
  }

  Future<void> _load() async {
    final int request = ++_request;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final PlannedMeals plan =
          await ref.read(apiClientProvider).plannedMeals();
      if (mounted && request == _request)
        setState(() {
          if (_plan?.planVersionId != plan.planVersionId ||
              _plan?.date != plan.date) _loggedSlots.clear();
          _plan = plan;
        });
    } on ApiException catch (error) {
      if (mounted && request == _request)
        setState(() => _error = error.message);
    } finally {
      if (mounted && request == _request) setState(() => _busy = false);
    }
  }

  Future<void> _log(String slot, PlannedMealsCopy copy) async {
    if (_busy || _plan == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).logPlannedMeal(_plan!, slot);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.logged)));
      setState(() => _loggedSlots.add(slot));
      widget.onLogged();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _swap(PlannedMeal meal, PlannedFood food) async {
    final FoodSwapCopy copy = FoodSwapCopy(ref.read(displayLanguageProvider));
    final FoodSwapTarget target =
        FoodSwapTarget(plan: _plan!, slot: meal.slot, role: food.role);
    final bool? saved = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        isDismissible: false,
        enableDrag: false,
        builder: (_) => FoodSwapSheet(target: target));
    if (!mounted) return;
    if (saved == true)
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.saved)));
    await _load();
  }

  Future<void> _requestSwap(PlannedMeal meal, int foodIndex) async {
    final bool? sent = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => RequestFoodSwapDialog(
            plan: _plan!, meal: meal, foodIndex: foodIndex));
    if (!mounted || sent != true) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content:
            Text(FoodSwapRequestCopy(ref.read(displayLanguageProvider)).sent)));
  }

  @override
  Widget build(BuildContext context) {
    final PlannedMealsCopy copy =
        PlannedMealsCopy(ref.watch(displayLanguageProvider));
    if (_error == null &&
        (_plan == null || (_plan!.status != 'ready' && !_plan!.enabled))) {
      return const SizedBox.shrink();
    }
    return Padding(
        padding: const EdgeInsets.only(bottom: MayosSpacing.md),
        child: Directionality(
            textDirection: copy.arabic ? TextDirection.rtl : TextDirection.ltr,
            child: NutritionCard(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                  Row(children: <Widget>[
                    Expanded(
                        child: Text(copy.title,
                            style: Theme.of(context).textTheme.titleLarge)),
                    if (widget.pastPlan == null &&
                        _plan?.canRequestSwap == true)
                      const FoodSwapRequestsEntry(),
                  ]),
                  if (_busy) const LinearProgressIndicator(),
                  if (_error != null) ...<Widget>[
                    Text(_error!,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error)),
                    TextButton(
                        onPressed: _busy ? null : _load,
                        child: Text(copy.retry)),
                  ],
                  if (_plan != null) ..._contents(copy),
                ]))));
  }

  List<Widget> _contents(PlannedMealsCopy copy) {
    final PlannedMeals plan = _plan!;
    return <Widget>[
      if (plan.author == 'Coach') Text(copy.coach),
      if (plan.targetsChanged) Text(copy.targetsChanged),
      if (plan.status == 'unavailable')
        Text(plan.reason == 'targets'
            ? copy.targetsNeeded
            : plan.reason == 'coach'
                ? copy.coachTargetsOnly
                : copy.unavailable),
      if (plan.status == 'ready') ...<Widget>[
        Text(plan.dayType == 'training_day' ? copy.trainingDay : copy.restDay),
        for (final PlannedMeal meal
            in (_expanded ? plan.meals : plan.meals.take(2)))
          _meal(meal, copy),
        if (!_expanded && plan.meals.length > 2)
          TextButton(
              key: const Key('show_more_meals'),
              onPressed: () => setState(() => _expanded = true),
              child: Text(copy.showMore(plan.meals.length - 2))),
      ],
    ];
  }

  bool _isLogged(PlannedMeal meal) {
    if (_loggedSlots.contains(meal.slot)) return true;
    // A partial manually logged meal must not hide the rest of the plan.
    return meal.foods.isNotEmpty &&
        meal.foods.every((PlannedFood food) =>
            food.id.isNotEmpty &&
            widget.loggedEntries
                    .where((FoodLogEntry entry) =>
                        (entry.mealSlot ?? entry.mealLabel) == meal.slot &&
                        entry.food.id == food.id)
                    .fold<double>(
                        0,
                        (double grams, FoodLogEntry entry) =>
                            grams + entry.grams) >=
                food.grams);
  }

  Widget _meal(PlannedMeal meal, PlannedMealsCopy copy) {
    final String name = meal.name.isEmpty ? copy.slot(meal.slot) : meal.name;
    if (_isLogged(meal))
      return Padding(
          padding: const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
          child: Text(
              '$name · ${copy.calories(meal.calories)} ✓ ${copy.loggedLabel}',
              key: Key('logged_planned_${meal.slot}'),
              style: Theme.of(context).textTheme.titleSmall));
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
                '${meal.name.isEmpty ? copy.slot(meal.slot) : meal.name} · ${copy.calories(meal.calories)}',
                style: Theme.of(context).textTheme.titleMedium),
            if (meal.note.isNotEmpty) Text(meal.note),
            if (meal.targetDeviation.isNotEmpty)
              Text(copy.deviation(meal.targetDeviation)),
            for (final (int index, PlannedFood food) in meal.foods.indexed)
              Row(children: <Widget>[
                Expanded(
                    child: Text(
                        '${copy.arabic ? food.arabicName ?? food.name : food.name} · ${copy.amount(food.grams)}'
                        '${food.portionGrams == null ? '' : ' (${(food.grams / food.portionGrams!).toStringAsFixed(1)} ${food.portionLabel})'}')),
                if (widget.pastPlan == null &&
                    _plan!.canSwap &&
                    _plan!.author == 'Player' &&
                    food.role.isNotEmpty)
                  IconButton(
                      key: Key('swap_${meal.slot}_${food.role}'),
                      tooltip: FoodSwapCopy(copy.language).swap,
                      onPressed: _busy ? null : () => _swap(meal, food),
                      icon: const Icon(Icons.swap_horiz)),
                if (widget.pastPlan == null && _plan!.canRequestSwap)
                  IconButton(
                      key: Key('request_swap_${meal.slot}_$index'),
                      tooltip: FoodSwapRequestCopy(copy.language).request,
                      onPressed: _busy ? null : () => _requestSwap(meal, index),
                      icon: const Icon(Icons.question_answer_outlined)),
              ]),
            if (widget.pastPlan == null)
              OutlinedButton(
                  key: Key('log_planned_${meal.slot}'),
                  onPressed: _busy ? null : () => _log(meal.slot, copy),
                  child: Text(copy.logMeal(name))),
          ]),
    );
  }
}
