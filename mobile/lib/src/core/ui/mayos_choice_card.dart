import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// A large, expressive selectable option. Selection is communicated by border,
/// a check indicator, and semantics — not by color alone.
class MayosChoiceCard extends StatelessWidget {
  const MayosChoiceCard({
    super.key,
    required this.title,
    required this.selected,
    required this.onTap,
    this.subtitle,
    this.leading,
    this.trailing,
    this.padding = const EdgeInsets.all(MayosSpacing.md),
  });

  final String title;
  final String? subtitle;
  final bool selected;
  final VoidCallback? onTap;
  final Widget? leading;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    final Color border = selected ? c.selectedBorder : c.border;
    final Color background = selected ? c.selectedSurface : c.surface;

    return Semantics(
      button: true,
      selected: selected,
      label: subtitle == null ? title : '$title. $subtitle',
      excludeSemantics: true,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOutCubic,
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: border, width: selected ? 1.6 : 1),
        ),
        clipBehavior: Clip.antiAlias,
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            onTap: onTap,
            child: Padding(
              padding: padding,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: <Widget>[
                  if (leading != null) ...<Widget>[
                    leading!,
                    const SizedBox(width: MayosSpacing.md),
                  ],
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(title, style: text.titleMedium),
                        if (subtitle != null) ...<Widget>[
                          const SizedBox(height: MayosSpacing.xxs),
                          Text(
                            subtitle!,
                            style: text.bodySmall
                                ?.copyWith(color: c.textSecondary),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(width: MayosSpacing.sm),
                  trailing ??
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 180),
                        width: 24,
                        height: 24,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: selected ? c.accent : Colors.transparent,
                          border: Border.all(
                            color: selected ? c.accent : c.borderStrong,
                            width: 1.5,
                          ),
                        ),
                        child: selected
                            ? Icon(Icons.check, size: 16, color: c.onAccent)
                            : null,
                      ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
