import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/nutrition_copy.dart';
import '../../../core/planned_meals_models.dart';
import '../../../providers.dart';
import 'food_swap_requests.dart';

class NutritionMealSettingsRows extends ConsumerStatefulWidget {
  const NutritionMealSettingsRows({required this.onOpenSetup, super.key});
  final Future<void> Function() onOpenSetup;

  @override
  ConsumerState<NutritionMealSettingsRows> createState() =>
      _NutritionMealSettingsRowsState();
}

class _NutritionMealSettingsRowsState
    extends ConsumerState<NutritionMealSettingsRows> {
  PlannedMeals? _meals;
  bool _loading = true;
  bool _loadFailed = false;
  bool _changing = false;
  bool? _pendingEnabled;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _coachControls =>
      _meals?.author == 'Coach' || _meals?.canEnable == false;
  bool get _canToggle =>
      _meals != null &&
      !_coachControls &&
      _meals!.status != 'unavailable' &&
      !_loading &&
      !_loadFailed &&
      !_changing;

  Future<void> _load() async {
    final int request = ++_request;
    setState(() {
      _loading = true;
      _loadFailed = false;
    });
    try {
      final PlannedMeals meals =
          await ref.read(apiClientProvider).plannedMeals();
      if (mounted && request == _request) setState(() => _meals = meals);
    } on ApiException catch (error) {
      if (mounted && request == _request) {
        setState(() => _loadFailed = true);
        _showError(error);
      }
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  Future<void> _changeEnabled(bool enabled) async {
    if (!_canToggle) return;
    setState(() {
      _changing = true;
      _pendingEnabled = enabled;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final PlannedMeals saved = enabled
          ? await api.plannedMeals(enable: true)
          : await api.disablePlannedMeals();
      if (mounted) setState(() => _meals = saved);
    } on ApiException catch (error) {
      if (mounted) _showError(error);
    } finally {
      if (mounted)
        setState(() {
          _changing = false;
          _pendingEnabled = null;
        });
    }
  }

  void _showError(ApiException error) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(error.message)));

  Future<void> _openSetup() async {
    await widget.onOpenSetup();
    if (mounted) await _load();
  }

  String _status(NutritionCopy copy) {
    if (_loading) return copy.loadingMeals;
    if (_changing) return copy.saving;
    if (_meals?.status == 'unavailable')
      return copy.mealsUnavailable(_meals!.reason);
    if (_coachControls) return copy.mealsUnavailable('coach');
    return _meals?.enabled == true ? copy.mealsOn : copy.mealsOff;
  }

  @override
  Widget build(BuildContext context) {
    final NutritionCopy copy =
        NutritionCopy(ref.watch(displayLanguageProvider));
    return PopScope(
        canPop: !_changing,
        child: Column(children: <Widget>[
          ListTile(
            key: const Key('meal_setup_entry'),
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.restaurant_menu),
            title: Text(copy.meals),
            subtitle: _loadFailed
                ? TextButton(onPressed: _load, child: Text(copy.retry))
                : Text(_status(copy)),
            onTap: _changing ? null : _openSetup,
            trailing: Row(mainAxisSize: MainAxisSize.min, children: <Widget>[
              const FoodSwapRequestsEntry(),
              Semantics(
                  label: copy.meals,
                  child: Switch(
                      key: const Key('meals_switch'),
                      value: _pendingEnabled ?? _meals?.enabled ?? false,
                      onChanged: _canToggle ? _changeEnabled : null)),
            ]),
          ),
          const Divider(),
          ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.no_food_outlined),
              title: Text(copy.foodRestrictions),
              onTap: _changing ? null : _openSetup,
              trailing: Icon(
                  copy.isArabic ? Icons.chevron_left : Icons.chevron_right)),
        ]));
  }
}
