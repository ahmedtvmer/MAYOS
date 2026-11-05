import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';
import 'food_amount_screen.dart';

class FoodSearchScreen extends ConsumerStatefulWidget {
  const FoodSearchScreen({
    required this.day,
    required this.kcalLeft,
    required this.mealLabel,
    super.key,
  });
  final String day;
  final double? kcalLeft;
  final String mealLabel;

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
    if (added == true && mounted) Navigator.of(context).pop(true);
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
          title: Text(copy.addTo(widget.mealLabel)),
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
    if (_foods.isEmpty)
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            _query.text.trim().isEmpty ? copy.noRecent : copy.noResults,
          ),
        ),
      );
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _foods.length,
      itemBuilder: (BuildContext context, int index) {
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
