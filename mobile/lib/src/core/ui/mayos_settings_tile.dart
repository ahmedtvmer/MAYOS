import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import 'first_strong_direction.dart';
import 'mayos_icon_chip.dart';

/// A settings/list row: a soft icon chip, a title, optional subtitle, and a
/// trailing affordance. Minimum 56dp tall.
class MayosSettingsTile extends StatelessWidget {
  const MayosSettingsTile({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.subtitleTextDirection,
    this.onTap,
    this.trailing,
    this.destructive = false,
    this.badge,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final TextDirection? subtitleTextDirection;
  final VoidCallback? onTap;
  final Widget? trailing;
  final bool destructive;
  final int? badge;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    final Color accentColor = destructive ? c.danger : c.accent;

    return Semantics(
      button: onTap != null,
      label: subtitle == null ? title : '$title. $subtitle',
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 56),
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xs),
            child: Row(
              children: <Widget>[
                MayosIconChip(
                  destructive: destructive,
                  child: Icon(
                    icon,
                    size: MayosIconSizes.medium,
                    color: accentColor,
                  ),
                ),
                const SizedBox(width: MayosSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: <Widget>[
                      Text(
                        title,
                        style: text.titleSmall?.copyWith(
                          color: destructive ? c.danger : c.textPrimary,
                        ),
                      ),
                      if (subtitle != null) ...<Widget>[
                        const SizedBox(height: 2),
                        subtitleTextDirection == null
                            ? FirstStrongDirection(
                                text: subtitle!,
                                child: Text(
                                  subtitle!,
                                  style: text.bodySmall
                                      ?.copyWith(color: c.textMuted),
                                ),
                              )
                            : Text(
                                subtitle!,
                                textDirection: subtitleTextDirection,
                                style: text.bodySmall
                                    ?.copyWith(color: c.textMuted),
                              ),
                      ],
                    ],
                  ),
                ),
                if (badge != null && badge! > 0) ...<Widget>[
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: c.danger,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Directionality(
                      textDirection: TextDirection.ltr,
                      child: Text(
                        '$badge',
                        style: text.labelSmall?.copyWith(color: c.onDanger),
                      ),
                    ),
                  ),
                  const SizedBox(width: MayosSpacing.xs),
                ],
                trailing ??
                    Icon(
                      Directionality.of(context) == TextDirection.rtl
                          ? Icons.chevron_left
                          : Icons.chevron_right,
                      size: 20,
                      color: c.textMuted,
                    ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
