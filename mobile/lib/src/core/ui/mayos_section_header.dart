import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// A section title with optional supporting line and trailing action. Uses
/// typography and spacing for structure instead of a card.
class MayosSectionHeader extends StatelessWidget {
  const MayosSectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
    this.padding = const EdgeInsets.only(bottom: MayosSpacing.sm),
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    return Padding(
      padding: padding,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(title, style: text.headlineSmall),
                if (subtitle != null) ...<Widget>[
                  const SizedBox(height: MayosSpacing.xxs),
                  Text(
                    subtitle!,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ],
              ],
            ),
          ),
          if (trailing != null) ...<Widget>[
            const SizedBox(width: MayosSpacing.sm),
            trailing!,
          ],
        ],
      ),
    );
  }
}
