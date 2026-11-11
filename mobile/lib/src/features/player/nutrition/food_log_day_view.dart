import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/refetch_on_reconnect.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../providers.dart';
import '../tour/tour_targets.dart';
import 'food_amount_screen.dart';
import 'food_search_screen.dart';
import 'copy_food_meal_button.dart';
import 'quick_add_screen.dart';
import 'today_meals.dart';
import 'nutrition_summary_card.dart';
import 'nutrition_tile.dart';

class FoodLogDayView extends ConsumerStatefulWidget {
  const FoodLogDayView({
    required this.checkInBuilder,
    required this.onTodayWaterLoaded,
    required this.targets,
    required this.onShowTargets,
    super.key,
  });
  final Widget Function(FoodLogDay day) checkInBuilder;
  final ValueChanged<int> onTodayWaterLoaded;
  final Map<String, dynamic>? targets;
  final Future<void> Function() onShowTargets;

  @override
  ConsumerState<FoodLogDayView> createState() => _FoodLogDayViewState();
}

class _FoodLogDayViewState extends ConsumerState<FoodLogDayView>
    with RefetchOnReconnect<FoodLogDayView> {
  @override
  Future<void> refreshAfterReconnect() async {
    if (!_deleting) await _load(background: true);
  }

  FoodLogDay? _day;
  DateTime? _selected;
  bool _opening = false;
  bool _loading = true;
  bool _deleting = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(FoodLogDayView oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Every Nutrition response builds a new map, so only real changes reload.
    if (!mapEquals(widget.targets, oldWidget.targets)) _load(background: true);
  }

  String _dateKey(DateTime date) => date.toIso8601String().substring(0, 10);

  /// A background load keeps the current view and scroll position on screen.
  Future<bool> _load({bool background = false}) async {
    final int request = ++_request;
    if (!background)
      setState(() {
        _loading = true;
        _error = null;
      });
    try {
      final FoodLogDay day = await ref
          .read(apiClientProvider)
          .foodLogDay(day: _selected == null ? null : _dateKey(_selected!));
      if (!mounted || request != _request) return false;
      setState(() {
        _day = day;
        _error = null;
        _loading = false;
      });
      if (day.date == day.today && day.waterGlasses != null) {
        widget.onTodayWaterLoaded(day.waterGlasses!);
      }
      return true;
    } on ApiException catch (error) {
      if (mounted && request == _request)
        setState(() {
          _error = error.message;
          _loading = false;
        });
    }
    return false;
  }

  void _move(int offset) {
    if (_loading || _deleting || _day == null) return;
    final DateTime date = _day!.date;
    final DateTime target = DateTime(date.year, date.month, date.day + offset);
    _selected = target == _day!.today ? null : target;
    _load();
  }

  /// The Player's day can change without the device's date changing, so every
  /// add asks the server which day it is before using it.
  Future<bool> _readyToAdd() async {
    if (_opening || _loading || _deleting || _error != null || _day == null)
      return false;
    _opening = true;
    try {
      if (_selected == null && !await _load(background: true)) return false;
      return mounted && _day!.editable;
    } finally {
      _opening = false;
    }
  }

  String get _defaultMeal {
    final int hour = ref.read(clockProvider)().hour;
    return hour < 11
        ? 'breakfast'
        : hour < 16
            ? 'lunch'
            : hour < 22
                ? 'dinner'
                : 'snack';
  }

  Future<void> _quickAdd() async {
    if (!await _readyToAdd() || !mounted) return;
    final bool? added = await Navigator.of(context).push<bool>(
        MaterialPageRoute<bool>(
            builder: (_) => QuickAddScreen(
                day: _dateKey(_day!.date), mealLabel: _defaultMeal)));
    if (added == true && mounted) await _load();
  }

  Future<void> _search() async {
    if (!await _readyToAdd() || !mounted) return;
    final FoodLogDay day = _day!;
    final bool? added = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        fullscreenDialog: true,
        builder: (_) => FoodSearchScreen(
          day: _dateKey(day.date),
          kcalLeft: day.remaining?.kcal,
          mealLabel: _defaultMeal,
        ),
      ),
    );
    if (added == true && mounted) await _load();
  }

  Future<void> _edit(FoodLogEntry entry) async {
    final bool? edited = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => entry.kind == 'quick_add'
            ? QuickAddScreen(
                day: _dateKey(_day!.date),
                mealLabel: entry.mealLabel,
                entry: entry)
            : FoodAmountScreen(
                food: entry.food,
                day: _dateKey(_day!.date),
                kcalLeft: _day!.remaining?.kcal,
                mealLabel: entry.mealLabel,
                entry: entry,
              ),
      ),
    );
    if (edited == true && mounted) await _load();
  }

  Future<void> _delete(FoodLogEntry entry, FoodLogCopy copy) async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(copy.deleteTitle),
        content: Text(entry.kind == 'quick_add'
            ? copy.quickAdd
            : entry.food.displayName(copy.isArabic)),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(copy.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(copy.delete),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deleting = true);
    try {
      await ref.read(apiClientProvider).deleteFoodLogEntry(entry.id);
      if (mounted) await _load();
    } on ApiException catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _deleting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    final FoodLogDay? day = _day;
    return Column(
      children: <Widget>[
        if (day != null)
          if (day.editable)
            _navigation(day, copy)
          else
            TourTarget(id: 'food_log', child: _navigation(day, copy)),
        Expanded(child: _body(copy)),
        if (day != null && day.editable)
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: TourTarget(
                id: 'food_log',
                child: Row(children: <Widget>[
                  Expanded(
                      child: TextField(
                    key: const Key('food_log_entry_point'),
                    readOnly: true,
                    enabled: !_loading && !_deleting && _error == null,
                    onTap: _search,
                    decoration: InputDecoration(
                      hintText: copy.addFood,
                      prefixIcon: const Icon(Icons.search),
                      filled: true,
                      border: const OutlineInputBorder(),
                    ),
                  )),
                  const SizedBox(width: 8),
                  OutlinedButton(
                      onPressed: _loading || _deleting || _error != null
                          ? null
                          : _quickAdd,
                      child: Text(copy.quickAdd)),
                ]),
              ),
            ),
          ),
      ],
    );
  }

  Widget _navigation(FoodLogDay day, FoodLogCopy copy) {
    final MaterialLocalizations localizations = MaterialLocalizations.of(
      context,
    );
    final String date = localizations.formatMediumDate(day.date);
    final String label = day.date == day.today
        ? '${copy.today}, $date'
        : day.date ==
                DateTime(day.today.year, day.today.month, day.today.day - 1)
            ? '${copy.yesterday}, $date'
            : date;
    return Row(
      children: <Widget>[
        IconButton(
          tooltip: copy.previousDay,
          onPressed: _loading || _deleting ? null : () => _move(-1),
          icon: Icon(copy.isArabic ? Icons.chevron_right : Icons.chevron_left),
        ),
        Expanded(
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ),
        IconButton(
          tooltip: copy.nextDay,
          onPressed: _loading || _deleting || !day.date.isBefore(day.today)
              ? null
              : () => _move(1),
          icon: Icon(copy.isArabic ? Icons.chevron_left : Icons.chevron_right),
        ),
        TourTarget(
            id: 'meal_setup',
            child: IconButton(
              key: const Key('nutrition_targets'),
              tooltip: copy.targetsTitle,
              onPressed: () async {
                await widget.onShowTargets();
                if (mounted) await _load(background: true);
              },
              constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
              icon: const Icon(Icons.tune),
            )),
      ],
    );
  }

  Widget _body(FoodLogCopy copy) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null)
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(_error!, textAlign: TextAlign.center),
            TextButton(onPressed: _load, child: Text(copy.retry)),
          ],
        ),
      );
    final FoodLogDay day = _day!;
    return ListView(
      key: const Key('nutrition_day_list'),
      padding: const EdgeInsets.all(MayosSpacing.md),
      // The Feature guide can focus a card even after it has scrolled away.
      children: <Widget>[
        Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              TourTarget(
                  id: 'nutrition',
                  child: NutritionSummaryCard(day: day, copy: copy)),
              const SizedBox(height: MayosSpacing.md),
              if (day.date == day.today ||
                  day.plannedMeals != null) ...<Widget>[
                TodayMeals(
                    key: ValueKey<String>(_dateKey(day.date)),
                    pastPlan: day.plannedMeals,
                    revision: _request,
                    loggedEntries: day.entries,
                    onLogged: () => _load(background: true)),
              ],
              _foodLogCard(day, copy),
              const SizedBox(height: MayosSpacing.md),
              widget.checkInBuilder(day),
            ])
      ],
    );
  }

  Widget _foodLogCard(FoodLogDay day, FoodLogCopy copy) {
    final Map<String, List<FoodLogEntry>> meals =
        <String, List<FoodLogEntry>>{};
    for (final FoodLogEntry entry in day.entries) {
      (meals[entry.mealSlot ?? entry.mealLabel] ??= <FoodLogEntry>[])
          .add(entry);
    }
    return NutritionCard(
        key: const Key('nutrition_food_log'),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Row(children: <Widget>[
                Expanded(
                    child: Text(copy.foodLog,
                        style: Theme.of(context).textTheme.titleMedium)),
                if (day.date == day.today)
                  Flexible(
                      child: CopyFoodMealButton(
                          key: ValueKey<String>('copy_${_dateKey(day.date)}'),
                          day: _dateKey(day.date),
                          revision: _request,
                          showInHeader: true,
                          enabled: !_loading && !_deleting && _error == null,
                          onCopied: _load,
                          onStale: () => _load(background: true))),
              ]),
              if (!day.editable)
                Text(copy.readOnly,
                    style: Theme.of(context).textTheme.bodySmall),
              if (day.entries.isEmpty)
                Padding(
                    padding:
                        const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
                    child: Text(copy.nothingLogged,
                        style: TextStyle(
                            color: MayosTheme.of(context).textMuted))),
              for (final MapEntry<String, List<FoodLogEntry>> meal
                  in meals.entries) ...<Widget>[
                const SizedBox(height: MayosSpacing.sm),
                Text(copy.mealLabel(meal.key),
                    style: Theme.of(context).textTheme.labelLarge),
                for (final FoodLogEntry entry in meal.value)
                  _entryRow(entry, day, copy),
              ],
            ]));
  }

  Widget _entryRow(FoodLogEntry entry, FoodLogDay day, FoodLogCopy copy) =>
      ListTile(
        contentPadding: EdgeInsets.zero,
        minLeadingWidth: 0,
        leading: Text(entry.loggedTime,
            style: Theme.of(context).textTheme.bodySmall),
        title: Text(entry.kind == 'quick_add'
            ? copy.quickAdd
            : entry.food.displayName(copy.isArabic)),
        subtitle: Text(entry.kind == 'quick_add'
            ? _quickMacros(entry, copy)
            : copy.amountLabel(
                entry.quantity, entry.unit, entry.food.portionLabel)),
        trailing: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
          Text('${entry.nutrients.kcal.round()} ${copy.calories}',
              style: Theme.of(context).textTheme.bodySmall),
          if (day.editable)
            PopupMenuButton<String>(
                    icon: const Icon(Icons.more_vert),
              enabled: !_deleting,
              onSelected: (String action) =>
                  action == 'edit' ? _edit(entry) : _delete(entry, copy),
              itemBuilder: (_) => <PopupMenuEntry<String>>[
                PopupMenuItem(value: 'edit', child: Text(copy.edit)),
                PopupMenuItem(value: 'delete', child: Text(copy.delete)),
              ],
            ),
        ]),
        onTap: day.editable && !_deleting ? () => _edit(entry) : null,
      );

  String _quickMacros(FoodLogEntry entry, FoodLogCopy copy) => <String>[
        for (final (String key, String label, double value)
            in <(String, String, double)>[
          ('protein_g', copy.protein, entry.nutrients.protein),
          ('carbohydrate_g', copy.carbs, entry.nutrients.carbs),
          ('fat_g', copy.fat, entry.nutrients.fat),
        ])
          '$label: ${entry.blankMacros.contains(key) ? '' : '${value.toStringAsFixed(1)} ${copy.grams}'}',
      ].join(' · ');
}
