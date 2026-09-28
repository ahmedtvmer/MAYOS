import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';
import 'coach_shared.dart';

/// The outcome of [showCoachRequestResolveSheet]: the resolved request, or the
/// readable service refusal the caller surfaces before refreshing its list
/// (#121).
class CoachRequestResolution {
  const CoachRequestResolution.applied(this.request)
      : message = null,
        resolved = true;
  const CoachRequestResolution.declined(this.request)
      : message = null,
        resolved = true;
  const CoachRequestResolution.failed(this.message)
      : request = null,
        resolved = false;
  const CoachRequestResolution.dismissed()
      : request = null,
        message = null,
        resolved = false;

  final ProgramRequest? request;
  final String? message;
  final bool resolved;
}

/// The swap as the coach reads it: **old → new exercise**, or the new split
/// for a split-change request (#121).
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
    switch (request.status) {
      'pending' => c.accent,
      'applied' => c.success,
      _ => c.textMuted,
    },
  );
}

/// The resolve sheet (#121): the player, the swap or the new split, the
/// player's reason, an optional reply capped at 500 characters with a counter,
/// and the two coaching actions — **Apply swap** (or **Apply (rebuilds
/// program)** for a split change) and **Decline**. The sheet runs the call and
/// reports back through [CoachRequestResolution], so the caller owns the list
/// refresh and the revision bumps.
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
  final TextEditingController _reply = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _run(
    Future<ProgramRequest> Function(ApiClient api) action,
    CoachRequestResolution Function(ProgramRequest) done,
  ) async {
    setState(() => _busy = true);
    try {
      final ProgramRequest updated =
          await action(ref.read(apiClientProvider));
      if (!mounted) return;
      Navigator.of(context).pop(done(updated));
    } on ApiException catch (error) {
      if (!mounted) return;
      Navigator.of(context).pop(CoachRequestResolution.failed(error.message));
    }
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
          TextField(
            key: const Key('request_reply_field'),
            controller: _reply,
            maxLength: 500,
            maxLines: 3,
            minLines: 1,
            decoration: const InputDecoration(
              labelText: 'Reply to the player (optional)',
              helperText: 'Up to 500 characters.',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            key: const Key('request_apply_button'),
            label: request.isExerciseSubstitution
                ? 'Apply swap'
                : 'Apply (rebuilds program)',
            loading: _busy,
            onPressed: _busy
                ? null
                : () => _run(
                      (ApiClient api) => api.applyCoachProgramRequest(
                        request.assignmentId,
                        request.requestId,
                      ),
                      CoachRequestResolution.applied,
                    ),
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            key: const Key('request_decline_button'),
            label: 'Decline',
            variant: MayosButtonVariant.secondary,
            loading: _busy,
            onPressed: _busy
                ? null
                : () {
                    final String reply = _reply.text.trim();
                    _run(
                      (ApiClient api) => api.declineCoachProgramRequest(
                        request.assignmentId,
                        request.requestId,
                        reply: reply.isEmpty ? null : reply,
                      ),
                      CoachRequestResolution.declined,
                    );
                  },
          ),
        ],
      ),
    );
  }
}
