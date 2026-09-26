import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models.dart';
import '../../../providers.dart';
import 'draft_sync_service.dart';

/// The drafts/sync status list: pending, synced, and needs-attention states,
/// with retry/discard actions and a manual "Sync now" (ADR 020/033).
class WorkoutDraftsScreen extends ConsumerWidget {
  const WorkoutDraftsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!ref.watch(offlineWorkoutDraftsEnabledProvider)) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Offline workout drafts are available in the Android app.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    final DraftSyncService sync = ref.watch(draftSyncServiceProvider);
    final List<WorkoutDraft> drafts = sync.drafts;
    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  drafts.isEmpty
                      ? 'No drafts yet.'
                      : '${drafts.where((WorkoutDraft d) => d.isUnsynced).length} pending · ${drafts.where((WorkoutDraft d) => d.isSynced).length} synced',
                ),
              ),
              FilledButton.tonalIcon(
                onPressed: sync.isSyncing ? null : sync.syncNow,
                icon: sync.isSyncing
                    ? const SizedBox(
                        height: 16,
                        width: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.sync),
                label: const Text('Sync now'),
              ),
            ],
          ),
        ),
        Expanded(
          child: drafts.isEmpty
              ? const Center(
                  child: Text(
                    'Workouts you log offline appear here until they sync.',
                    textAlign: TextAlign.center,
                  ),
                )
              : ListView(
                  children: <Widget>[
                    for (final WorkoutDraft draft in drafts)
                      _DraftTile(draft: draft),
                  ],
                ),
        ),
      ],
    );
  }
}

class _DraftTile extends ConsumerWidget {
  const _DraftTile({required this.draft});

  final WorkoutDraft draft;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final DraftSyncService sync = ref.watch(draftSyncServiceProvider);
    return Card(
      child: ListTile(
        leading: _statusIcon(),
        title: Text('${draft.dayName} · ${draft.performedDate}'),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('${draft.workingSetCount} working sets · ${draft.statusLabel}'),
            if (draft.lastError != null && draft.needsAttention)
              Text(
                draft.lastError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            if (draft.needsAttention)
              IconButton(
                tooltip: 'Retry',
                onPressed: () => sync.retryDraft(draft.clientSessionId),
                icon: const Icon(Icons.refresh),
              ),
            if (draft.isUnsynced)
              IconButton(
                tooltip: 'Discard draft',
                onPressed: () => sync.discardDraft(draft.clientSessionId),
                icon: const Icon(Icons.delete_outline),
              ),
          ],
        ),
      ),
    );
  }

  Widget _statusIcon() {
    if (draft.isSynced) {
      return const Icon(Icons.cloud_done, color: Colors.green);
    }
    if (draft.needsAttention) {
      return const Icon(Icons.error_outline, color: Colors.orange);
    }
    if (draft.inFlight) {
      return const SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    }
    return const Icon(Icons.cloud_upload_outlined);
  }
}
