import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import 'coach_shared.dart';

/// What [showCoachRequestResolveSheet] reports back: the updated request when
/// the coaching action landed, the readable service refusal otherwise, or
/// nothing when the coach closed the sheet without acting (#121).
class CoachRequestResolution {
  const CoachRequestResolution.resolved(this.request) : message = null;
  const CoachRequestResolution.failed(this.message) : request = null;
  const CoachRequestResolution.dismissed()
      : request = null,
        message = null;

  /// The request as the service returned it, after apply or decline.
  final ProgramRequest? request;

  /// The service's readable refusal (the request may have been answered
  /// elsewhere); null when nothing failed.
  final String? message;

  /// True when the request was applied or declined.
  bool get resolved => request != null;
}

enum CoachRequestDecision { apply, decline }

Future<CoachRequestResolution> resolveCoachProgramRequest({
  required ApiClient api,
  required ProgramRequest request,
  required CoachRequestDecision decision,
  String reply = '',
}) async {
  try {
    final ProgramRequest updated = switch (decision) {
      CoachRequestDecision.apply => await api.applyCoachProgramRequest(
          request.assignmentId, request.requestId),
      CoachRequestDecision.decline => await api.declineCoachProgramRequest(
          request.assignmentId, request.requestId, reply: reply),
    };
    return CoachRequestResolution.resolved(updated);
  } on ApiException catch (error) {
    return CoachRequestResolution.failed(error.message);
  }
}

class CoachRequestDecisionControls extends StatefulWidget {
  const CoachRequestDecisionControls({
    super.key,
    required this.request,
    required this.replyController,
    required this.busy,
    required this.onDecision,
  });

  final ProgramRequest request;
  final TextEditingController replyController;
  final bool busy;
  final ValueChanged<CoachRequestDecision> onDecision;

  @override
  State<CoachRequestDecisionControls> createState() =>
      _CoachRequestDecisionControlsState();
}

class _CoachRequestDecisionControlsState
    extends State<CoachRequestDecisionControls> {
  @override
  Widget build(BuildContext context) {
    final bool canDecline = widget.replyController.text.trim().isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosButton(
          key: const Key('request_apply_button'),
          label: widget.request.isExerciseSubstitution
              ? 'Apply swap'
              : 'Apply (rebuilds program)',
          loading: widget.busy,
          onPressed: widget.busy
              ? null
              : () => widget.onDecision(CoachRequestDecision.apply),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('request_reply_field'),
          controller: widget.replyController,
          label: 'Reason for declining (shown to the player)',
          helperText: 'Sent only with Decline · up to 500 characters.',
          minLines: 1,
          maxLines: 3,
          maxLength: 500,
          enabled: !widget.busy,
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('request_decline_button'),
          label: 'Decline',
          variant: MayosButtonVariant.secondary,
          loading: widget.busy,
          onPressed: widget.busy || !canDecline
              ? null
              : () => widget.onDecision(CoachRequestDecision.decline),
        ),
      ],
    );
  }
}

/// The swap as the coach reads it: **old → new exercise**, or the new split
/// for a split-change request (#121). Exercise IDs are shown as-is: the
/// catalogue is API-only (`GET /workouts/exercises...`), so no client-side
/// id→name map exists without a new call per request.
String coachRequestTitle(ProgramRequest request) {
  if (request.isExerciseSubstitution) {
    return '${request.exerciseId} → ${request.replacementExerciseId}';
  }
  final String? preference = request.desiredSplitPreference;
  final String base =
      'Split change → ${request.desiredWeeklyFrequency} days/week';
  return preference == null || preference.isEmpty
      ? base
      : '$base · $preference';
}

/// One request's status pill: accent while pending, success once applied,
/// muted otherwise (#121).
Widget coachRequestStatusChip(BuildContext context, ProgramRequest request) {
  final MayosThemeExtension c = MayosTheme.of(context);
  return coachPillChip(
    context,
    request.statusLabel,
    request.isPending
        ? c.accent
        : request.isApplied
            ? c.success
            : c.textMuted,
  );
}

/// The resolve sheet (#121): the player, the swap or the new split, the
/// player's reason, and the two coaching actions — **Apply swap** (or **Apply
/// (rebuilds program)** for a split change), which never sends a reply, and
/// **Decline**, which requires the player-visible reason below it (ADR 027,
/// min 1 and at most 500 characters). The sheet runs the call and reports
/// back through [CoachRequestResolution], so the caller owns the list refresh
/// and the revision bumps.
Future<CoachRequestResolution> showCoachRequestResolveSheet(
  BuildContext context, {
  required ProgramRequest request,
  String? playerUsername,
}) {
  return showModalBottomSheet<CoachRequestResolution>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) => _ResolveRequestSheet(
      request: request,
      playerUsername: playerUsername ?? request.playerUsername,
    ),
  ).then((CoachRequestResolution? result) =>
      result ?? const CoachRequestResolution.dismissed());
}

class _ResolveRequestSheet extends ConsumerStatefulWidget {
  const _ResolveRequestSheet({
    required this.request,
    this.playerUsername,
  });

  final ProgramRequest request;
  final String? playerUsername;

  @override
  ConsumerState<_ResolveRequestSheet> createState() =>
      _ResolveRequestSheetState();
}

class _ResolveRequestSheetState extends ConsumerState<_ResolveRequestSheet> {
  final TextEditingController _declineReason = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _declineReason.dispose();
    super.dispose();
  }

  Future<void> _run(CoachRequestDecision decision) async {
    setState(() => _busy = true);
    final CoachRequestResolution result = await resolveCoachProgramRequest(
      api: ref.read(apiClientProvider),
      request: widget.request,
      decision: decision,
      reply: _declineReason.text.trim(),
    );
    if (!mounted) return;
    Navigator.of(context).pop(result);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProgramRequest request = widget.request;
    return Padding(
      key: const Key('resolve_request_sheet'),
      padding: EdgeInsets.fromLTRB(
        MayosSpacing.lg,
        0,
        MayosSpacing.lg,
        MayosSpacing.lg + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            '${widget.playerUsername ?? 'Player'} asks',
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            coachRequestTitle(request),
            style:
                MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            '${request.dayName ?? 'Whole program'} · program v${request.programVersion}',
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          Text(
            '“${request.reason}”',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.md),
          CoachRequestDecisionControls(
            request: request,
            replyController: _declineReason,
            busy: _busy,
            onDecision: _run,
          ),
        ],
      ),
    );
  }
}
