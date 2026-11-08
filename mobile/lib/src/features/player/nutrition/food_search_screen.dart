import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/display_language/meal_setup_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';
import 'food_amount_screen.dart';
import 'copy_food_meal_button.dart';
import 'personal_food_screen.dart';
import 'quick_add_screen.dart';
import 'food_restriction_badge.dart';

class FoodSearchScreen extends ConsumerStatefulWidget {
  const FoodSearchScreen({
    required this.day,
    required this.kcalLeft,
    required this.mealLabel,
    this.selectOnly = false,
    super.key,
  });
  final String day;
  final double? kcalLeft;
  final String mealLabel;
  final bool selectOnly;

  @override
  ConsumerState<FoodSearchScreen> createState() => _FoodSearchScreenState();
}

class _FoodSearchScreenState extends ConsumerState<FoodSearchScreen> {
  final TextEditingController _query = TextEditingController();
  Timer? _debounce;
  int _request = 0;
  List<FoodLibraryItem> _foods = <FoodLibraryItem>[];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _search();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _query.dispose();
    super.dispose();
  }

  void _changed(String value) {
    _debounce?.cancel();
    _request++;
    setState(() {
      _loading = true;
      _error = null;
    });
    _debounce = Timer(const Duration(milliseconds: 250), _search);
  }

  Future<void> _search() async {
    final int request = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final List<FoodLibraryItem> foods = await ref
          .read(apiClientProvider)
          .searchFoods(_query.text);
      if (mounted && request == _request)
        setState(() {
          _foods = foods;
          _loading = false;
        });
    } on ApiException catch (error) {
      if (mounted && request == _request)
        setState(() {
          _error = error.message;
          _loading = false;
        });
    }
  }

  Future<void> _open(FoodLibraryItem food) async {
    if (widget.selectOnly) {
      Navigator.of(context).pop(food);
      return;
    }
    final bool? added = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => FoodAmountScreen(
          food: food,
          day: widget.day,
          kcalLeft: widget.kcalLeft,
          mealLabel: widget.mealLabel,
        ),
      ),
    );
    if (added == true && mounted) {
      Navigator.of(context).pop(true);
    } else if (mounted) {
      await _search();
    }
  }

  Future<void> _quickAdd() async {
    final bool? added = await Navigator.of(context).push<bool>(MaterialPageRoute<bool>(
      builder: (_) => QuickAddScreen(day: widget.day, mealLabel: widget.mealLabel)));
    if (added == true && mounted) Navigator.of(context).pop(true);
  }

  Future<void> _createPersonal() async {
    final FoodLibraryItem? food = await Navigator.of(context).push<FoodLibraryItem>(
      MaterialPageRoute<FoodLibraryItem>(builder: (_) => PersonalFoodScreen(initialName: _query.text.trim())));
    if (!mounted || food == null) return;
    await _open(food);
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    return Directionality(
      textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            tooltip: copy.close,
            icon: const Icon(Icons.close),
            onPressed: () => Navigator.of(context).pop(),
          ),
          title: Text(widget.selectOnly ? MealSetupCopy(copy.languageCode).addDislike : copy.addTo(widget.mealLabel)),
          actions: <Widget>[if (!widget.selectOnly) TextButton(onPressed: _quickAdd, child: Text(copy.quickAdd))],
        ),
        body: Column(
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: TextField(
                controller: _query,
                autofocus: true,
                onChanged: _changed,
                decoration: InputDecoration(
                  labelText: copy.searchFoods,
                  prefixIcon: const Icon(Icons.search),
                  border: const OutlineInputBorder(),
                ),
              ),
            ),
            if (_query.text.trim().isEmpty)
              Padding(
                padding: const EdgeInsets.all(8),
                child: Text(copy.recentFoods),
              ),
            if (_query.text.trim().isEmpty && !widget.selectOnly)
              CopyFoodMealButton(day: widget.day,
                onCopied: () => Navigator.of(context).pop(true)),
            Expanded(child: _results(copy)),
          ],
        ),
      ),
    );
  }

  Widget _results(FoodLogCopy copy) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null)
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(_error!, textAlign: TextAlign.center),
            TextButton(onPressed: _search, child: Text(copy.retry)),
          ],
        ),
      );
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _foods.length + (_foods.isEmpty ? 1 : 0) + (widget.selectOnly ? 0 : 1),
      itemBuilder: (BuildContext context, int index) {
        if (_foods.isEmpty && index == 0) return Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_query.text.trim().isEmpty ? copy.noRecent : copy.noResults));
        if (index >= _foods.length) return Card(child: ListTile(
          key: const Key('create_personal_food'),
          title: Text(copy.cantFind), subtitle: Text(copy.createPersonal),
          onTap: _createPersonal,
        ));
        final FoodLibraryItem food = _foods[index];
        final String detail = <String>[
          if (food.recipe) copy.recipe,
          if (food.loggedCount > 0) copy.loggedTimes(food.loggedCount),
          copy.proteinDetail(food.nutrients.protein),
          if (food.portionLabel != null)
            '${food.portionLabel} (${food.portionGrams} ${copy.grams})',
        ].join(' · ');
        return Card(
          child: ListTile(
            onTap: () => _open(food),
            title: Wrap(
              spacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: <Widget>[
                Text(food.displayName(copy.isArabic)),
                if (food.staple)
                  Chip(
                    label: Text(copy.staple),
                    visualDensity: VisualDensity.compact,
                  ),
                if (food.restrictionReasons.isNotEmpty)
                  FoodRestrictionBadge(reasons: food.restrictionReasons,
                    copy: MealSetupCopy(copy.languageCode)),
              ],
            ),
            subtitle: Text(detail),
            trailing: Text(
              copy.per100g(food.nutrients.kcal),
              textAlign: TextAlign.end,
            ),
          ),
        );
      },
    );
  }
}
