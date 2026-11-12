import 'package:flutter/material.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';

class NutritionCard extends StatelessWidget {
  const NutritionCard({required this.child, super.key});
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
        margin: EdgeInsets.zero,
        shape:
            const RoundedRectangleBorder(borderRadius: MayosRadii.largeRadius),
        child: Padding(
            padding: const EdgeInsets.all(MayosSpacing.md), child: child),
      );
}

/// Shared by the day's remaining amounts and the prescribed target amounts.
class NutritionTile extends StatelessWidget {
  const NutritionTile(
      {required this.label,
      required this.amount,
      this.detail,
      this.color,
      this.progress,
      super.key});
  final String label;
  final String amount;
  final String? detail;
  final Color? color;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension tokens = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(MayosSpacing.xs),
      decoration: BoxDecoration(
          color: tokens.surfaceSunken,
          borderRadius: MayosRadii.mediumRadius,
          border: Border.all(color: tokens.border)),
      child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            Text(label,
                style: text.labelMedium
                    ?.copyWith(color: color ?? tokens.textSecondary)),
            const SizedBox(height: MayosSpacing.xs),
            Text(amount, style: text.titleSmall),
            if (detail != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.xxs),
              Text(detail!,
                  style: text.bodySmall?.copyWith(color: tokens.textMuted)),
            ],
            if (progress != null) ...<Widget>[
              const Spacer(),
              const SizedBox(height: MayosSpacing.xs),
              LinearProgressIndicator(
                  value: progress!.clamp(0.0, 1.0),
                  minHeight: 3,
                  color: color,
                  backgroundColor: tokens.border,
                  borderRadius: MayosRadii.pillRadius),
            ],
          ]),
    );
  }
}

class NutritionTileRow extends StatelessWidget {
  const NutritionTileRow({required this.tiles, super.key});
  final List<NutritionTile> tiles;

  @override
  Widget build(BuildContext context) => IntrinsicHeight(
          child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          for (int index = 0; index < tiles.length; index++) ...<Widget>[
            if (index > 0) const SizedBox(width: MayosSpacing.xs),
            Expanded(child: tiles[index]),
          ],
        ],
      ));
}
