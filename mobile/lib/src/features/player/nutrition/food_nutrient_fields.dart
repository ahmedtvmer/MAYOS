import 'package:flutter/material.dart';

import '../../../core/display_language/food_log_copy.dart';

const List<String> foodNutrientKeys = <String>[
  'energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g',
];

double? foodNumber(String text) => double.tryParse(text.trim()
    .replaceAllMapped(RegExp('[٠-٩]'),
      (Match match) => (match[0]!.codeUnitAt(0) - 0x0660).toString())
    .replaceAll('٫', '.'));

class FoodNutrientFields extends StatelessWidget {
  const FoodNutrientFields({required this.controllers, required this.copy,
    required this.onChanged, required this.enabled, super.key});

  final Map<String, TextEditingController> controllers;
  final FoodLogCopy copy;
  final VoidCallback onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => Column(children: <Widget>[
    for (final (String key, String label) in <(String, String)>[
      ('energy_kcal', copy.calories), ('protein_g', copy.protein),
      ('carbohydrate_g', copy.carbs), ('fat_g', copy.fat),
    ])
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: TextField(
          key: Key('food_$key'),
          controller: controllers[key],
          enabled: enabled,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: label,
            suffixText: key == 'energy_kcal' ? null : copy.grams),
          onChanged: (_) => onChanged(),
        ),
      ),
  ]);
}
