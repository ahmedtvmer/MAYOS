import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_workout.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
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

/// The confirmation the logger's top-bar menu raises before it discards the
/// workout (#159): the Resume prompt's own dialog, so the wording and the
/// Discard effect are one thing rather than two. Resolves true only for
/// Discard — the Resume button and any dismissal keep the workout, exactly
/// as the prompt does (#123 item 13).
Future<bool> confirmDiscardWorkout(
  BuildContext context, {
  required ActiveWorkout activeWorkout,
}) async {
  final ActiveWorkoutPromptChoice? choice = await showActiveWorkoutPrompt(
    context,
    activeWorkout: activeWorkout,
    forNewStart: false,
  );
  return choice == ActiveWorkoutPromptChoice.discard;
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
