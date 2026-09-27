import 'package:flutter/material.dart';

import '../theme/mayos_theme.dart';

/// A restrained MAYOS surface. Used only where content genuinely groups, never
/// merely to wrap every text block.
class MayosCard extends StatelessWidget {
  const MayosCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.selected = false,
    this.elevated = false,
    this.color,
    this.borderColor,
    this.radius = 16,
    this.clip = true,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final bool selected;
  final bool elevated;
  final Color? color;
  final Color? borderColor;
  final double radius;
  final bool clip;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color background =
        color ?? (selected ? c.selectedSurface : c.surface);
    final Color side = borderColor ?? (selected ? c.selectedBorder : c.border);
    final BorderRadius borderRadius = BorderRadius.circular(radius);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      decoration: BoxDecoration(
        color: background,
        borderRadius: borderRadius,
        border: Border.all(color: side, width: selected ? 1.5 : 1),
        boxShadow: elevated ? c.shadows : null,
      ),
      clipBehavior: clip ? Clip.antiAlias : Clip.none,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}
