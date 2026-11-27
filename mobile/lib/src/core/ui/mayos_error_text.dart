import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

/// An inline error message: a warning icon followed by the text, both in the
/// danger colour.
///
/// Danger shares the brand red (#885), so an error must never rely on colour
/// alone; the icon marks it as an error.
class MayosErrorText extends StatelessWidget {
  const MayosErrorText(
    this.message, {
    super.key,
    this.style,
    this.textAlign,
    this.color,
  });

  final String message;

  /// Base text style; the danger colour is applied on top.
  final TextStyle? style;
  final TextAlign? textAlign;

  /// Overrides the danger colour (for example on the wallpaper theme).
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final Color tone = color ?? MayosTheme.of(context).danger;
    final TextStyle base = style ?? MayosTypography.of(context).bodySecondary;
    final double iconSize = (base.fontSize ?? 14) + 2;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Padding(
          padding: const EdgeInsetsDirectional.only(top: 1),
          child: Icon(Icons.error_outline, size: iconSize, color: tone),
        ),
        const SizedBox(width: MayosSpacing.xs),
        Flexible(
          child: Text(
            message,
            textAlign: textAlign,
            style: base.copyWith(color: tone),
          ),
        ),
      ],
    );
  }
}
