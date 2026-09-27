import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
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
    final MayosThemeExtension c = MayosTheme.of(context);
    if (!ref.watch(offlineWorkoutDraftsEnabledProvider)) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Text(
            'Offline workout drafts are available in the Android app.',
            textAlign: TextAlign.center,
            style: MayosTypography.body.copyWith(color: c.textSecondary),
          ),
        ),
      );
    }
    final DraftSyncService sync = ref.watch(draftSyncServiceProvider);
    final List<WorkoutDraft> drafts = sync.drafts;
    final int pending = drafts.where((WorkoutDraft d) => d.isUnsynced).length;
    final int synced = drafts.where((WorkoutDraft d) => d.isSynced).length;
    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(MayosSpacing.lg, MayosSpacing.md,
              MayosSpacing.lg, MayosSpacing.xs),
          child: Wrap(
            spacing: MayosSpacing.sm,
            runSpacing: MayosSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            alignment: WrapAlignment.spaceBetween,
            children: <Widget>[
              Text(
                drafts.isEmpty
                    ? 'No drafts yet.'
                    : '$pending pending · $synced synced',
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textSecondary),
              ),
              MayosButton(
                label: 'Sync now',
                icon: Icons.sync,
                variant: MayosButtonVariant.secondary,
                expand: false,
                loading: sync.isSyncing,
                onPressed: sync.isSyncing ? null : sync.syncNow,
              ),
            ],
          ),
        ),
        Expanded(
          child: drafts.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(MayosSpacing.xl),
                    child: Text(
                      'Workouts you log offline appear here until they sync.',
                      textAlign: TextAlign.center,
                      style:
                          MayosTypography.body.copyWith(color: c.textSecondary),
                    ),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(
                      MayosSpacing.lg, 0, MayosSpacing.lg, MayosSpacing.xxl),
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
    final MayosThemeExtension c = MayosTheme.of(context);
    final DraftSyncService sync = ref.watch(draftSyncServiceProvider);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                _statusIcon(context),
                const SizedBox(width: MayosSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        '${draft.dayName} · ${draft.performedDate}',
                        style: MayosTypography.exerciseTitle
                            .copyWith(color: c.textPrimary),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${draft.workingSetCount} working sets · ${draft.statusLabel}',
                        style: MayosTypography.bodySecondary
                            .copyWith(color: c.textSecondary),
                      ),
                      if (draft.versionDifferenceLabel != null) ...<Widget>[
                        const SizedBox(height: 2),
                        Text(
                          draft.versionDifferenceLabel!,
                          style: MayosTypography.caption
                              .copyWith(color: c.textMuted),
                        ),
                      ],
                      if (draft.lastError != null &&
                          draft.needsAttention) ...<Widget>[
                        const SizedBox(height: 2),
                        Text(
                          draft.lastError!,
                          style:
                              MayosTypography.caption.copyWith(color: c.danger),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: <Widget>[
                if (!draft.isSynced && !draft.inFlight)
                  IconButton(
                    icon: const Icon(Icons.edit_calendar_outlined),
                    tooltip: 'Edit date',
                    onPressed: () => _editPendingDate(context, ref),
                  ),
                if (draft.needsAttention)
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    tooltip: 'Retry',
                    onPressed: () => sync.retryDraft(draft.clientSessionId),
                  ),
                if (draft.isSynced && draft.serverSessionId != null)
                  IconButton(
                    icon: const Icon(Icons.history_toggle_off),
                    tooltip: 'Correct date',
                    onPressed: () => _correctSyncedDate(context, ref),
                  ),
                if (draft.isUnsynced)
                  IconButton(
                    icon: const Icon(Icons.delete_outline),
                    tooltip: 'Discard draft',
                    onPressed: () => sync.discardDraft(draft.clientSessionId),
                  ),
              ],
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

  Widget _statusIcon(BuildContext context) {
    if (draft.isSynced) {
      return Icon(Icons.cloud_done, color: MayosTheme.of(context).success);
    }
    if (draft.needsAttention) {
      return Icon(Icons.error_outline, color: MayosTheme.of(context).warning);
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
