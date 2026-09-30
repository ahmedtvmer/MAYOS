import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_request_sheet.dart';

class CoachListDetail extends StatelessWidget {
  const CoachListDetail({
    super.key,
    required this.list,
    required this.detail,
    this.listKey,
    this.detailKey,
  });

  final Widget list;
  final Widget detail;
  final Key? listKey;
  final Key? detailKey;

  @override
  Widget build(BuildContext context) => Row(
        children: <Widget>[
          SizedBox(
            key: listKey,
            width: MayosLayout.coachListPaneWidth,
            child: list,
          ),
          const VerticalDivider(width: MayosBorderWidths.hairline),
          Expanded(key: detailKey, child: detail),
        ],
      );
}

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

/// The coach's read order for program requests (#121): pending first, oldest
/// first, then answered most recently resolved first — the order
/// `GET /coach/program-requests` returns (#118), applied client-side to the
/// per-assignment list so the Requests tab and the player-page segment read
/// the same way.
List<ProgramRequest> sortCoachRequests(Iterable<ProgramRequest> requests) {
  final List<ProgramRequest> sorted = List<ProgramRequest>.of(requests);
  sorted.sort((ProgramRequest a, ProgramRequest b) {
    if (a.isPending != b.isPending) {
      return a.isPending ? -1 : 1;
    }
    if (a.isPending) {
      final int byCreated = a.createdAt.compareTo(b.createdAt);
      return byCreated != 0
          ? byCreated
          : a.requestId.compareTo(b.requestId);
    }
    final String resolvedA = a.resolvedAt ?? a.createdAt;
    final String resolvedB = b.resolvedAt ?? b.createdAt;
    final int byResolved = resolvedB.compareTo(resolvedA);
    return byResolved != 0
        ? byResolved
        : a.requestId.compareTo(b.requestId);
  });
  return sorted;
}

/// The shared post-resolve flow for the Requests tab and the player page
/// (#121), mirroring [applyCoachAlertAction]: the applied/declined snackbar,
/// the roster-chip revision, the Requests-badge revision when the caller is
/// not the Requests tab itself, the caller's [reload], and the refusal branch
/// — the readable message lands after the refresh so a request answered
/// elsewhere shows its true state.
///
/// Only resolving actions run this, never a plain load, so the revision bumps
/// cannot loop; [notifyRequestsTab] is false for the tab, which republishes
/// the badge count from its own reload.
Future<void> applyCoachRequestAction(
  WidgetRef ref, {
  required BuildContext context,
  required CoachRequestResolution result,
  required Future<void> Function() reload,
  required void Function(String message) showError,
  required bool notifyRequestsTab,
}) async {
  if (result.resolved) {
    final ProgramRequest request = result.request!;
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(request.isApplied
              ? 'Program request applied.'
              : 'Program request declined.'),
        ),
      );
    }
  } else if (result.message == null) {
    // Closed without acting: nothing changed.
    return;
  }
  // A landing action and a refusal alike can change the roster chip, and a
  // refusal usually means the request was answered elsewhere, so the badge
  // must refresh too.
  ref.read(coachRosterRevisionProvider.notifier).state++;
  if (notifyRequestsTab) {
    ref.read(coachRequestsRevisionProvider.notifier).state++;
  }
  await reload();
  final String? message = result.message;
  if (message != null && context.mounted) {
    showError(message);
  }
}

/// One request row as both coach surfaces show it (#121): the player and day,
/// the swap or new split, the player's reason, the status, and — once
/// answered — the coach's own reply. Only a pending row is tappable, and it
/// opens the resolve sheet through [onTap].
class CoachRequestCard extends StatelessWidget {
  const CoachRequestCard({
    super.key,
    required this.request,
    this.playerUsername,
    this.onTap,
    this.selected = false,
  });

  final ProgramRequest request;
  final String? playerUsername;
  final VoidCallback? onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String player = playerUsername ??
        request.playerUsername ??
        'Player';
    final DateTime? sent = DateTime.tryParse(request.createdAt);
    return MayosCard(
      key: Key('request_card_${request.requestId}'),
      onTap: request.isPending ? onTap : null,
      selected: selected,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                request.isExerciseSubstitution
                    ? Icons.swap_horiz
                    : Icons.calendar_view_week,
                size: 20,
                color: c.accent,
              ),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: Text(
                  request.dayName == null ? player : '$player · ${request.dayName}',
                  style:
                      MayosTypography.caption.copyWith(color: c.textSecondary),
                ),
              ),
              coachRequestStatusChip(context, request),
            ],
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            coachRequestTitle(request),
            style:
                MayosTypography.exerciseTitle.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            '“${request.reason}”',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
          ),
          if (request.hasResponse) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            Text(
              'You: ${request.response}',
              style: MayosTypography.caption.copyWith(color: c.textSecondary),
            ),
          ],
          if (request.isPending) ...<Widget>[
            const SizedBox(height: MayosSpacing.xxs),
            Text(
              sent == null
                  ? 'Sent ${request.createdAt} · tap to review'
                  : 'Sent ${isoDateOf(sent)} · tap to review',
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ],
        ],
      ),
    );
  }
}
