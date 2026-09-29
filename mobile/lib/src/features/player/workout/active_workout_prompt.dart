import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_workout.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/workout_start_notice_store.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'active_workout_controller.dart';

/// What the player chose in the Resume / Discard prompt (#123).
enum ActiveWorkoutPromptChoice { resume, discard, cancel }

/// The minimal Resume / Discard dialog shown while an Active workout exists.
///
/// [forNewStart] switches the wording to the second-workout guard ("finish or
/// discard the current one first"); without it this is the offer shown when
/// the app opens. There is no third button: tapping outside the dialog (or the
/// system back gesture) dismisses it, `showDialog` resolves null, and both
/// call sites treat null as [ActiveWorkoutPromptChoice.cancel], so nothing is
/// ever discarded or started by accident (#123 item 13).
Future<ActiveWorkoutPromptChoice?> showActiveWorkoutPrompt(
  BuildContext context, {
  required ActiveWorkout activeWorkout,
  required bool forNewStart,
}) {
  final MayosThemeExtension c = MayosTheme.of(context);
  return showDialog<ActiveWorkoutPromptChoice>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(
          forNewStart ? 'Finish your current workout' : 'Unfinished workout'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '${activeWorkout.dayName} · started ${_startedLabel(activeWorkout)}',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          Text(
            forNewStart
                ? 'This device is already logging a workout. Resume it, or '
                    'discard it to start a new one.'
                : 'Resume where you left off, or discard this workout.',
            style: MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
          ),
        ],
      ),
      actions: <Widget>[
        MayosButton(
          label: 'Discard',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () =>
              Navigator.of(context).pop(ActiveWorkoutPromptChoice.discard),
        ),
        MayosButton(
          label: 'Resume',
          expand: false,
          onPressed: () =>
              Navigator.of(context).pop(ActiveWorkoutPromptChoice.resume),
        ),
      ],
    ),
  );
}

/// `2026-09-28 10:32` in the device's local zone, for the prompt's caption.
String _startedLabel(ActiveWorkout activeWorkout) {
  final DateTime local = activeWorkout.startedAtClock.toLocal();
  final String hh = local.hour.toString().padLeft(2, '0');
  final String mm = local.minute.toString().padLeft(2, '0');
  return '${activeWorkout.startedDate} $hh:$mm';
}

/// The confirmation the logger's ⋮ menu raises before it discards the
/// workout (#159). It is its own dialog — a player mid-workout is not being
/// offered a Resume — but the Discard action has exactly the effect Discard
/// has in the Resume prompt: the Active workout is cleared and every set
/// logged in it is lost (#123). Resolves true only for Discard; "Keep
/// logging" and any dismissal keep the workout.
Future<bool> confirmDiscardWorkout(BuildContext context) async {
  final MayosThemeExtension c = MayosTheme.of(context);
  final bool? discard = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: const Text('Discard this workout?'),
      content: Text(
        "The sets you've logged in this workout will be lost.",
        style: MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
      ),
      actions: <Widget>[
        MayosButton(
          label: 'Keep logging',
          variant: MayosButtonVariant.secondary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(false),
        ),
        MayosButton(
          label: 'Discard',
          destructive: true,
          expand: false,
          onPressed: () => Navigator.of(context).pop(true),
        ),
      ],
    ),
  );
  return discard ?? false;
}

/// The offer shown when the app opens with an Active workout: Resume routes to
/// its logger, Discard clears it (#123).
Future<void> offerActiveWorkoutOnOpen(
  BuildContext context,
  WidgetRef ref,
) async {
  final ActiveWorkoutController controller =
      ref.read(activeWorkoutControllerProvider.notifier);
  final ActiveWorkout? active = controller.workout;
  if (active == null) {
    return;
  }
  final ActiveWorkoutPromptChoice? choice = await showActiveWorkoutPrompt(
    context,
    activeWorkout: active,
    forNewStart: false,
  );
  if (!context.mounted) {
    return;
  }
  if (choice == ActiveWorkoutPromptChoice.discard) {
    await controller.discard(accountId: active.accountId, workoutId: active.id);
  } else if (choice == ActiveWorkoutPromptChoice.resume) {
    // Pushed, not `go`: the logger must sit on top of the screen the offer
    // was made on, so its back affordance has somewhere to return to (#156).
    context.push('$logWorkoutPath/${active.dayOrder}');
  }
}

/// The second-workout guard: when an Active workout exists it offers Resume /
/// Discard first, then starts the new workout and reports whether the caller
/// may navigate to the logger (#123).
Future<bool> startWorkoutFromDay(
  BuildContext context,
  WidgetRef ref, {
  required ProgramDay day,
  required int? programVersion,
}) async {
  final ActiveWorkoutController controller =
      ref.read(activeWorkoutControllerProvider.notifier);
  final String? accountId =
      ref.read(authControllerProvider).session?.account.accountId;
  if (accountId == null) {
    return false;
  }

  if (controller.hasActive) {
    final ActiveWorkout active = controller.workout!;
    final ActiveWorkoutPromptChoice? choice = await showActiveWorkoutPrompt(
      context,
      activeWorkout: active,
      forNewStart: true,
    );
    if (!context.mounted) {
      return false;
    }
    if (choice == ActiveWorkoutPromptChoice.resume) {
      // Pushed, not `go`, so Back from the logger returns to the screen the
      // guard was raised on (#156).
      context.push('$logWorkoutPath/${active.dayOrder}');
      return false;
    }
    if (choice != ActiveWorkoutPromptChoice.discard) {
      return false;
    }
    await controller.discard(accountId: active.accountId, workoutId: active.id);
    if (!context.mounted) {
      return false;
    }
  }

  if (ref.read(webDirectWorkoutCommitEnabledProvider) &&
      !await _showFirstWebWorkoutNotice(context, ref, accountId)) {
    return false;
  }
  if (!context.mounted) {
    return false;
  }

  final StartWorkoutOutcome outcome = await controller.startFromDay(
    accountId: accountId,
    day: day,
    programVersion: programVersion,
  );
  if (!context.mounted || outcome != StartWorkoutOutcome.started) {
    return false;
  }
  // Pushed, not `go`: the logger sits above Home or Program and Back returns
  // there (#156). `go` replaced the whole stack, leaving the logger as the
  // only page with nothing to pop.
  context.push('$logWorkoutPath/${day.dayOrder}');
  return true;
}

Future<bool> _showFirstWebWorkoutNotice(
  BuildContext context,
  WidgetRef ref,
  String accountId,
) async {
  final WorkoutStartNoticeStore store =
      ref.read(workoutStartNoticeStoreProvider);
  bool seen = false;
  try {
    seen = await store.hasSeenWorkoutStartNotice(accountId);
  } on Object {
    // If browser storage is denied, show the notice again next time.
  }
  if (seen) {
    return true;
  }
  if (!context.mounted) return false;
  final bool? acknowledged = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: const Text('Logging workouts on web'),
      content: const Text(
        'You need a connection to finish saving. An unfinished workout is kept only in this browser.',
      ),
      actions: <Widget>[
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Continue logging'),
        ),
      ],
    ),
  );
  if (acknowledged != true || !context.mounted) {
    return false;
  }
  try {
    await store.markWorkoutStartNoticeSeen(accountId);
  } on Object {
    // If browser storage is denied, show the notice again next time.
  }
  return true;
}
