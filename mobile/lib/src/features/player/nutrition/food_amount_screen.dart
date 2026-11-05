import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';

class FoodAmountScreen extends ConsumerStatefulWidget {
  const FoodAmountScreen({
    required this.food,
    required this.day,
    required this.kcalLeft,
    required this.mealLabel,
    this.entry,
    super.key,
  });

  final FoodLibraryItem food;
  final String day;
  final double? kcalLeft;
  final String mealLabel;
  final FoodLogEntry? entry;

  @override
  ConsumerState<FoodAmountScreen> createState() => _FoodAmountScreenState();
}

class _FoodAmountScreenState extends ConsumerState<FoodAmountScreen> {
  late final TextEditingController _quantity;
  late String _unit;
  late String _meal;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _unit = widget.entry?.unit ?? 'grams';
    _meal = widget.entry?.mealLabel ?? widget.mealLabel;
    _quantity = TextEditingController(text: '${widget.entry?.quantity ?? 100}');
  }

  @override
  void dispose() {
    _quantity.dispose();
    super.dispose();
  }

  double get _amount =>
      double.tryParse(
        _quantity.text
            .replaceAllMapped(
              RegExp('[٠-٩]'),
              (Match match) => (match[0]!.codeUnitAt(0) - 0x0660).toString(),
            )
            .replaceAll('٫', '.'),
      ) ??
      0;
  double get _grams =>
      _amount * (_unit == 'grams' ? 1 : widget.food.portionGrams!);
  bool get _valid => _grams.isFinite && _grams > 0 && _grams <= 10000;

  Future<void> _save() async {
    if (_saving || !_valid) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final ApiClient api = ref.read(apiClientProvider);
    try {
      if (widget.entry == null) {
        await api.addFoodLogEntry(
          foodId: widget.food.id,
          day: widget.day,
          quantity: _amount,
          unit: _unit,
          mealLabel: _meal,
        );
      } else {
        await api.editFoodLogEntry(
          widget.entry!.id,
          quantity: _amount,
          unit: _unit,
          mealLabel: _meal,
        );
      }
      if (mounted) {
        setState(() => _saving = false);
        Navigator.of(context).pop(true);
      }
    } on ApiException catch (error) {
      if (mounted)
        setState(() {
          _error = error.message;
          _saving = false;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    final FoodNutrients nutrients = widget.food.nutrients.forGrams(
      _valid ? _grams : 0,
    );
    final double? after = widget.kcalLeft == null
        ? null
        : widget.kcalLeft! +
              (widget.entry?.nutrients.kcal ?? 0) -
              nutrients.kcal;
    return Directionality(
      textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: PopScope(
        canPop: !_saving,
        child: Scaffold(
          appBar: AppBar(
            title: Text(widget.entry == null ? copy.addTo(_meal) : copy.edit),
          ),
          body: ListView(
            padding: const EdgeInsets.all(20),
            children: <Widget>[
              Text(
                widget.food.displayName(copy.isArabic),
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 20),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _meal,
                decoration: InputDecoration(labelText: copy.meal),
                items: <String>['breakfast', 'lunch', 'dinner', 'snack']
                    .map(
                      (String value) => DropdownMenuItem<String>(
                        value: value,
                        child: Text(copy.mealLabel(value)),
                      ),
                    )
                    .toList(),
                onChanged: _saving
                    ? null
                    : (String? value) {
                        if (value != null) setState(() => _meal = value);
                      },
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                isExpanded: true,
                initialValue: _unit,
                decoration: InputDecoration(labelText: copy.unit),
                items: <DropdownMenuItem<String>>[
                  DropdownMenuItem(value: 'grams', child: Text(copy.grams)),
                  if (widget.food.portionGrams != null &&
                      widget.food.portionGrams! > 0)
                    DropdownMenuItem(
                      value: 'portion',
                      child: Text(
                        '${widget.food.portionLabel} (${widget.food.portionGrams} ${copy.grams})',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (String? value) {
                        if (value == null || value == _unit) return;
                        final double grams = _grams;
                        setState(() {
                          _unit = value;
                          _quantity.text =
                              (value == 'grams'
                                      ? grams
                                      : grams / widget.food.portionGrams!)
                                  .toStringAsFixed(2);
                        });
                      },
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _quantity,
                enabled: !_saving,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText: copy.amount,
                  errorText: _valid ? null : copy.invalidAmount,
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 20),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: <Widget>[
                      Text(
                        '${nutrients.kcal.round()} ${copy.calories}',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${copy.protein}: ${nutrients.protein.toStringAsFixed(1)} ${copy.grams}',
                      ),
                      Text(
                        '${copy.carbs}: ${nutrients.carbs.toStringAsFixed(1)} ${copy.grams}',
                      ),
                      Text(
                        '${copy.fat}: ${nutrients.fat.toStringAsFixed(1)} ${copy.grams}',
                      ),
                    ],
                  ),
                ),
              ),
              if (after != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    '${after.round()} ${widget.entry == null ? copy.afterAdding : copy.afterSaving}',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              if (_error != null)
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              FilledButton(
                onPressed: !_valid || _saving ? null : _save,
                child: Text(
                  _saving
                      ? copy.saving
                      : widget.entry == null
                      ? copy.add
                      : copy.save,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
