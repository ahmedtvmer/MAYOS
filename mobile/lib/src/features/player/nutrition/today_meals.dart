import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_swap_copy.dart';
import '../../../core/display_language/food_swap_request_copy.dart';
import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/display_language/planned_meals_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../core/food_swap_models.dart';
import '../../../core/planned_meals_models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../providers.dart';
import 'food_swap_requests.dart';
import 'food_swap_sheet.dart';
import 'nutrition_tile.dart';

class TodayMeals extends ConsumerStatefulWidget {
  const TodayMeals({
    required this.onLogged,
    this.revision = 0,
    this.loggedEntries = const <FoodLogEntry>[],
    this.pastPlan,
    super.key,
  });

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
  bool _syncingTableScroll = false;
  int _request = 0;
  final Set<String> _loggedSlots = <String>{};
  final Map<String, ScrollController> _tableScrollControllers =
      <String, ScrollController>{};

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

  @override
  void dispose() {
    for (final ScrollController controller in _tableScrollControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final int request = ++_request;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final PlannedMeals plan = await ref
          .read(apiClientProvider)
          .plannedMeals();
      if (mounted && request == _request) {
        setState(() {
          if (_plan?.planVersionId != plan.planVersionId ||
              _plan?.date != plan.date) {
            _loggedSlots.clear();
          }
          _plan = plan;
        });
      }
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
    final FoodSwapTarget target = FoodSwapTarget(
      plan: _plan!,
      slot: meal.slot,
      role: food.role,
    );
    final bool? saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      isDismissible: false,
      enableDrag: false,
      builder: (_) => FoodSwapSheet(target: target),
    );
    if (!mounted) return;
    if (saved == true) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.saved)));
    }
    await _load();
  }

  Future<void> _requestSwap(PlannedMeal meal, int foodIndex) async {
    final bool? sent = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) =>
          RequestFoodSwapDialog(plan: _plan!, meal: meal, foodIndex: foodIndex),
    );
    if (!mounted || sent != true) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          FoodSwapRequestCopy(ref.read(displayLanguageProvider)).sent,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final PlannedMealsCopy copy = PlannedMealsCopy(
      ref.watch(displayLanguageProvider),
    );
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
              Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      copy.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  if (widget.pastPlan == null && _plan?.canRequestSwap == true)
                    const FoodSwapRequestsEntry(),
                ],
              ),
              if (_busy) const LinearProgressIndicator(),
              if (_error != null) ...<Widget>[
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                TextButton(
                  onPressed: _busy ? null : _load,
                  child: Text(copy.retry),
                ),
              ],
              if (_plan != null) ..._contents(copy),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _contents(PlannedMealsCopy copy) {
    final PlannedMeals plan = _plan!;
    final List<Widget> contents = _planNotices(plan, copy);
    if (plan.status == 'ready') contents.addAll(_tableContents(plan, copy));
    return contents;
  }

  List<Widget> _planNotices(PlannedMeals plan, PlannedMealsCopy copy) =>
      <Widget>[
        if (plan.author == 'Coach' && plan.status != 'ready') Text(copy.coach),
        if (plan.targetsChanged) Text(copy.targetsChanged),
        if (plan.status == 'unavailable')
          Text(
            plan.reason == 'targets'
                ? copy.targetsNeeded
                : plan.reason == 'coach'
                ? copy.coachTargetsOnly
                : copy.unavailable,
          ),
      ];

  List<Widget> _tableContents(
    PlannedMeals plan,
    PlannedMealsCopy copy,
  ) => <Widget>[
    if (plan.author == 'Coach') Text(copy.coach),
    Text(plan.dayType == 'training_day' ? copy.trainingDay : copy.restDay),
    if (plan.author == 'Player') ..._playerMealNotes(plan, copy),
    for (final PlannedMeal meal in plan.meals) ..._mealNotes(plan, meal, copy),
    const SizedBox(height: MayosSpacing.xs),
    _mealTable(plan, copy),
  ];

  List<Widget> _playerMealNotes(
    PlannedMeals plan,
    PlannedMealsCopy copy,
  ) => <Widget>[
    if (plan.gapNote[copy.language] != null) Text(plan.gapNote[copy.language]!),
    Text(copy.cookedWeights),
    if (widget.pastPlan == null) Text(copy.swapHint),
  ];

  List<Widget> _mealNotes(
    PlannedMeals plan,
    PlannedMeal meal,
    PlannedMealsCopy copy,
  ) => <Widget>[
    if (meal.note.isNotEmpty) Text(meal.note),
    if (plan.author == 'Coach' && meal.targetDeviation.isNotEmpty)
      Text(copy.deviation(meal.targetDeviation)),
  ];

  bool _isLogged(PlannedMeal meal) {
    if (_loggedSlots.contains(meal.slot)) return true;
    return meal.foods.isNotEmpty &&
        meal.foods.every(
          (PlannedFood food) =>
              food.id.isNotEmpty &&
              widget.loggedEntries
                      .where(
                        (FoodLogEntry entry) =>
                            (entry.mealSlot ?? entry.mealLabel) == meal.slot &&
                            entry.food.id == food.id,
                      )
                      .fold<double>(
                        0,
                        (double grams, FoodLogEntry entry) =>
                            grams + entry.grams,
                      ) >=
                  food.grams,
        );
  }

  Widget _mealTable(PlannedMeals plan, PlannedMealsCopy copy) {
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final double foodWidth = _foodColumnWidth(constraints.maxWidth);
        final double numberWidth = _numberColumnWidth(
          constraints.maxWidth,
          foodWidth,
        );
        final List<String> columns = _columnNames(copy);
        return Column(
          children: <Widget>[
            _tableRow(_headerRow(copy), foodWidth, numberWidth, columns),
            for (final _MealTableRow row in _mealRows(plan, copy))
              _tableRow(row, foodWidth, numberWidth, columns),
            _tableRow(_dayTotalRow(plan, copy), foodWidth, numberWidth, columns),
            _tableRow(_targetRow(plan, copy), foodWidth, numberWidth, columns),
          ],
        );
      },
    );
  }

  /// Spoken names of the number columns, so a screen reader says
  /// "Protein: 30" instead of a bare number (#753).
  List<String> _columnNames(PlannedMealsCopy copy) {
    final NutritionCopy nutrition = NutritionCopy(copy.language);
    return <String>[
      copy.amountColumn,
      nutrition.calories,
      nutrition.protein,
      nutrition.carbsShort,
      nutrition.fat,
    ];
  }

  double _foodColumnWidth(double tableWidth) => tableWidth < 170
      ? tableWidth
      : (tableWidth * 0.52).clamp(170.0, 220.0).toDouble();

  double _numberColumnWidth(double tableWidth, double foodWidth) =>
      (tableWidth - foodWidth).clamp(340.0, double.infinity) / 5;

  _MealTableRow _headerRow(PlannedMealsCopy copy) => _MealTableRow(
    id: 'header',
    food: Text(
      copy.foodColumn,
      style: Theme.of(context).textTheme.labelLarge
          ?.copyWith(fontWeight: FontWeight.bold),
    ),
    values: <String>[copy.amountColumn, 'kcal', 'P', 'C', 'F'],
    kind: _MealTableRowKind.header,
  );

  Iterable<_MealTableRow> _mealRows(
    PlannedMeals plan,
    PlannedMealsCopy copy,
  ) sync* {
    for (final PlannedMeal meal in plan.meals) {
      yield _mealSummaryRow(meal, copy);
      for (final (int index, PlannedFood food) in meal.foods.indexed) {
        yield _foodRow(meal, food, index, copy);
      }
    }
  }

  _MealTableRow _mealSummaryRow(PlannedMeal meal, PlannedMealsCopy copy) =>
      _MealTableRow(
        id: 'meal_${meal.slot}',
        food: _mealCell(meal, copy),
        values: <String>['', ..._macroValues(meal.totals)],
        kind: _MealTableRowKind.meal,
        // A logged meal's summary row is muted like its foods (#753).
        muted: _isLogged(meal),
      );

  _MealTableRow _foodRow(
    PlannedMeal meal,
    PlannedFood food,
    int index,
    PlannedMealsCopy copy,
  ) => _MealTableRow(
    id: 'food_${meal.slot}_$index',
    food: _foodCell(meal, food, index, copy),
    values: <String>[
      copy.foodAmount(food.grams, food.portionLabel, food.portionGrams),
      ..._macroValues(food.macros),
    ],
    kind: _MealTableRowKind.food,
    muted: _isLogged(meal),
  );

  _MealTableRow _dayTotalRow(PlannedMeals plan, PlannedMealsCopy copy) =>
      _MealTableRow(
        id: 'day_total',
        food: Text(
          copy.dayTotal,
          style: Theme.of(context).textTheme.titleSmall
              ?.copyWith(fontWeight: FontWeight.bold),
        ),
        values: <String>['', ..._macroValues(plan.dayTotals)],
        kind: _MealTableRowKind.total,
      );

  _MealTableRow _targetRow(PlannedMeals plan, PlannedMealsCopy copy) {
    return _MealTableRow(
      id: 'target',
      food: Text(
        copy.target,
        style: Theme.of(context).textTheme.bodyMedium
            ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
      ),
      values: <String>['', ..._macroValues(plan.targets)],
      kind: _MealTableRowKind.target,
      muted: true,
    );
  }

  Widget _mealCell(PlannedMeal meal, PlannedMealsCopy copy) => Row(
    crossAxisAlignment: CrossAxisAlignment.center,
    children: <Widget>[
      Expanded(
        child: Text(
          _mealName(meal, copy),
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.bold,
            color: _isLogged(meal)
                ? Theme.of(context).colorScheme.onSurfaceVariant
                : null,
          ),
        ),
      ),
      if (_isLogged(meal))
        _loggedMealLabel(meal, copy)
      else if (widget.pastPlan == null)
        _logMealButton(meal, copy),
    ],
  );

  Widget _loggedMealLabel(PlannedMeal meal, PlannedMealsCopy copy) => Container(
    key: Key('logged_planned_${meal.slot}'),
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Text(
      '✓ ${copy.loggedLabel}',
      style: Theme.of(context).textTheme.labelMedium
          ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
    ),
  );

  Widget _logMealButton(PlannedMeal meal, PlannedMealsCopy copy) => Tooltip(
    message: copy.logMeal(_mealName(meal, copy)),
    child: OutlinedButton(
      key: Key('log_planned_${meal.slot}'),
      onPressed: _busy ? null : () => _log(meal.slot, copy),
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      child: Text(copy.logAction),
    ),
  );

  Widget _foodCell(
    PlannedMeal meal,
    PlannedFood food,
    int foodIndex,
    PlannedMealsCopy copy,
  ) {
    final Widget? action = _foodActionFor(meal, food, foodIndex, copy);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: <Widget>[
        Expanded(child: _foodName(meal, food, copy)),
        if (action != null) action,
      ],
    );
  }

  Widget _foodName(PlannedMeal meal, PlannedFood food, PlannedMealsCopy copy) =>
      Text(
        copy.arabic ? food.arabicName ?? food.name : food.name,
        style: _isLogged(meal)
            ? TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant
                    .withValues(alpha: 0.7),
              )
            : null,
      );

  Widget? _foodActionFor(
    PlannedMeal meal,
    PlannedFood food,
    int foodIndex,
    PlannedMealsCopy copy,
  ) {
    if (_canSwapFood(meal, food)) {
      return _foodAction(
        key: Key('swap_${meal.slot}_${food.role}'),
        tooltip: FoodSwapCopy(copy.language).swap,
        icon: Icons.swap_horiz,
        onPressed: _busy ? null : () => _swap(meal, food),
      );
    }
    if (_canRequestFoodSwap(meal)) {
      return _foodAction(
        key: Key('request_swap_${meal.slot}_$foodIndex'),
        tooltip: FoodSwapRequestCopy(copy.language).request,
        icon: Icons.swap_horiz,
        onPressed: _busy ? null : () => _requestSwap(meal, foodIndex),
      );
    }
    return null;
  }

  bool _canSwapFood(PlannedMeal meal, PlannedFood food) =>
      !_isLogged(meal) &&
      widget.pastPlan == null &&
      _plan!.canSwap &&
      _plan!.author == 'Player' &&
      food.role.isNotEmpty;

  bool _canRequestFoodSwap(PlannedMeal meal) =>
      !_isLogged(meal) && widget.pastPlan == null && _plan!.canRequestSwap;

  Widget _foodAction({
    required Key key,
    required String tooltip,
    required IconData icon,
    required VoidCallback? onPressed,
  }) => IconButton(
    key: key,
    tooltip: tooltip,
    onPressed: onPressed,
    constraints: const BoxConstraints.tightFor(width: 44, height: 44),
    padding: EdgeInsets.zero,
    style: IconButton.styleFrom(
      backgroundColor: Theme.of(context).colorScheme.primaryContainer,
      foregroundColor: Theme.of(context).colorScheme.onPrimaryContainer,
      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
    ),
    icon: Icon(icon, size: 18),
  );

  Widget _tableRow(
    _MealTableRow row,
    double foodWidth,
    double numberWidth,
    List<String> columns,
  ) =>
      Container(
        key: Key('planned_meals_row_${row.id}'),
        decoration: _rowDecoration(row),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            _fixedFoodCell(row, foodWidth),
            Expanded(child: _scrollingNumberCells(row, numberWidth, columns)),
          ],
        ),
      );

  BoxDecoration _rowDecoration(_MealTableRow row) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final Color background =
        row.kind == _MealTableRowKind.header ||
            row.kind == _MealTableRowKind.total
        ? colors.surfaceContainerHighest
        : Colors.transparent;
    return BoxDecoration(
      color: background,
      border: Border(
        bottom: BorderSide(color: Theme.of(context).dividerColor),
        top: row.kind == _MealTableRowKind.header
            ? BorderSide(color: Theme.of(context).dividerColor)
            : BorderSide.none,
      ),
    );
  }

  Widget _fixedFoodCell(_MealTableRow row, double width) => SizedBox(
    key: Key('planned_meals_food_${row.id}'),
    width: width,
    child: Padding(
      padding: EdgeInsetsDirectional.only(
        // Food rows sit indented under their meal (#753).
        start: row.kind == _MealTableRowKind.food
            ? MayosSpacing.xs + MayosSpacing.md
            : MayosSpacing.xs,
        end: MayosSpacing.xs,
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xs,
      ),
      child: row.food,
    ),
  );

  Widget _scrollingNumberCells(
    _MealTableRow row,
    double width,
    List<String> columns,
  ) {
    final TextStyle? style =
        (row.kind == _MealTableRowKind.header
                ? Theme.of(context).textTheme.labelLarge
                : Theme.of(context).textTheme.bodyMedium)
            ?.copyWith(
              fontWeight: row.bold ? FontWeight.bold : FontWeight.normal,
              color: row.muted
                  ? Theme.of(context).colorScheme.onSurfaceVariant
                  : null,
            );
    return NotificationListener<ScrollNotification>(
      onNotification: (ScrollNotification notification) =>
          _syncTableScroll(row.id, notification),
      child: SingleChildScrollView(
        key: Key('planned_meals_numbers_${row.id}'),
        controller: _tableScrollController(row.id),
        scrollDirection: Axis.horizontal,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            for (final (int index, String value) in row.values.indexed)
              _numberCell(
                value,
                width,
                style,
                label: row.kind == _MealTableRowKind.header || value.isEmpty
                    ? null
                    : '${columns[index]}: $value',
              ),
          ],
        ),
      ),
    );
  }

  Widget _numberCell(
    String value,
    double width,
    TextStyle? style, {
    String? label,
  }) {
    final Widget cell = SizedBox(
      width: width,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.xxs,
          vertical: MayosSpacing.xs,
        ),
        child: Center(
          child: Text(value, textAlign: TextAlign.center, style: style),
        ),
      ),
    );
    return label == null
        ? cell
        : Semantics(label: label, excludeSemantics: true, child: cell);
  }

  ScrollController _tableScrollController(String rowId) =>
      _tableScrollControllers.putIfAbsent(rowId, ScrollController.new);

  bool _syncTableScroll(String sourceId, ScrollNotification notification) {
    if (notification is! ScrollUpdateNotification ||
        notification.metrics.axis != Axis.horizontal ||
        _syncingTableScroll) {
      return false;
    }
    _syncingTableScroll = true;
    try {
      _moveOtherTableScrolls(sourceId, notification.metrics.pixels);
    } finally {
      _syncingTableScroll = false;
    }
    return false;
  }

  void _moveOtherTableScrolls(String sourceId, double pixels) {
    for (final MapEntry<String, ScrollController> entry
        in _tableScrollControllers.entries) {
      if (entry.key != sourceId) _moveTableScroll(entry.value, pixels);
    }
  }

  void _moveTableScroll(ScrollController controller, double pixels) {
    if (!controller.hasClients || !controller.position.hasContentDimensions)
      return;
    final ScrollPosition position = controller.position;
    final double target = pixels
        .clamp(position.minScrollExtent, position.maxScrollExtent)
        .toDouble();
    if (position.pixels != target) controller.jumpTo(target);
  }

  List<String> _macroValues(PlannedMacros macros) => <String>[
    macros.calories?.round().toString() ?? '—',
    _formatMacro(macros.protein),
    _formatMacro(macros.carbs),
    _formatMacro(macros.fat),
  ];

  String _formatMacro(double? amount) => amount?.toStringAsFixed(1) ?? '—';

  String _mealName(PlannedMeal meal, PlannedMealsCopy copy) =>
      meal.name.isEmpty ? copy.slot(meal.slot) : meal.name;
}

class _MealTableRow {
  const _MealTableRow({
    required this.id,
    required this.food,
    required this.values,
    required this.kind,
    this.muted = false,
  });

  final String id;
  final Widget food;
  final List<String> values;
  final _MealTableRowKind kind;
  final bool muted;

  bool get bold =>
      kind != _MealTableRowKind.food && kind != _MealTableRowKind.target;
}

enum _MealTableRowKind { header, meal, food, total, target }
