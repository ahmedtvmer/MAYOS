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
    // Prefer the theme's progress colour so the wallpaper theme can substitute
    // its lighter link blue; both app themes set it to the accent.
    final Color resolved = color ??
        Theme.of(context).progressIndicatorTheme.color ??
        c.accent;
    return ClipRRect(
      borderRadius: BorderRadius.circular(height),
      child: LinearProgressIndicator(
        value: value,
        minHeight: height,
        color: resolved,
        backgroundColor: c.surfaceSunken,
      ),
    );
  }
}
