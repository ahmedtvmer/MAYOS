import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/food_log_copy.dart';
import '../../../core/food_log_models.dart';
import '../../../providers.dart';
import 'food_nutrient_fields.dart';

class QuickAddScreen extends ConsumerStatefulWidget {
  const QuickAddScreen({required this.day, required this.mealLabel,
    this.entry, super.key});
  final String day;
  final String mealLabel;
  final FoodLogEntry? entry;

  @override
  ConsumerState<QuickAddScreen> createState() => _QuickAddScreenState();
}

class _QuickAddScreenState extends ConsumerState<QuickAddScreen> {
  late final Map<String, TextEditingController> _fields;
  late String _meal;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _meal = widget.entry?.mealLabel ?? widget.mealLabel;
    final FoodLogEntry? entry = widget.entry;
    final List<double>? values = entry == null ? null : <double>[
      entry.nutrients.kcal, entry.nutrients.protein, entry.nutrients.carbs, entry.nutrients.fat,
    ];
    _fields = <String, TextEditingController>{
      for (int index = 0; index < foodNutrientKeys.length; index++)
        foodNutrientKeys[index]: TextEditingController(text: values == null ||
            entry!.blankMacros.contains(foodNutrientKeys[index]) ? '' : '${values[index]}'),
    };
  }

  @override
  void dispose() {
    for (final TextEditingController field in _fields.values) { field.dispose(); }
    super.dispose();
  }

  bool get _valid => _fields.entries.every((MapEntry<String, TextEditingController> field) {
    if (field.key != 'energy_kcal' && field.value.text.trim().isEmpty) return true;
    final double? value = foodNumber(field.value.text);
    return value != null && value.isFinite && value >= 0 &&
        value <= (field.key == 'energy_kcal' ? 100000 : 10000);
  });

  Future<void> _save() async {
    if (_saving || !_valid) return;
    setState(() { _saving = true; _error = null; });
    try {
      await ref.read(apiClientProvider).saveQuickAdd(<String, dynamic>{
        if (widget.entry == null) 'entry_date': widget.day,
        'meal_label': _meal,
        for (final String key in foodNutrientKeys) key: foodNumber(_fields[key]!.text),
      }, entryId: widget.entry?.id);
      if (mounted) {
        setState(() => _saving = false);
        Navigator.of(context).pop(true);
      }
    } on ApiException catch (error) {
      if (mounted) setState(() { _saving = false; _error = error.message; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final FoodLogCopy copy = FoodLogCopy(ref.watch(displayLanguageProvider));
    return Directionality(
      textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: PopScope(canPop: !_saving, child: Scaffold(
        appBar: AppBar(title: Text(copy.quickAdd)),
        body: ListView(padding: const EdgeInsets.all(20), children: <Widget>[
          DropdownButtonFormField<String>(
            initialValue: _meal,
            decoration: InputDecoration(labelText: copy.meal),
            items: <String>['breakfast', 'lunch', 'dinner', 'snack'].map((String value) =>
              DropdownMenuItem<String>(value: value, child: Text(copy.mealLabel(value)))).toList(),
            onChanged: _saving ? null : (String? value) {
              if (value != null) setState(() => _meal = value);
            },
          ),
          const SizedBox(height: 16),
          Text(copy.optionalMacros),
          FoodNutrientFields(controllers: _fields, copy: copy,
            onChanged: () => setState(() {}), enabled: !_saving),
          if (!_valid && _fields.values.any((TextEditingController field) => field.text.isNotEmpty))
            Text(copy.invalidNutrients),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 20),
          FilledButton(onPressed: _saving || !_valid ? null : _save,
            child: Text(_saving ? copy.saving : widget.entry == null ? copy.add : copy.save)),
        ]),
      )),
    );
  }
}
