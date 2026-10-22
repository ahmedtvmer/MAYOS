import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/models.dart';
import '../../../core/performed_date_window.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/myos_button.dart';
import '../../../core/ui/myos_card.dart';
import '../../../core/ui/first_strong_direction.dart';
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    if (!ref.watch(offlineWorkoutDraftsEnabledProvider)) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MyosSpacing.xl),
          child: Text(
            copy.androidDraftsUnavailable,
            textAlign: TextAlign.center,
            style: MyosTypography.of(context).body.copyWith(color: c.textSecondary),
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
          padding: const EdgeInsetsDirectional.fromSTEB(MyosSpacing.lg,
              MyosSpacing.md, MyosSpacing.lg, MyosSpacing.xs),
          child: Wrap(
            spacing: MyosSpacing.sm,
            runSpacing: MyosSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            alignment: WrapAlignment.spaceBetween,
            children: <Widget>[
              Text(
                drafts.isEmpty
                    ? copy.noDraftsYet
                    : copy.draftsCounts(pending, synced),
                textAlign: copy.isArabic ? TextAlign.end : null,
                style: MyosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary),
              ),
              MyosButton(
                label: copy.syncNow,
                icon: Icons.sync,
                variant: MyosButtonVariant.secondary,
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
                    padding: const EdgeInsets.all(MyosSpacing.xl),
                    child: Text(
                      copy.offlineDraftsExplanation,
                      textAlign: TextAlign.center,
                      style:
                          MyosTypography.of(context).body.copyWith(color: c.textSecondary),
                    ),
                  ),
                )
              : ListView(
                  padding: const EdgeInsetsDirectional.fromSTEB(
                      MyosSpacing.lg, 0, MyosSpacing.lg, MyosSpacing.xxl),
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    final MyosCopy displayCopy = MyosCopy(ref.watch(displayLanguageProvider));
    final DraftSyncService sync = ref.watch(draftSyncServiceProvider);
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: MyosSpacing.sm),
      child: MyosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                _statusIcon(context),
                const SizedBox(width: MyosSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        '${draft.dayName} · ${draft.performedDate}',
                        style: MyosTypography.of(context).exerciseTitle
                            .copyWith(color: c.textPrimary),
                        textDirection: TextDirection.ltr,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${copy.workingSetCount(draft.workingSetCount)} · ${copy.draftStatus(draft.status)}',
                        style: MyosTypography.of(context).bodySecondary
                            .copyWith(color: c.textSecondary),
                        textAlign: copy.isArabic ? TextAlign.end : null,
                      ),
                      if (draft.versionDifferenceLabel != null) ...<Widget>[
                        const SizedBox(height: 2),
                        Text(
                          draft.isHistoricalProgram &&
                                  draft.activeProgramVersionAtSync != null
                              ? copy.historicalProgram(
                                  draft.programVersion,
                                  draft.activeProgramVersionAtSync!,
                                )
                              : draft.versionDifferenceLabel!,
                          style: MyosTypography.of(context).caption
                              .copyWith(color: c.textMuted),
                          textAlign: copy.isArabic ? TextAlign.end : null,
                        ),
                      ],
                      if (draft.lastError != null &&
                          draft.needsAttention) ...<Widget>[
                        const SizedBox(height: 2),
                        FirstStrongDirection(
                          text: displayCopy.failureMessage(
                            draft.lastErrorFailure ??
                                ServerFailureMessage(draft.lastError!),
                          ),
                          child: Text(
                            displayCopy.failureMessage(
                              draft.lastErrorFailure ??
                                  ServerFailureMessage(draft.lastError!),
                            ),
                            style: MyosTypography.of(context).caption
                                .copyWith(color: c.danger),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: MyosSpacing.xs),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: <Widget>[
                if (!draft.isSynced && !draft.inFlight)
                  IconButton(
                    icon: const Icon(Icons.edit_calendar_outlined),
                    tooltip: copy.editDate,
                    onPressed: () => _editPendingDate(context, ref),
                  ),
                if (draft.needsAttention)
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    tooltip: copy.retry,
                    onPressed: () => sync.retryDraft(draft.clientSessionId),
                  ),
                if (draft.isSynced && draft.serverSessionId != null)
                  IconButton(
                    icon: const Icon(Icons.history_toggle_off),
                    tooltip: copy.correctDate,
                    onPressed: () => _correctSyncedDate(context, ref),
                  ),
                if (draft.isUnsynced)
                  IconButton(
                    icon: const Icon(Icons.delete_outline),
                    tooltip: copy.discardDraft,
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
          SnackBar(content: Text(workoutCopyOf(context).dateCorrected)),
        );
      }
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              MyosCopy(ref.read(displayLanguageProvider))
                  .failureMessage(apiFailureMessage(error)),
            ),
          ),
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
      return Icon(Icons.cloud_done, color: MyosTheme.of(context).success);
    }
    if (draft.needsAttention) {
      return Icon(Icons.error_outline, color: MyosTheme.of(context).warning);
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
