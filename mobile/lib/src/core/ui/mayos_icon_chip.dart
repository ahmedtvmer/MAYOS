import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// The soft square that frames a row's leading icon.
///
/// Extracted from `MayosSettingsTile` so every settings-like row shares one
/// treatment: a [kMayosIconChipSize] box in the theme's sunken surface colour,
/// the [MayosRadii.medium] corner, and a danger-washed border on destructive
/// rows. The glyph inside is sized with [MayosIconSizes], never a raw pixel.
class MayosIconChip extends StatelessWidget {
  const MayosIconChip({
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      width: kMayosIconChipSize,
      height: kMayosIconChipSize,
      decoration: BoxDecoration(
        color: destructive ? c.accentSubtle : c.surfaceSunken,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(
          color: destructive ? c.danger.withValues(alpha: 0.3) : c.border,
        ),
      ),
      child: Center(child: child),
    );
  }
}
