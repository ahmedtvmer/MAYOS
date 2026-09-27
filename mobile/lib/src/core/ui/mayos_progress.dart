import 'package:flutter/material.dart';

import '../theme/mayos_theme.dart';

/// A thin, rounded MAYOS progress bar. [value] is null for indeterminate.
class MayosProgressIndicator extends StatelessWidget {
  const MayosProgressIndicator({
    super.key,
    this.value,
    this.color,
    this.height = 4,
  });

  final double? value;
  final Color? color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ClipRRect(
      borderRadius: BorderRadius.circular(height),
      child: LinearProgressIndicator(
        value: value,
        minHeight: height,
        color: color ?? c.accent,
        backgroundColor: c.surfaceSunken,
      ),
    );
  }
}
