import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../providers.dart';
import 'draft_sync_service.dart';

/// The drafts/sync status list: pending, synced, and needs-attention states,
/// with retry/discard actions and a manual "Sync now" (ADR 020/033).
///
/// An unsynced draft's performed date can be edited locally within the same
/// three-day window as entry; a synced workout offers "Correct date", which
/// calls the service and surfaces an offline/refusal error (ADR 020/035).
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
            Text(
                '${draft.workingSetCount} working sets · ${draft.statusLabel}'),
            if (draft.versionDifferenceLabel != null)
              Text(
                draft.versionDifferenceLabel!,
                style: Theme.of(context).textTheme.bodySmall,
              ),
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
            if (!draft.isSynced && !draft.inFlight)
              IconButton(
                tooltip: 'Edit date',
                onPressed: () => _editPendingDate(context, ref),
                icon: const Icon(Icons.edit_calendar_outlined),
              ),
            if (draft.needsAttention)
              IconButton(
                tooltip: 'Retry',
                onPressed: () => sync.retryDraft(draft.clientSessionId),
                icon: const Icon(Icons.refresh),
              ),
            if (draft.isSynced && draft.serverSessionId != null)
              IconButton(
                tooltip: 'Correct date',
                onPressed: () => _correctSyncedDate(context, ref),
                icon: const Icon(Icons.history_toggle_off),
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

  /// Opens the shared window picker and stores the edited date locally.
  Future<void> _editPendingDate(BuildContext context, WidgetRef ref) async {
    final DateTime? picked = await _pickWithinWindow(context);
    if (picked == null) {
      return;
    }
    await ref.read(draftSyncServiceProvider).updatePendingPerformedDate(
        draft.clientSessionId, formatPerformedDate(picked));
  }

  Future<void> _correctSyncedDate(BuildContext context, WidgetRef ref) async {
    final DateTime? picked = await _pickWithinWindow(context);
    if (picked == null) {
      return;
    }
    try {
      await ref.read(draftSyncServiceProvider).correctSyncedPerformedDate(
          draft.clientSessionId, formatPerformedDate(picked));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Date corrected.')),
        );
      }
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
      }
    }
  }

  Future<DateTime?> _pickWithinWindow(BuildContext context) {
    final DateTime? capturedAt = DateTime.tryParse(draft.capturedAt);
    final PerformedDateWindow window =
        performedDateWindow(captureAt: capturedAt);
    final DateTime current =
        DateTime.tryParse(draft.performedDate) ?? window.last;
    return showDatePicker(
      context: context,
      initialDate: window.clamp(current),
      firstDate: window.first,
      lastDate: window.last,
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
