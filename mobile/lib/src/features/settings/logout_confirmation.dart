import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/active_workout.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/settings_copy.dart';
import '../../providers.dart';
import '../player/workout/active_workout_controller.dart';
import '../player/workout/draft_sync_service.dart';

enum _LogoutChoice { keep, discard }

/// Signs the account out after warning about unsynced workout drafts.
///
/// Logout must never silently destroy unsynced drafts: warn, and let the
/// player explicitly keep or discard them (ADR 020/033). Shared by Settings
/// and the mode sheet (#119).
Future<void> confirmLogout(BuildContext context, WidgetRef ref) async {
  final String? accountId =
      ref.read(authControllerProvider).session?.account.accountId;
  if (ref.read(webDirectWorkoutCommitEnabledProvider)) {
    if (!await _confirmWebLogout(context, ref, accountId)) {
      return;
    }
    await ref.read(authControllerProvider.notifier).logout();
    return;
  }
  final DraftSyncService sync = ref.read(draftSyncServiceProvider);
  final int unsynced =
      accountId == null ? 0 : await sync.unsyncedCountFor(accountId);
  if (!context.mounted) return;

  if (unsynced > 0) {
    final SettingsCopy copy = settingsCopyOf(context);
    final _LogoutChoice? choice = await showDialog<_LogoutChoice>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(copy.unsyncedWorkouts),
        content: Text(
          copy.unsyncedDraftWarning(unsynced),
          textDirection: copy.isArabic ? TextDirection.ltr : null,
          textAlign: copy.isArabic ? TextAlign.end : null,
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(copy.cancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(_LogoutChoice.discard),
            child: Text(copy.discardDraftsAndLogOut),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(_LogoutChoice.keep),
            child: Text(copy.keepDraftsAndLogOut),
          ),
        ],
      ),
    );
    if (choice == null) {
      return;
    }
    if (choice == _LogoutChoice.discard && accountId != null) {
      await sync.discardAllForAccount(accountId);
    }
  }
  await ref.read(authControllerProvider.notifier).logout();
}

Future<bool> _confirmWebLogout(
  BuildContext context,
  WidgetRef ref,
  String? accountId,
) async {
  if (accountId == null) {
    return true;
  }
  final ActiveWorkoutController controller =
      ref.read(activeWorkoutControllerProvider.notifier);
  await controller.syncAccount(accountId);
  final ActiveWorkout? workout = controller.workout;
  if (!context.mounted) {
    return false;
  }
  if (workout == null) {
    return true;
  }
  final bool? discard = await showDialog<bool>(
    context: context,
    builder: (BuildContext context) => AlertDialog(
      title: Text(settingsCopyOf(context).discardUnfinishedWorkout),
      content: Text(settingsCopyOf(context).logoutDiscardsBrowserWorkout),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(settingsCopyOf(context).cancel),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(settingsCopyOf(context).discardAndLogOut),
        ),
      ],
    ),
  );
  if (discard != true || !context.mounted) {
    return false;
  }
  await controller.discard(accountId: accountId, workoutId: workout.id);
  return true;
}
