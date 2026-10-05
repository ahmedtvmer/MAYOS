import 'package:flutter/material.dart';

import '../../../core/personal_records.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';

/// The small `PR kg` / `PR e1RM` badge a record-earning set row shows under
/// itself (#107 resolution, #124).
///
/// The solid form marks the session's current best; [beaten] renders the
/// struck-through, muted version a later set of the same exercise took over
/// from. It carries no value — the celebration line in the workout summary
/// does (#124).
class PersonalRecordBadge extends StatelessWidget {
  const PersonalRecordBadge({
    super.key,
    required this.kind,
    this.beaten = false,
  });

  /// Which record this badge stands for.
  final PrRecordKind kind;

  /// True when a later set has taken the record over.
  final bool beaten;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color fg = beaten ? c.textMuted : c.onWarning;
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: beaten ? 1 : 0.4, end: 1),
      duration: MayosMotion.slow,
      curve: Curves.elasticOut,
      builder: (BuildContext context, double t, Widget? child) =>
          Transform.scale(scale: t, child: child),
      child: Container(
        padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
        decoration: BoxDecoration(
          color: beaten ? Colors.transparent : c.warning,
          border: Border.all(color: beaten ? c.border : c.warning),
          borderRadius: MayosRadii.pillRadius,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(Icons.emoji_events, size: 12, color: fg),
            const SizedBox(width: MayosSpacing.xxs),
            Text(
              workoutCopyOf(context).recordBadge(kind),
              style: MayosTypography.of(context).captionStrong.copyWith(
                color: fg,
                decoration: beaten ? TextDecoration.lineThrough : null,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
