import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/active_workout.dart';
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
    final _LogoutChoice? choice = await showDialog<_LogoutChoice>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Unsynced workouts'),
        content: Text(
          'You have $unsynced unsynced workout '
          '${unsynced == 1 ? 'draft' : 'drafts'}. '
          'They stay on this device until they sync; logging out will not delete them.',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(_LogoutChoice.discard),
            child: const Text('Discard drafts and log out'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(_LogoutChoice.keep),
            child: const Text('Keep drafts and log out'),
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
      title: const Text('Discard unfinished workout?'),
      content: const Text(
        'Logging out will discard this workout from this browser.',
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Discard and log out'),
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
