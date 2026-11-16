import 'package:flutter/material.dart';

import '../../../core/display_language/meal_setup_copy.dart';

class FoodRestrictionBadge extends StatelessWidget {
  const FoodRestrictionBadge({required this.reasons, required this.copy, super.key});
  final List<String> reasons;
  final MealSetupCopy copy;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final String label = '${copy.restricted}: ${reasons.map(copy.reason).join(', ')}';
    return Chip(avatar: Icon(Icons.warning_amber_rounded, size: 18, color: colors.onErrorContainer),
      backgroundColor: colors.errorContainer,
      label: Text(label, style: TextStyle(color: colors.onErrorContainer)),
      visualDensity: VisualDensity.compact);
  }
}
