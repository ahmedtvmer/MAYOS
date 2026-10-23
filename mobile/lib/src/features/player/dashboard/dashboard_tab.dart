import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_program.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/api_client.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/personal_records.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/myos_button.dart';
import '../../../core/ui/myos_card.dart';
import '../../../core/ui/myos_section_header.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../program/preparing_program_banner.dart';
import '../workout/active_workout_prompt.dart';
import 'home_planning.dart';
import '../../shared/install_prompt.dart';

/// The player Home tab: current program, the next ordered session, real
/// seven-day volume and recent personal records, with honest empty states.
///
/// No readiness, chart, body metric, recommendation, or invented name appears
/// here; every figure is a real value from the service.
class DashboardTab extends ConsumerStatefulWidget {
  const DashboardTab({super.key});

  @override
  ConsumerState<DashboardTab> createState() => _DashboardTabState();
}

class _DashboardData {
  const _DashboardData({
    required this.program,
    required this.schedule,
    required this.volume,
    required this.records,
    this.latestSession,
    this.unopenedCheckpointReview,
    this.partialError,
    this.assignment,
    this.programFromCache = false,
  });

  final TrainingProgram? program;
  final TrainingSchedule? schedule;
  final Map<String, double> volume;
  final List<PersonalRecord> records;

  /// The player's most recent committed session from the ledger (or its cached
  /// last-known value offline), used to derive the next program day (#53).
  final LatestSession? latestSession;
  final CheckpointReviewListItem? unopenedCheckpointReview;
  final Assignment? assignment;

  /// True when [program] is the offline cached copy after a failed fetch (#54).
  final bool programFromCache;

  /// Set when a non-fatal section failed to load so the body can say so instead
  /// of silently showing an empty section.
  final FailureMessage? partialError;
}

class _DashboardTabState extends ConsumerState<DashboardTab> {
  late Future<_DashboardData> _future;
  Assignment? _assignmentOverride;
  bool _assignmentOverrideKnown = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<_DashboardData> _load() async {
    final ApiClient api = ref.read(apiClientProvider);
    final Future<Assignment?> assignmentFuture = _loadAssignment(api);
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    final cache = ref.read(workoutCacheStoreProvider);
    if (accountId != null) {
      unawaited(
        ref.read(trainingStatusProvider.notifier).refresh(accountId),
      );
    }
    if (accountId != null && ref.read(offlineWorkoutDraftsEnabledProvider)) {
      // Fire-and-forget baselines prefetch: cached on success, never awaited,
      // so Home cannot be delayed or failed by it (#123).
      unawaited(ref.read(baselinesServiceProvider).prefetch(accountId));
    }
    // The active program is shared with the Program tab so an offline launch
    // falls back to the cached copy identically (#54). A missing program is an
    // honest empty state, not an error; a transport failure with no cache
    // rethrows and becomes the Home error state.
    final ActiveProgram active = await loadActiveProgram(
      api: api,
      cache: cache,
      accountId: accountId,
    );
    final TrainingProgram? program = active.program;
    if (accountId != null) {
      final PlayerProgramUpdate? sharedProgram =
          ref.read(playerProgramUpdateProvider);
      if (!active.fromCache || sharedProgram?.accountId != accountId) {
        ref.read(playerProgramUpdateProvider.notifier).state =
            PlayerProgramUpdate(
          accountId: accountId,
          program: program,
          fromCache: active.fromCache,
        );
      }
    }
    TrainingSchedule? schedule;
    Map<String, double> volume = const <String, double>{};
    List<PersonalRecord> records = const <PersonalRecord>[];
    LatestSession? latestSession;
    CheckpointReviewListItem? unopenedCheckpointReview;
    FailureMessage? partialError;
    try {
      schedule = await api.trainingSchedule();
    } on ApiException catch (error) {
      partialError = apiFailureMessage(error);
    }
    try {
      volume = await api.volume();
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    try {
      records = await api.personalRecords();
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    try {
      final List<CheckpointReviewListItem> reviews =
          await api.checkpointReviews();
      for (final CheckpointReviewListItem review in reviews) {
        if (!review.opened) {
          unopenedCheckpointReview = review;
          break;
        }
      }
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    try {
      latestSession = await api.latestSession();
      if (latestSession != null && accountId != null) {
        // Cache the real ledger value so the next day still resolves offline.
        unawaited(cache.writeLatestSession(accountId, latestSession));
      }
    } on ApiException {
      // Offline: fall back to the last-known committed session.
      latestSession =
          accountId == null ? null : await cache.readLatestSession(accountId);
    }
    return _DashboardData(
      program: program,
      schedule: schedule,
      volume: volume,
      records: records,
      latestSession: latestSession,
      unopenedCheckpointReview: unopenedCheckpointReview,
      partialError: partialError,
      assignment: await assignmentFuture,
      programFromCache: active.fromCache,
    );
  }

  Future<Assignment?> _loadAssignment(ApiClient api) async {
    try {
      return await api.myAssignment();
    } on ApiException {
      // The program remains available if assignment details are offline.
      return null;
    }
  }

  Future<void> _refreshAssignment() async {
    try {
      final Assignment? assignment =
          await ref.read(apiClientProvider).myAssignment();
      if (!mounted) return;
      setState(() {
        _assignmentOverrideKnown = true;
        _assignmentOverride = assignment;
      });
    } on ApiException {
      // Keep the last-known assignment when a tab-switch refresh is offline.
    }
  }

  Future<void> _refresh() async {
    final Future<_DashboardData> future = _load();
    setState(() {
      _assignmentOverrideKnown = false;
      _future = future;
    });
    await future;
  }

  void _openExercise(ProgramExercise exercise, int dayOrder) {
    context.push('$exerciseDetailPath/${exercise.exerciseId}?day=$dayOrder');
  }

  void _openDrafts() => context.push(workoutsPath);

  Future<void> _openCheckpointReview(int checkpoint) async {
    await context.push('$checkpointReviewPath/$checkpoint');
    if (mounted) await _refresh();
  }

  void _openProgram() =>
      ref.read(playerShellTabProvider.notifier).state =
          PlayerShellTab.program.index;

  void _logWorkout(
    ProgramDay day,
    int? programVersion,
    int programWeekCount,
  ) {
    // Runs the Resume/Discard guard and creates the Active workout before
    // routing to the logger (#123). The returned future only matters to the
    // guard itself; navigation happens inside it.
    startWorkoutFromDay(
      context,
      ref,
      day: day,
      programVersion: programVersion,
      programWeekCount: programWeekCount,
    );
  }

  @override
  Widget build(BuildContext context) {
    final String? accountId =
        ref.watch(authControllerProvider).session?.account.accountId;
    final PlayerProgramUpdate? sharedProgram =
        ref.watch(playerProgramUpdateProvider);
    ref.listen<int>(playerShellTabProvider, (int? previous, int next) {
      if (next == 0 && previous != 0) {
        unawaited(_refreshAssignment());
      }
    });
    ref.listen<PlayerAssignmentUpdate?>(playerAssignmentUpdateProvider,
        (_, PlayerAssignmentUpdate? update) {
      setState(() {
        _assignmentOverrideKnown = update != null;
        _assignmentOverride = update?.assignment;
      });
    });
    return FutureBuilder<_DashboardData>(
      future: _future,
      builder: (BuildContext context, AsyncSnapshot<_DashboardData> snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const _HomeSkeleton();
        }
        if (snapshot.hasError) {
          final Object error = snapshot.error!;
          final MyosCopy copy = MyosCopy(ref.watch(displayLanguageProvider));
          final String message = error is ApiException
              ? copy.failureMessage(apiFailureMessage(error))
              : displayCopyOf(context).loadHomeFailed;
          return _ErrorView(message: message, onRetry: _refresh);
        }
        final List<WorkoutDraft> drafts =
            ref.watch(draftSyncServiceProvider).drafts;
        final _DashboardData loadedData = snapshot.data!;
        final bool hasSharedProgram =
            sharedProgram != null && sharedProgram.accountId == accountId;
        final LatestSession? latest = snapshot.data!.latestSession;
        return _HomeBody(
          copy: MyosCopy(ref.watch(displayLanguageProvider)),
          data: loadedData,
          program: hasSharedProgram ? sharedProgram.program : loadedData.program,
          programFromCache: hasSharedProgram
              ? sharedProgram.fromCache
              : loadedData.programFromCache,
          assignment: _assignmentOverrideKnown
              ? _assignmentOverride
              : loadedData.assignment,
          onRefresh: _refresh,
          onOpenExercise: _openExercise,
          onOpenDrafts: _openDrafts,
          onOpenCheckpointReview: _openCheckpointReview,
          onOpenProgram: _openProgram,
          onLogWorkout: _logWorkout,
          trainedDays: <TrainedDay>[
            if (latest != null) TrainedDay.fromLatestSession(latest),
            for (final WorkoutDraft draft in drafts)
              TrainedDay.fromDraft(draft),
          ],
          pendingDrafts: drafts.where((WorkoutDraft d) => d.isUnsynced).length,
        );
      },
    );
  }
}

class _HomeBody extends StatelessWidget {
  const _HomeBody({
    required this.copy,
    required this.data,
    required this.program,
    required this.programFromCache,
    required this.assignment,
    required this.onRefresh,
    required this.onOpenExercise,
    required this.onOpenDrafts,
    required this.onOpenCheckpointReview,
    required this.onOpenProgram,
    required this.onLogWorkout,
    required this.trainedDays,
    required this.pendingDrafts,
  });

  final MyosCopy copy;

  final _DashboardData data;
  final TrainingProgram? program;
  final bool programFromCache;
  final Assignment? assignment;
  final Future<void> Function() onRefresh;
  final void Function(ProgramExercise exercise, int dayOrder) onOpenExercise;
  final VoidCallback onOpenDrafts;
  final ValueChanged<int> onOpenCheckpointReview;
  final VoidCallback onOpenProgram;
  final void Function(ProgramDay day, int? programVersion, int programWeekCount)
      onLogWorkout;
  final List<TrainedDay> trainedDays;
  final int pendingDrafts;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final DateTime now = DateTime.now();
    final TrainingProgram? activeProgram = program;
    final ProgramDay? nextDay =
        activeProgram == null ? null : selectNextDay(activeProgram, trainedDays);

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(MyosSpacing.lg, MyosSpacing.md,
            MyosSpacing.lg, MyosSpacing.xxl),
        children: <Widget>[
          const InstallPromptBanner(),
          Text(
            displayCopyOf(context).greetingFor(now),
            style: MyosTypography.of(context).display.copyWith(
              fontSize: 34,
              color: c.textPrimary,
            ),
          ),
          if (programFromCache) ...<Widget>[
            const SizedBox(height: MyosSpacing.sm),
            _InlineNotice(message: displayCopyOf(context).offlineSavedProgram),
          ] else if (data.partialError != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.sm),
            _InlineNotice(message: copy.failureMessage(data.partialError!)),
          ],
          const SizedBox(height: MyosSpacing.xl),
          _ProgramSection(
              program: activeProgram,
              assignment: assignment,
              onOpenProgram: onOpenProgram,
              copy: copy),
          if (pendingDrafts > 0) ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            _DraftsBanner(count: pendingDrafts, onTap: onOpenDrafts),
          ],
          if (data.unopenedCheckpointReview != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            _CheckpointReviewCard(
              copy: copy,
              review: data.unopenedCheckpointReview!,
              onTap: onOpenCheckpointReview,
            ),
          ],
          // No program means no next session to show: the Program tab owns the
          // generate flow, and a training day cannot be derived without one.
          if (nextDay != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.xl),
            _NextSessionSection(
              day: nextDay,
              label: nextSessionLabel(data.schedule, now,
                  isArabic: displayCopyOf(context).isArabic),
              onOpenExercise: onOpenExercise,
              onLogWorkout: () => onLogWorkout(
                nextDay,
                activeProgram?.version,
                activeProgram?.weekCount ?? 1,
              ),
              logEnabled: true,
            ),
          ],
          const SizedBox(height: MyosSpacing.xl),
          _VolumeSection(volume: data.volume),
          const SizedBox(height: MyosSpacing.xl),
          _RecordsSection(records: data.records),
        ],
      ),
    );
  }
}

class _CheckpointReviewCard extends StatelessWidget {
  const _CheckpointReviewCard(
      {required this.review, required this.onTap, required this.copy});

  final CheckpointReviewListItem review;
  final ValueChanged<int> onTap;
  final MyosCopy copy;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return MyosCard(
      padding: EdgeInsets.zero,
      child: ListTile(
        key: const ValueKey<String>('dashboard.checkpoint-review'),
        leading: Icon(Icons.emoji_events_outlined, color: c.accent),
        title: Text(copy.checkpointReview),
        subtitle: Text(
            '${copy.checkpointLabel} ${review.checkpoint} · ${copy.openYourReview}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => onTap(review.checkpoint),
      ),
    );
  }
}

class _ProgramSection extends StatelessWidget {
  const _ProgramSection(
      {required this.program,
      required this.assignment,
      required this.onOpenProgram,
      required this.copy});

  final TrainingProgram? program;
  final Assignment? assignment;
  final VoidCallback onOpenProgram;
  final MyosCopy copy;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final TrainingProgram? active = program;
    final Assignment? currentAssignment = assignment;
    final bool showPreparingProgram =
        currentAssignment?.coachPreparingProgram == true;
    final List<Widget> programContent = active == null
        ? <Widget>[
            Text(copy.noActiveProgram,
                style: MyosTypography.of(context).sectionHeading
                    .copyWith(color: c.textPrimary)),
            const SizedBox(height: MyosSpacing.xs),
            Text(
              copy.generateProgramForNextSession,
              style: MyosTypography.of(context).bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
            const SizedBox(height: MyosSpacing.md),
            MyosButton(
              label: copy.goToProgram,
              icon: Icons.auto_awesome,
              variant: MyosButtonVariant.secondary,
              expand: false,
              onPressed: onOpenProgram,
            ),
          ]
        : <Widget>[
            Text(
              active.programName,
              style: MyosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MyosSpacing.xs),
            Text(
              '${active.splitType} · ${displayCopyOf(context).programFrequency(active.weeklyFrequency)}',
              style: MyosTypography.of(context).bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
          ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (showPreparingProgram) ...<Widget>[
          PreparingProgramBanner(
            assignment: currentAssignment!,
          ),
          const SizedBox(height: MyosSpacing.md),
        ],
        ...programContent,
      ],
    );
  }
}

class _NextSessionSection extends StatelessWidget {
  const _NextSessionSection({
    required this.day,
    required this.label,
    required this.onOpenExercise,
    required this.onLogWorkout,
    required this.logEnabled,
  });

  final ProgramDay day;
  final String label;
  final void Function(ProgramExercise exercise, int dayOrder) onOpenExercise;
  final VoidCallback onLogWorkout;
  final bool logEnabled;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final ProgramDay current = day;
    return MyosCard(
      padding: const EdgeInsets.all(MyosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // The single "Next session" label (with the expected weekday when a
          // schedule exists) lives here as the card eyebrow; there is no
          // duplicate section heading.
          Text(
            label,
            style: MyosTypography.of(context).caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MyosSpacing.xxs),
          Text(
            current.dayName,
            style: MyosTypography.of(context).exerciseTitle.copyWith(
              fontSize: 18,
              color: c.textPrimary,
            ),
          ),
          const SizedBox(height: MyosSpacing.sm),
          for (final ProgramExercise exercise in current.exercises)
            _NextSessionExercise(
              exercise: exercise,
              onTap: () => onOpenExercise(exercise, current.dayOrder),
            ),
          if (current.hasCardio) ...<Widget>[
            const SizedBox(height: MyosSpacing.xs),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Icon(Icons.directions_run, size: 16, color: c.textMuted),
                const SizedBox(width: MyosSpacing.xs),
                Expanded(
                  child: Text(
                    current.cardio!,
                    style: MyosTypography.of(context).bodySecondary
                        .copyWith(color: c.textSecondary),
                  ),
                ),
              ],
            ),
          ],
          if (logEnabled) ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            MyosButton(
              label: displayCopyOf(context).logWorkout,
              icon: Icons.edit_note,
              // Runs the Resume/Discard guard and creates the Active workout
              // before routing to the logger (#123).
              onPressed: onLogWorkout,
            ),
          ],
        ],
      ),
    );
  }
}

class _NextSessionExercise extends StatelessWidget {
  const _NextSessionExercise({required this.exercise, required this.onTap});

  final ProgramExercise exercise;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: MyosRadii.smallRadius,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: MyosSpacing.xs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              exercise.exerciseName,
              style:
                  MyosTypography.of(context).exerciseTitle.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: 2),
            Directionality(
              textDirection: TextDirection.ltr,
              child: Text(
                exercise.prescriptionFor(
                  amrapLabel: displayCopyOf(context).amrapLabel,
                ),
                style: MyosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary),
              ),
            ),
            Text(
              displayCopyOf(context).restTime(exercise.restSecondsOrDefault),
              style: MyosTypography.of(context).caption.copyWith(color: c.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}

class _VolumeSection extends StatelessWidget {
  const _VolumeSection({required this.volume});

  final Map<String, double> volume;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final List<MapEntry<String, double>> muscles = volume.entries
        .where((MapEntry<String, double> entry) => entry.value > 0)
        .toList(growable: false)
      ..sort((MapEntry<String, double> a, MapEntry<String, double> b) =>
          b.value.compareTo(a.value));
    final double total =
        volume.values.fold<double>(0, (double a, double b) => a + b);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MyosSectionHeader(title: displayCopyOf(context).thisWeek),
        if (muscles.isEmpty)
          Text(
            displayCopyOf(context).noSetsLastWeek,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          )
        else ...<Widget>[
          Text(
            displayCopyOf(context).countedSetsMetric(total),
            style: MyosTypography.of(context).numericSmall.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MyosSpacing.xxs),
          Text(
            displayCopyOf(context).countedSetsExplanation,
            style: MyosTypography.of(context).caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MyosSpacing.md),
          for (final MapEntry<String, double> entry in muscles)
            _VolumeRow(
              muscle: entry.key,
              value: entry.value,
              fraction: entry.value / muscles.first.value,
            ),
        ],
      ],
    );
  }
}

class _VolumeRow extends StatelessWidget {
  const _VolumeRow({
    required this.muscle,
    required this.value,
    required this.fraction,
  });

  final String muscle;
  final double value;
  final double fraction;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  muscle,
                  style: MyosTypography.of(context).bodySecondary
                      .copyWith(color: c.textPrimary),
                ),
              ),
              Directionality(
                textDirection: TextDirection.ltr,
                child: Text(
                  _formatValue(value),
                  style: MyosTypography.of(context).numericSmall
                      .copyWith(color: c.textSecondary),
                ),
              ),
            ],
          ),
          const SizedBox(height: MyosSpacing.xs),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: SizedBox(
              height: 6,
              child: FractionallySizedBox(
                alignment: AlignmentDirectional.centerStart,
                widthFactor: fraction.clamp(0.0, 1.0),
                child: DecoratedBox(
                  decoration: BoxDecoration(color: c.accent),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RecordsSection extends StatelessWidget {
  const _RecordsSection({required this.records});

  final List<PersonalRecord> records;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MyosSectionHeader(title: displayCopyOf(context).personalRecords),
        if (records.isEmpty)
          Text(
            displayCopyOf(context).noPersonalRecords,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          )
        else
          for (final PersonalRecord record in records)
            Padding(
              padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          record.name,
                          style: MyosTypography.of(context).body
                              .copyWith(color: c.textPrimary),
                        ),
                        Text(
                          displayCopyOf(context)
                              .personalRecordType(record.recordType),
                          style: MyosTypography.of(context).caption
                              .copyWith(color: c.textMuted),
                        ),
                      ],
                    ),
                  ),
                  Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      PrRecordKind.fromRecordType(record.recordType) ==
                              PrRecordKind.mostReps
                          ? displayCopyOf(context)
                              .personalRecordReps(record.reps)
                          : '${_formatValue(record.value)} kg × ${record.reps}',
                      style: MyosTypography.of(context).numericSmall
                          .copyWith(color: c.textPrimary),
                    ),
                  ),
                ],
              ),
            ),
      ],
    );
  }
}

class _DraftsBanner extends StatelessWidget {
  const _DraftsBanner({required this.count, required this.onTap});

  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Material(
      color: c.accentSubtle,
      borderRadius: MyosRadii.mediumRadius,
      child: InkWell(
        onTap: onTap,
        borderRadius: MyosRadii.mediumRadius,
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: MyosSpacing.md, vertical: MyosSpacing.sm),
          child: Row(
            children: <Widget>[
              Icon(Icons.cloud_upload_outlined, size: 18, color: c.accent),
              const SizedBox(width: MyosSpacing.xs),
              Expanded(
                child: Text(
                  displayCopyOf(context).pendingWorkoutDrafts(count),
                  style: MyosTypography.of(context).bodySecondary
                      .copyWith(color: c.textPrimary),
                ),
              ),
              Icon(Icons.chevron_right, size: 20, color: c.textSecondary),
            ],
          ),
        ),
      ),
    );
  }
}

class _InlineNotice extends StatelessWidget {
  const _InlineNotice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(Icons.info_outline, size: 16, color: c.textSecondary),
        const SizedBox(width: MyosSpacing.xs),
        Expanded(
          child: Text(
            message,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
        ),
      ],
    );
  }
}

class _HomeSkeleton extends StatelessWidget {
  const _HomeSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(
          MyosSpacing.lg, MyosSpacing.md, MyosSpacing.lg, MyosSpacing.xxl),
      children: const <Widget>[
        _SkeletonBlock(widthFactor: 0.7, height: 34),
        SizedBox(height: MyosSpacing.xl),
        _SkeletonBlock(widthFactor: 0.5, height: 24),
        SizedBox(height: MyosSpacing.sm),
        _SkeletonBlock(widthFactor: 0.6, height: 14),
        SizedBox(height: MyosSpacing.xl),
        _SkeletonBlock(widthFactor: 1.0, height: 160),
        SizedBox(height: MyosSpacing.xl),
        _SkeletonBlock(widthFactor: 0.5, height: 18),
        SizedBox(height: MyosSpacing.md),
        _SkeletonBlock(widthFactor: 1.0, height: 10),
        SizedBox(height: MyosSpacing.sm),
        _SkeletonBlock(widthFactor: 1.0, height: 10),
        SizedBox(height: MyosSpacing.sm),
        _SkeletonBlock(widthFactor: 1.0, height: 10),
      ],
    );
  }
}

class _SkeletonBlock extends StatelessWidget {
  const _SkeletonBlock({required this.widthFactor, required this.height});

  final double widthFactor;
  final double height;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: FractionallySizedBox(
        widthFactor: widthFactor,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: c.surfaceSunken,
            borderRadius: BorderRadius.circular(6),
          ),
          child: SizedBox(height: height),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(MyosSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              message,
              textAlign: TextAlign.center,
              style: MyosTypography.of(context).body.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MyosSpacing.md),
            MyosButton(
              label: displayCopyOf(context).retry,
              variant: MyosButtonVariant.secondary,
              expand: false,
              onPressed: onRetry,
            ),
          ],
        ),
      ),
    );
  }
}

String _formatValue(double value) {
  if (value == value.roundToDouble()) {
    return value.round().toString();
  }
  return value.toStringAsFixed(1);
}
