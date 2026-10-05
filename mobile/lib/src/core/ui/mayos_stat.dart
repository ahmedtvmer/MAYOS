import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

/// A single numeric/metric display: a prominent figure over a quiet label.
class MayosStat extends StatelessWidget {
  const MayosStat({
    super.key,
    required this.value,
    required this.label,
    this.unit,
    this.valueColor,
    this.alignment = CrossAxisAlignment.start,
    this.semanticsLabel,
  });

  final String value;
  final String label;
  final String? unit;
  final Color? valueColor;
  final CrossAxisAlignment alignment;
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      label: semanticsLabel ?? '$value ${unit ?? ''} $label'.trim(),
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: alignment,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          // A long figure (e.g. a many-hour Workout time) shrinks to its cell
          // instead of overflowing a narrow column.
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: switch (alignment) {
              CrossAxisAlignment.end => AlignmentDirectional.centerEnd,
              CrossAxisAlignment.center => AlignmentDirectional.center,
              CrossAxisAlignment.start ||
              CrossAxisAlignment.stretch ||
              CrossAxisAlignment.baseline =>
                AlignmentDirectional.centerStart,
            },
            child: Directionality(
              textDirection: TextDirection.ltr,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: <Widget>[
                  Text(
                    value,
                    style: MayosTypography.of(context).numeric
                        .copyWith(color: valueColor ?? c.textPrimary),
                  ),
                  if (unit != null) ...<Widget>[
                    const SizedBox(width: MayosSpacing.xxs),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Text(
                        unit!,
                        style: MayosTypography.of(context).label
                            .copyWith(color: c.textSecondary),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            label,
            style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
          ),
        ],
      ),
    );
  }
}
