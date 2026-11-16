import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/refetch_on_reconnect.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../providers.dart';

class CopyFoodMealButton extends ConsumerStatefulWidget {
  const CopyFoodMealButton(
      {required this.day,
      required this.onCopied,
      this.onStale,
      this.revision = 0,
      this.enabled = true,
      this.showInHeader = false,
      super.key});
  final String day;
  final VoidCallback onCopied;
  final VoidCallback? onStale;
  final int revision;
  final bool enabled;
  final bool showInHeader;

  @override
  ConsumerState<CopyFoodMealButton> createState() => _CopyFoodMealButtonState();
}

class _CopyFoodMealButtonState extends ConsumerState<CopyFoodMealButton>
    with RefetchOnReconnect<CopyFoodMealButton> {
  @override
  Future<void> refreshAfterReconnect() async {
    if (!_busy) await _load();
  }

  List<String> _meals = <String>[];
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(CopyFoodMealButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_busy &&
        (oldWidget.day != widget.day || oldWidget.revision != widget.revision))
      _load();
  }

  Future<void> _load() async {
    final String day = widget.day;
    setState(() {
      _meals = <String>[];
      _error = null;
    });
    try {
      final List<String> meals =
          await ref.read(apiClientProvider).yesterdayFoodMeals(day);
      if (mounted && widget.day == day) setState(() => _meals = meals);
    } on ApiException catch (error) {
      if (mounted && widget.day == day) setState(() => _error = error.message);
    }
  }

  Future<void> _copy() async {
    if (_busy) return;
    setState(() => _busy = true);
    // The picker can outlive the Player's day, so its choices are read fresh.
    final List<String> meals;
    try {
      meals = await ref.read(apiClientProvider).yesterdayFoodMeals(widget.day);
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _busy = false;
          _error = error.message;
        });
      return;
    }
    if (!mounted) return;
    if (meals.isEmpty) {
      setState(() {
        _busy = false;
        _meals = meals;
      });
      widget.onStale?.call();
      return;
    }
    setState(() => _meals = meals);
    final bool? copied = await showModalBottomSheet<bool>(
        context: context,
        isDismissible: false,
        enableDrag: false,
        builder: (_) => _CopyMealSheet(day: widget.day, meals: meals));
    if (!mounted) return;
    setState(() => _busy = false);
    if (copied == true) widget.onCopied();
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    if (_error != null)
      return TextButton(
          onPressed: _load, child: Text('${_error!} ${copy.retry}'));
    if (_meals.isEmpty && !widget.showInHeader) return const SizedBox.shrink();
    return PopScope(
        canPop: !_busy,
        child: TextButton.icon(
          key: const Key('copy_food_meal'),
          onPressed: _busy || !widget.enabled || _meals.isEmpty ? null : _copy,
          icon: const Icon(Icons.copy),
          label: Text(_busy
              ? copy.copying
              : widget.showInHeader
                  ? copy.copyMealShort
                  : copy.copyMeal),
        ));
  }
}

class _CopyMealSheet extends ConsumerStatefulWidget {
  const _CopyMealSheet({required this.day, required this.meals});
  final String day;
  final List<String> meals;

  @override
  ConsumerState<_CopyMealSheet> createState() => _CopyMealSheetState();
}

class _CopyMealSheetState extends ConsumerState<_CopyMealSheet> {
  bool _saving = false;
  String? _error;

  Future<void> _copy(String meal) async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).copyFoodMeal(meal, widget.day);
      if (mounted) {
        setState(() => _saving = false);
        Navigator.of(context).pop(true);
      }
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _saving = false;
          _error = error.message;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    return PopScope(
        canPop: !_saving,
        child: Directionality(
          textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
          child: SafeArea(
              child: SingleChildScrollView(
                  child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(_saving ? copy.copying : copy.copyMeal)),
              for (final String meal in widget.meals)
                ListTile(
                    title: Text(copy.mealLabel(meal)),
                    onTap: _saving ? null : () => _copy(meal)),
              if (_error != null)
                Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(_error!,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error))),
              TextButton(
                  onPressed:
                      _saving ? null : () => Navigator.of(context).pop(false),
                  child: Text(copy.cancel)),
            ],
          ))),
        ));
  }
}
