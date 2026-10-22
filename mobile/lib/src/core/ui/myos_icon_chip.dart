import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';
import '../theme/myos_theme.dart';

/// The soft square that frames a row's leading icon.
///
/// Extracted from `MyosSettingsTile` so every settings-like row shares one
/// treatment: a [kMyosIconChipSize] box in the theme's sunken surface colour,
/// the [MyosRadii.medium] corner, and a danger-washed border on destructive
/// rows. The glyph inside is sized with [MyosIconSizes], never a raw pixel.
class MyosIconChip extends StatelessWidget {
  const MyosIconChip({
    super.key,
    required this.child,
    this.destructive = false,
  });

  /// The glyph itself, normally an `Icon` or a brand mark.
  final Widget child;

  /// Paints the chip the way a destructive row frames its icon.
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Container(
      width: kMyosIconChipSize,
      height: kMyosIconChipSize,
      decoration: BoxDecoration(
        color: destructive ? c.accentSubtle : c.surfaceSunken,
        borderRadius: MyosRadii.mediumRadius,
        border: Border.all(
          color: destructive ? c.danger.withValues(alpha: 0.3) : c.border,
        ),
      ),
      child: Center(child: child),
    );
  }
}
