import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';
import '../theme/myos_theme.dart';

/// A section title with optional supporting line and trailing action. Uses
/// typography and spacing for structure instead of a card.
class MyosSectionHeader extends StatelessWidget {
  const MyosSectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
    this.padding = const EdgeInsets.only(bottom: MyosSpacing.sm),
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
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
                  const SizedBox(height: MyosSpacing.xxs),
                  Text(
                    subtitle!,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ],
              ],
            ),
          ),
          if (trailing != null) ...<Widget>[
            const SizedBox(width: MyosSpacing.sm),
            trailing!,
          ],
        ],
      ),
    );
  }
}
