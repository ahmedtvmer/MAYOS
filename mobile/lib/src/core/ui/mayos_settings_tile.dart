import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';

/// A settings/list row: a soft icon chip, a title, optional subtitle, and a
/// trailing affordance. Minimum 56dp tall.
class MayosSettingsTile extends StatelessWidget {
  const MayosSettingsTile({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.onTap,
    this.trailing,
    this.destructive = false,
    this.badge,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
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
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: destructive ? c.accentSubtle : c.surfaceSunken,
                    borderRadius: BorderRadius.circular(11),
                    border: Border.all(
                        color: destructive
                            ? c.danger.withValues(alpha: 0.3)
                            : c.border),
                  ),
                  child: Icon(icon, size: 19, color: accentColor),
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
                        Text(
                          subtitle!,
                          style: text.bodySmall?.copyWith(color: c.textMuted),
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
                    child: Text(
                      '$badge',
                      style: text.labelSmall?.copyWith(color: c.onDanger),
                    ),
                  ),
                  const SizedBox(width: MayosSpacing.xs),
                ],
                trailing ??
                    Icon(
                      Icons.chevron_right,
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
