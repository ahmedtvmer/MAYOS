import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../providers.dart';
import 'coach_shared.dart';

/// What [showCoachRequestResolveSheet] reports back: the updated request when
/// the coaching action landed, the readable service refusal otherwise, or
/// nothing when the coach closed the sheet without acting (#121).
class CoachRequestResolution {
  const CoachRequestResolution.resolved(this.request) : failure = null;
  const CoachRequestResolution.failed(this.failure) : request = null;
  const CoachRequestResolution.dismissed()
      : request = null,
        failure = null;

  /// The request as the service returned it, after apply or decline.
  final ProgramRequest? request;

  /// Typed app failure or verbatim server detail. Null when nothing failed.
  final FailureMessage? failure;

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
          request.assignmentId, request.requestId,
          reply: reply),
    };
    return CoachRequestResolution.resolved(updated);
  } on ApiException catch (error) {
    return CoachRequestResolution.failed(apiFailureMessage(error));
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
              ? coachCopyOf(context).applySwap
              : coachCopyOf(context).applyAndRebuild,
          loading: widget.busy,
          onPressed: widget.busy
              ? null
              : () => widget.onDecision(CoachRequestDecision.apply),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('request_reply_field'),
          controller: widget.replyController,
          label: coachCopyOf(context).reasonForDeclining,
          helperText: coachCopyOf(context).sentOnlyOnDecline,
          minLines: 1,
          maxLines: 3,
          maxLength: 500,
          enabled: !widget.busy,
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('request_decline_button'),
          label: coachCopyOf(context).decline,
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
/// for a split-change request (#121).
String coachRequestTitle(BuildContext context, ProgramRequest request) =>
    coachCopyOf(context).programRequestTitle(
      isSubstitution: request.isExerciseSubstitution,
      exerciseName: request.exerciseName,
      day: request.dayName,
      replacementName: request.replacementExerciseName,
      frequency: request.desiredWeeklyFrequency,
      preference: request.desiredSplitPreference,
    );

/// One request's status pill: accent while pending, success once applied,
/// muted otherwise (#121).
Widget coachRequestStatusChip(BuildContext context, ProgramRequest request) {
  final MayosThemeExtension c = MayosTheme.of(context);
  return coachPillChip(
    context,
    coachCopyOf(context).requestStatus(request.status),
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
    final copy = coachCopyOf(context);
    final ProgramRequest request = widget.request;
    return Padding(
      key: const Key('resolve_request_sheet'),
      padding: EdgeInsetsDirectional.fromSTEB(
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
            copy.playerAsks(widget.playerUsername ?? copy.player),
            style: MayosTypography.of(context).caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            coachRequestTitle(context, request),
            style:
                MayosTypography.of(context).sectionHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            copy.requestScope(request.dayName, request.programVersion),
            style: MayosTypography.of(context).caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          FirstStrongDirection(
            text: request.reason,
            child: Text(
              '“${request.reason}”',
              style:
                  MayosTypography.of(context).bodySecondary.copyWith(color: c.textPrimary),
            ),
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
