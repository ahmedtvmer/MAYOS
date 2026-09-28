import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
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
