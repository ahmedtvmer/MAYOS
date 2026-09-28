import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../providers.dart';

/// A tinted caption pill — the roster's urgency chips and the alert state
/// chip (#120). Colour comes from the theme tokens, type from
/// [MayosTypography.caption].
Widget coachPillChip(BuildContext context, String label, Color color) {
  return Container(
    padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: MayosRadii.pillRadius,
    ),
    child: Text(label, style: MayosTypography.caption.copyWith(color: color)),
  );
}

/// The theme colour of a coach alert's state: danger while new, warning while
/// acknowledged, muted once resolved (#120).
Color coachAlertStateColor(BuildContext context, String state) {
  final MayosThemeExtension c = MayosTheme.of(context);
  return switch (state) {
    'new' => c.danger,
    'acknowledged' => c.warning,
    _ => c.textMuted,
  };
}

/// The alert's state as a pill chip, as shown on the player page and in the
/// alert centre (#120).
Widget coachAlertStateChip(BuildContext context, CoachAlert alert) {
  return coachPillChip(
    context,
    alert.stateLabel,
    coachAlertStateColor(context, alert.state),
  );
}

/// Acknowledges or resolves one coach alert through [action] and publishes
/// the side effects both tabs share (#120): the shell badge loses a `new`
/// alert it lost, and the Alerts tab and the Roster tab refetch.
///
/// [wasNew] is the state before the call, so an acknowledged alert resolving
/// leaves the badge alone. Only callers' actions run this, never a plain load,
/// so the revision bumps cannot loop.
Future<CoachAlert> applyCoachAlertAction(
  WidgetRef ref,
  Future<CoachAlert> Function() action, {
  required bool wasNew,
}) async {
  final CoachAlert updated = await action();
  if (wasNew) {
    final int count = ref.read(coachNewAlertsCountProvider);
    ref.read(coachNewAlertsCountProvider.notifier).state =
        count > 0 ? count - 1 : 0;
  }
  ref.read(coachAlertsRevisionProvider.notifier).state++;
  ref.read(coachRosterRevisionProvider.notifier).state++;
  return updated;
}
