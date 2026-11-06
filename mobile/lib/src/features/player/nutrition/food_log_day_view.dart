import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';
import '../tour/tour_targets.dart';
import 'food_amount_screen.dart';
import 'food_search_screen.dart';
import 'copy_food_meal_button.dart';
import 'quick_add_screen.dart';

class FoodLogDayView extends ConsumerStatefulWidget {
  const FoodLogDayView({
    required this.targetsView,
    required this.adherence,
    required this.targets,
    required this.onShowTargets,
    super.key,
  });
  final Widget targetsView;
  final Widget adherence;
  final Map<String, dynamic>? targets;
  final VoidCallback onShowTargets;

  @override
  ConsumerState<FoodLogDayView> createState() => _FoodLogDayViewState();
}

class _FoodLogDayViewState extends ConsumerState<FoodLogDayView> {
  FoodLogDay? _day;
  DateTime? _selected;
  DateTime? _lastLoadedDeviceDate;
  late final AppLifecycleListener _lifecycle;
  bool _loading = true;
  bool _deleting = false;
  String? _error;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _lifecycle = AppLifecycleListener(onResume: () {
      if (mounted) _load(background: true);
    });
    _load();
  }

  @override
  void dispose() {
    _lifecycle.dispose();
    super.dispose();
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
    // A read spanning device midnight must still refresh before opening search.
    final DateTime deviceDate = DateUtils.dateOnly(ref.read(clockProvider)());
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
        _lastLoadedDeviceDate = deviceDate;
        _loading = false;
      });
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

  Future<bool> _readyToAdd() async {
    if (_loading || _deleting || _error != null || _day == null) return false;
    while (_selected == null &&
        _lastLoadedDeviceDate != DateUtils.dateOnly(ref.read(clockProvider)())) {
      final bool loaded = await _load();
      if (!mounted || !loaded) return false;
    }
    return _day!.editable;
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
    final bool? added = await Navigator.of(context).push<bool>(MaterialPageRoute<bool>(
      builder: (_) => QuickAddScreen(day: _dateKey(_day!.date), mealLabel: _defaultMeal)));
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
            ? QuickAddScreen(day: _dateKey(_day!.date), mealLabel: entry.mealLabel, entry: entry)
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
        content: Text(entry.kind == 'quick_add' ? copy.quickAdd : entry.food.displayName(copy.isArabic)),
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
        if (day != null && day.date == day.today)
          CopyFoodMealButton(key: ValueKey<String>('copy_${_dateKey(day.date)}'),
            day: _dateKey(day.date), revision: _request,
            enabled: !_loading && !_deleting && _error == null, onCopied: _load),
        if (day != null && day.editable)
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: TourTarget(
                id: 'food_log',
                child: Row(children: <Widget>[
                  Expanded(child: TextField(
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
                  OutlinedButton(onPressed: _loading || _deleting || _error != null ? null : _quickAdd,
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
    if (day.date == day.today && day.entries.isEmpty) return widget.targetsView;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        if (day.remaining != null) ...<Widget>[
          TourTarget(
            id: 'nutrition',
            child: Column(
              children: <Widget>[
                Text(
                  '${day.remaining!.kcal.round()}',
                  style: Theme.of(context).textTheme.displayLarge,
                ),
                Text(copy.leftOf(day.targets?['calories'] as num? ?? 0)),
              ],
            ),
          ),
          const SizedBox(height: 20),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              _macro(
                copy.macroLeft(copy.protein),
                day.remaining!.protein,
                Theme.of(context).colorScheme.primary,
                copy,
              ),
              _macro(
                copy.macroLeft(copy.carbs),
                day.remaining!.carbs,
                Theme.of(context).colorScheme.tertiary,
                copy,
              ),
              _macro(
                copy.macroLeft(copy.fat),
                day.remaining!.fat,
                Theme.of(context).colorScheme.secondary,
                copy,
              ),
            ],
          ),
        ],
        const SizedBox(height: 16),
        if (day.date == day.today && day.cardioBurnedKcal > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(copy.cardioBurned(day.cardioBurnedKcal)),
          ),
        if (!day.editable) Text(copy.readOnly, textAlign: TextAlign.center),
        if (day.entries.isEmpty)
          Padding(
            padding: const EdgeInsets.all(20),
            child: Text(copy.noEntries),
          ),
        for (final FoodLogEntry entry in day.entries)
          Card(
            child: ListTile(
              leading: Text(entry.loggedTime),
              title: Text(entry.kind == 'quick_add' ? copy.quickAdd : entry.food.displayName(copy.isArabic)),
              subtitle: Text(entry.kind == 'quick_add'
                  ? '${copy.mealLabel(entry.mealLabel)}\n${_quickMacros(entry, copy)}'
                  : '${copy.amountLabel(entry.quantity, entry.unit, entry.food.portionLabel)} · ${copy.mealLabel(entry.mealLabel)}'),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text('${entry.nutrients.kcal.round()} ${copy.calories}'),
                  if (day.editable)
                    PopupMenuButton<String>(
                      enabled: !_deleting,
                      onSelected: (String action) => action == 'edit'
                          ? _edit(entry)
                          : _delete(entry, copy),
                      itemBuilder: (_) => <PopupMenuEntry<String>>[
                        PopupMenuItem(value: 'edit', child: Text(copy.edit)),
                        PopupMenuItem(
                          value: 'delete',
                          child: Text(copy.delete),
                        ),
                      ],
                    ),
                ],
              ),
              onTap: day.editable && !_deleting ? () => _edit(entry) : null,
            ),
          ),
        if (day.date == day.today) ...<Widget>[
          const SizedBox(height: 16),
          widget.adherence,
        ],
        TextButton(
          onPressed: widget.onShowTargets,
          child: Text(copy.targetsTitle),
        ),
      ],
    );
  }

  String _quickMacros(FoodLogEntry entry, FoodLogCopy copy) => <String>[
    for (final (String key, String label, double value) in <(String, String, double)>[
      ('protein_g', copy.protein, entry.nutrients.protein),
      ('carbohydrate_g', copy.carbs, entry.nutrients.carbs),
      ('fat_g', copy.fat, entry.nutrients.fat),
    ]) '$label: ${entry.blankMacros.contains(key) ? '' : '${value.toStringAsFixed(1)} ${copy.grams}'}',
  ].join(' · ');

  Widget _macro(String label, double value, Color color, FoodLogCopy copy) =>
      Expanded(
        child: Card(
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              border: Border(top: BorderSide(color: color, width: 4)),
            ),
            child: Column(
              children: <Widget>[
                Text(label, textAlign: TextAlign.center),
                const SizedBox(height: 4),
                Text(
                  '${value.round()} ${copy.grams}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ],
            ),
          ),
        ),
      );
}
