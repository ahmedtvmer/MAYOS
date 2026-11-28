import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_program.dart';
import '../../../core/refetch_on_reconnect.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/api_client.dart';
import '../../../core/analytics_client.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/food_log_models.dart';
import '../../../core/personal_records.dart';
import '../../../core/display_language/workout_copy.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../program/preparing_program_banner.dart';
import '../auth/auth_controller.dart';
import '../workout/workout_share_card.dart';
import '../workout/active_workout_prompt.dart';
import 'home_planning.dart';
import '../../shared/install_prompt.dart';
import '../../settings/push_settings_card.dart';
import '../exercise/exercise_detail_screen.dart';
import '../tour/tour_targets.dart';
import '../xp/xp_widgets.dart';

/// The player Home tab: current program, the next ordered session, real
/// seven-day volume and recent personal records, with honest empty states.
///
/// No readiness, chart, body metric, recommendation, or invented name appears
/// here; every figure is a real value from the service.
class DashboardTab extends ConsumerStatefulWidget {
  const DashboardTab({super.key});

  /// Key on Home's scrolling list, for tests that scroll to lower tiles.
  static const Key listKey = ValueKey<String>('home.list');

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
    this.foodDay,
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

  /// Today's Food log with its totals and targets, for the Home Nutrition
  /// tile (#790); null when it could not be read.
  final FoodLogDay? foodDay;

  /// Set when a non-fatal section failed to load so the body can say so instead
  /// of silently showing an empty section.
  final FailureMessage? partialError;
}

class _DashboardTabState extends ConsumerState<DashboardTab>
    with RefetchOnReconnect<DashboardTab> {
  @override
  Future<void> refreshAfterReconnect() => _refresh();

  late Future<_DashboardData> _future;
  Assignment? _assignmentOverride;
  bool _assignmentOverrideKnown = false;
  int _loadGeneration = 0;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<_DashboardData> _load() async {
    final int generation = ++_loadGeneration;
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
    late ActiveProgram active;
    try {
      active = await loadActiveProgram(
        api: api,
        cache: cache,
        accountId: accountId,
      );
    } on ApiException {
      if (!_isCurrentLoad(generation, accountId)) {
        return const _DashboardData(
          program: null,
          schedule: null,
          volume: <String, double>{},
          records: <PersonalRecord>[],
        );
      }
      rethrow;
    }
    final TrainingProgram? program = active.program;
    // Check the load is still current (and the screen mounted) before reading
    // providers after the await (#894).
    if (accountId != null && _isCurrentLoad(generation, accountId)) {
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
      if (_isCurrentLoad(generation, accountId)) {
        ref.read(pendingCheckpointReviewProvider.notifier).state =
            unopenedCheckpointReview?.checkpoint;
      }
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    FoodLogDay? foodDay;
    try {
      foodDay = await api.foodLogDay();
    } on Object {
      // The Nutrition tile is optional; Home stays usable without it.
    }
    try {
      latestSession = await api.latestSession();
      if (latestSession != null &&
          accountId != null &&
          _isCurrentLoad(generation, accountId)) {
        // Cache the real ledger value so the next day still resolves offline.
        unawaited(cache.writeLatestSession(accountId, latestSession));
      }
    } on ApiException {
      // Offline: fall back to the last-known committed session.
      latestSession =
          accountId == null ? null : await cache.readLatestSession(accountId);
    }
    if (program != null && _isCurrentLoad(generation, accountId) &&
        !ref.read(authControllerProvider).isShowingSavedData) {
      final ProgramDay? nextDay = selectNextDay(program, <TrainedDay>[
        if (latestSession != null) TrainedDay.fromLatestSession(latestSession),
        for (final WorkoutDraft draft in ref.read(draftSyncServiceProvider).drafts)
          TrainedDay.fromDraft(draft),
      ]);
      if (nextDay != null) unawaited(_prefetchPrescription(api, nextDay));
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
      foodDay: foodDay,
    );
  }

  bool _isCurrentLoad(int generation, String? accountId) =>
      mounted &&
      generation == _loadGeneration &&
      ref.read(authControllerProvider).session?.account.accountId == accountId;

  Future<void> _prefetchPrescription(ApiClient api, ProgramDay day) async {
    try {
      await api.prescription(
        day.dayOrder,
        weekOrder: day.weekOrder,
        retryTransportFailures: false,
      );
    } on ApiException {
      // Home stays usable if today's targets cannot be saved yet.
    }
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
    unawaited(openExerciseDetail(
      context,
      exercise.exerciseId,
      ExerciseDetailOptions(dayOrder: dayOrder),
    ));
  }

  void _openDrafts() => context.push(workoutsPath);

  Future<void> _shareLatest(LatestSession session) =>
      WorkoutShareFlowGuard.run(() async {
    final String language = ref.read(displayLanguageProvider);
    final WorkoutCardShare shareCard = ref.read(workoutCardShareProvider);
    final AnalyticsClient analytics = ref.read(analyticsClientProvider);
    final WorkoutImagePicker picker = ref.read(workoutImagePickerProvider);
    final BuildContext shareContext = Navigator.of(context, rootNavigator: true).context;
    final OverlayState shareOverlay = Navigator.of(context, rootNavigator: true).overlay!;
    final WorkoutShareFlowFeedback feedback = WorkoutShareFlowFeedback(
      overlay: shareOverlay, analytics: analytics, source: 'home',
      languageCode: language);
    final WorkoutPhotoChoiceResult choice = await chooseWorkoutPhoto(
      shareContext,
      languageCode: language,
      pickImage: picker,
      onFailure: (String stage, Object error) => feedback.failed(stage, error),
    );
    if (choice.cancelled) return;
    await shareWorkoutCardAndTrack(
      share: () => shareCard(shareContext, latestSessionShareCard(
        session: session,
        languageCode: language,
        photoFile: choice.photoFile,
        feedback: feedback,
        captureOverlay: shareOverlay,
      )),
      analytics: analytics,
      source: 'home',
      photo: choice,
    );
  });

  void _openProgram() =>
      ref.read(playerShellTabProvider.notifier).state =
          PlayerShellTab.program.index;

  void _openNutrition() =>
      ref.read(playerShellTabProvider.notifier).state =
          PlayerShellTab.nutrition.index;

  void _openProgress() =>
      ref.read(playerShellTabProvider.notifier).state =
          PlayerShellTab.progress.index;

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
    ref.listen<AuthState>(
      authControllerProvider,
      (AuthState? previous, AuthState next) {
        final String? previousId = previous?.session?.account.accountId;
        final String? nextId = next.session?.account.accountId;
        if (previousId == nextId) return;
        ++_loadGeneration;
        if (mounted) {
          final Future<_DashboardData> future = nextId == null
              ? Future<_DashboardData>.value(const _DashboardData(
                  program: null,
                  schedule: null,
                  volume: <String, double>{},
                  records: <PersonalRecord>[],
                ))
              : _load();
          setState(() {
            _assignmentOverrideKnown = false;
            _future = future;
          });
        }
      },
    );
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
      // A new account starts from an empty snapshot, never the previous
      // account's data.
      key: ValueKey<String?>(accountId),
      future: _future,
      builder: (BuildContext context, AsyncSnapshot<_DashboardData> snapshot) {
        // A refresh keeps the loaded Home on screen; the skeleton is only for
        // the first load (#894).
        if (snapshot.connectionState == ConnectionState.waiting &&
            !snapshot.hasData) {
          return const _HomeSkeleton();
        }
        if (snapshot.hasError) {
          final Object error = snapshot.error!;
          final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
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
        return InstallPromptHost(
          enabled: ref.watch(playerShellTabProvider) == 0,
          child: Stack(
            children: <Widget>[
              _HomeBody(
                copy: MayosCopy(ref.watch(displayLanguageProvider)),
                data: loadedData,
                program: hasSharedProgram
                    ? sharedProgram.program
                    : loadedData.program,
                programFromCache: hasSharedProgram
                    ? sharedProgram.fromCache
                    : loadedData.programFromCache,
                assignment: _assignmentOverrideKnown
                    ? _assignmentOverride
                    : loadedData.assignment,
                onRefresh: _refresh,
                onOpenExercise: _openExercise,
                onOpenDrafts: _openDrafts,
                onOpenProgram: _openProgram,
                onOpenNutrition: _openNutrition,
                onOpenProgress: _openProgress,
                now: ref.watch(clockProvider)(),
                trainingStatus: ref.watch(trainingStatusProvider),
                onLogWorkout: _logWorkout,
                onShareLatest: _shareLatest,
                trainedDays: <TrainedDay>[
                  if (latest != null) TrainedDay.fromLatestSession(latest),
                  for (final WorkoutDraft draft in drafts)
                    TrainedDay.fromDraft(draft),
                ],
                pendingDrafts:
                    drafts.where((WorkoutDraft d) => d.isUnsynced).length,
              ),
            ],
          ),
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
    required this.onOpenProgram,
    required this.onOpenNutrition,
    required this.onOpenProgress,
    required this.onLogWorkout,
    required this.onShareLatest,
    required this.trainedDays,
    required this.pendingDrafts,
    required this.now,
    this.trainingStatus,
  });

  final MayosCopy copy;

  final _DashboardData data;
  final TrainingProgram? program;
  final bool programFromCache;
  final Assignment? assignment;
  final Future<void> Function() onRefresh;
  final void Function(ProgramExercise exercise, int dayOrder) onOpenExercise;
  final VoidCallback onOpenDrafts;
  final VoidCallback onOpenProgram;
  final VoidCallback onOpenNutrition;
  final VoidCallback onOpenProgress;
  final void Function(ProgramDay day, int? programVersion, int programWeekCount)
      onLogWorkout;
  final Future<void> Function(LatestSession session) onShareLatest;
  final List<TrainedDay> trainedDays;
  final int pendingDrafts;
  final DateTime now;

  /// Rank, XP and Weekly streak for the strip above the session (#796);
  /// null until the first status read, and for a status cached before XP.
  final TrainingStatus? trainingStatus;

  /// Home answers "what do I do today" (#790): today's session first, then
  /// short summaries that open their own tabs. A day with a weekly schedule
  /// that does not include today is a rest day.
  @override
  Widget build(BuildContext context) {
    final TrainingProgram? activeProgram = program;
    final ProgramDay? nextDay =
        activeProgram == null ? null : selectNextDay(activeProgram, trainedDays);
    final List<int> weekdays = scheduledWeekdays(data.schedule);
    final bool restDay = weekdays.isNotEmpty && !weekdays.contains(now.weekday);
    final int? nextWeekday = weekdays.isEmpty
        ? null
        : nextScheduledWeekday(weekdays, now.add(const Duration(days: 1)));
    final bool coachPreparing = assignment?.coachPreparingProgram == true;
    final LatestSession? latest = data.latestSession;
    final bool? latestIsToday = _recentSessionDay(latest, now);

    final Widget sessionCard;
    if (activeProgram == null || nextDay == null) {
      sessionCard = coachPreparing
          ? PreparingProgramBanner(assignment: assignment!)
          : _BuildProgramCard(copy: copy, onOpenProgram: onOpenProgram);
    } else if (restDay) {
      sessionCard = _RestDayCard(
        copy: copy,
        today: now.weekday,
        nextDay: nextDay,
        nextWeekday: nextWeekday,
        onPreview: onOpenProgram,
      );
    } else {
      sessionCard = _NextSessionSection(
        day: nextDay,
        label: nextSessionLabel(data.schedule, now,
            isArabic: displayCopyOf(context).isArabic),
        onOpenExercise: onOpenExercise,
        onOpenProgram: onOpenProgram,
        onLogWorkout: () => onLogWorkout(
          nextDay,
          activeProgram.version,
          activeProgram.weekCount,
        ),
        logEnabled: true,
      );
    }

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        key: DashboardTab.listKey,
        padding: const EdgeInsets.fromLTRB(MayosSpacing.lg, MayosSpacing.md,
            MayosSpacing.lg, MayosSpacing.xxl),
        children: <Widget>[
          if (programFromCache) ...<Widget>[
            _InlineNotice(message: displayCopyOf(context).savedProgramNote),
            const SizedBox(height: MayosSpacing.sm),
          ] else if (data.partialError != null) ...<Widget>[
            _InlineNotice(message: copy.failureMessage(data.partialError!)),
            const SizedBox(height: MayosSpacing.sm),
          ],
          // Reminders: shown only while they are available, off and not
          // dismissed (the card decides).
          const PushSettingsCard(compact: true),
          // Rank, XP and Weekly streak, directly above the session (#796).
          if (trainingStatus case final TrainingStatus status
              when status.rank != null) ...<Widget>[
            XpStatusStrip(
              status: status,
              onTap: () => showRankSheet(context, status),
            ),
            const SizedBox(height: MayosSpacing.md),
          ],
          TourTarget(id: 'home', child: sessionCard),
          if (latest != null && latestIsToday != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            _LastSessionRow(
              label: copy.homeLastSession(latest.splitName, today: latestIsToday),
              onShare: () => onShareLatest(latest),
              languageCode: displayCopyOf(context).isArabic ? 'ar' : 'en',
            ),
          ],
          if (pendingDrafts > 0) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            _DraftsBanner(count: pendingDrafts, onTap: onOpenDrafts),
          ],
          if (data.foodDay != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            _NutritionTodayTile(
              copy: copy,
              day: data.foodDay!,
              onTap: onOpenNutrition,
            ),
          ],
          if (activeProgram != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            if (coachPreparing) ...<Widget>[
              PreparingProgramBanner(assignment: assignment!),
              const SizedBox(height: MayosSpacing.sm),
            ],
            _ProgramLine(
              label: copy.homeProgramLine(
                activeProgram.programName,
                activeProgram.currentWeek,
                activeProgram.weekCount,
                activeProgram.weeklyFrequency,
              ),
              onTap: onOpenProgram,
            ),
          ],
          const SizedBox(height: MayosSpacing.md),
          _SummaryTiles(
            copy: copy,
            volume: data.volume,
            records: data.records,
            onTap: onOpenProgress,
          ),
        ],
      ),
    );
  }
}

/// True for a session performed today, false for yesterday, null otherwise:
/// the last-session row shows on the workout's day and the next one only.
bool? _recentSessionDay(LatestSession? session, DateTime now) {
  if (session == null) return null;
  final String today = isoDateOf(now);
  if (session.sessionDate == today) return true;
  if (session.sessionDate == isoDateOf(now.subtract(const Duration(days: 1)))) {
    return false;
  }
  return null;
}

class _BuildProgramCard extends StatelessWidget {
  const _BuildProgramCard({required this.copy, required this.onOpenProgram});

  final MayosCopy copy;
  final VoidCallback onOpenProgram;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(copy.noActiveProgram,
              style: MayosTypography.of(context)
                  .sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            copy.generateProgramForNextSession,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            label: copy.goToProgram,
            icon: Icons.auto_awesome,
            onPressed: onOpenProgram,
          ),
        ],
      ),
    );
  }
}

class _RestDayCard extends StatelessWidget {
  const _RestDayCard({
    required this.copy,
    required this.today,
    required this.nextDay,
    required this.nextWeekday,
    required this.onPreview,
  });

  final MayosCopy copy;
  final int today;
  final ProgramDay nextDay;
  final int? nextWeekday;
  final VoidCallback onPreview;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    return MayosCard(
      key: const ValueKey<String>('home.restDay'),
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.bedtime_outlined, color: c.textSecondary),
              const SizedBox(width: MayosSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(copy.homeTodayLabel(today),
                        style: type.caption.copyWith(color: c.textSecondary)),
                    Text(copy.homeRestDay,
                        style: type.pageHeading.copyWith(color: c.textPrimary)),
                  ],
                ),
              ),
            ],
          ),
          Divider(height: MayosSpacing.lg, color: c.border),
          Row(
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(copy.nextSessionLabel(null),
                        style: type.caption.copyWith(color: c.textSecondary)),
                    Text(
                      copy.homeNextDayOn(nextDay.dayName, nextWeekday),
                      style: type.exerciseTitle.copyWith(color: c.textPrimary),
                    ),
                  ],
                ),
              ),
              MayosButton(
                label: copy.homePreview,
                variant: MayosButtonVariant.secondary,
                expand: false,
                onPressed: onPreview,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LastSessionRow extends StatelessWidget {
  const _LastSessionRow({
    required this.label,
    required this.onShare,
    required this.languageCode,
  });

  final String label;
  final VoidCallback onShare;
  final String languageCode;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Row(
      children: <Widget>[
        Expanded(
          child: Text(
            label,
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: c.textSecondary),
          ),
        ),
        const SizedBox(width: MayosSpacing.sm),
        MayosButton(
          key: const ValueKey<String>('home.shareLatestWorkout'),
          label: WorkoutCopy(languageCode).shareToStory,
          icon: Icons.ios_share,
          variant: MayosButtonVariant.secondary,
          expand: false,
          onPressed: onShare,
        ),
      ],
    );
  }
}

class _NutritionTodayTile extends StatelessWidget {
  const _NutritionTodayTile({
    required this.copy,
    required this.day,
    required this.onTap,
  });

  final MayosCopy copy;
  final FoodLogDay day;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final num? kcalTarget = day.targets?['calories'] as num?;
    final num? proteinTarget = day.targets?['protein_g'] as num?;
    final double fraction = kcalTarget == null || kcalTarget <= 0
        ? 0
        : (day.totals.kcal / kcalTarget).clamp(0.0, 1.0);
    return _HomeTile(
      key: const ValueKey<String>('home.nutritionToday'),
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(copy.homeNutritionToday,
                    style: type.captionStrong.copyWith(color: c.textSecondary)),
              ),
              Icon(Icons.chevron_right, size: 20, color: c.textSecondary),
            ],
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(copy.homeCalories(day.totals.kcal, kcalTarget),
              style: type.numericSmall.copyWith(color: c.textPrimary)),
          if (kcalTarget != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: fraction,
                minHeight: 6,
                color: c.accent,
                backgroundColor: c.surfaceSunken,
              ),
            ),
            const SizedBox(height: MayosSpacing.xs),
            Text(copy.homeProtein(day.totals.protein, proteinTarget),
                style: type.bodySecondary.copyWith(color: c.textSecondary)),
          ] else ...<Widget>[
            const SizedBox(height: MayosSpacing.xxs),
            Text(copy.homeSetNutritionTargets,
                style: type.bodySecondary.copyWith(color: c.textSecondary)),
          ],
        ],
      ),
    );
  }
}

class _ProgramLine extends StatelessWidget {
  const _ProgramLine({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return _HomeTile(
      key: const ValueKey<String>('home.programLine'),
      onTap: onTap,
      child: Row(
        children: <Widget>[
          Icon(Icons.article_outlined, size: 18, color: c.textSecondary),
          const SizedBox(width: MayosSpacing.sm),
          Expanded(
            child: Text(
              label,
              style: MayosTypography.of(context)
                  .body
                  .copyWith(color: c.textPrimary),
            ),
          ),
          Icon(Icons.chevron_right, size: 20, color: c.textSecondary),
        ],
      ),
    );
  }
}

class _SummaryTiles extends StatelessWidget {
  const _SummaryTiles({
    required this.copy,
    required this.volume,
    required this.records,
    required this.onTap,
  });

  final MayosCopy copy;
  final Map<String, double> volume;
  final List<PersonalRecord> records;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosTypography type = MayosTypography.of(context);
    final List<MapEntry<String, double>> muscles = volume.entries
        .where((MapEntry<String, double> entry) => entry.value > 0)
        .toList(growable: false)
      ..sort((MapEntry<String, double> a, MapEntry<String, double> b) =>
          b.value.compareTo(a.value));
    final double total =
        volume.values.fold<double>(0, (double a, double b) => a + b);
    final PersonalRecord? record = records.isEmpty ? null : records.first;
    Widget tile(Key key, String title, String value, String? detail) => Expanded(
          child: _HomeTile(
            key: key,
            onTap: onTap,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(title,
                    style: type.captionStrong.copyWith(color: c.textSecondary)),
                const SizedBox(height: MayosSpacing.xxs),
                Directionality(
                  textDirection: TextDirection.ltr,
                  child: Text(value,
                      style: type.numericSmall.copyWith(color: c.textPrimary)),
                ),
                if (detail != null)
                  Text(detail,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: type.caption.copyWith(color: c.textSecondary)),
              ],
            ),
          ),
        );
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          tile(
            const ValueKey<String>('home.weekTile'),
            copy.thisWeek,
            muscles.isEmpty ? copy.homeNoSetsYet : copy.countedSetsMetric(total),
            muscles.isEmpty ? null : copy.homeMostTrained(muscles.first.key),
          ),
          const SizedBox(width: MayosSpacing.sm),
          tile(
            const ValueKey<String>('home.prTile'),
            copy.homeLatestPr,
            record == null
                ? copy.homeNoPrYet
                : PrRecordKind.fromRecordType(record.recordType) ==
                        PrRecordKind.mostReps
                    ? copy.personalRecordReps(record.reps)
                    : '${_formatValue(record.value)} kg × ${record.reps}',
            record?.name,
          ),
        ],
      ),
    );
  }
}

/// One tappable Home summary surface; every tile shares the card treatment.
class _HomeTile extends StatelessWidget {
  const _HomeTile({super.key, required this.onTap, required this.child});

  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.surface,
      shape: RoundedRectangleBorder(
        borderRadius: MayosRadii.mediumRadius,
        side: BorderSide(color: c.border),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: MayosRadii.mediumRadius,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Padding(
            padding: const EdgeInsets.all(MayosSpacing.md),
            child: child,
          ),
        ),
      ),
    );
  }
}

class _NextSessionSection extends StatelessWidget {
  const _NextSessionSection({
    required this.day,
    required this.label,
    required this.onOpenExercise,
    required this.onOpenProgram,
    required this.onLogWorkout,
    required this.logEnabled,
  });

  static const int _shownExercises = 3;

  final ProgramDay day;
  final String label;
  final void Function(ProgramExercise exercise, int dayOrder) onOpenExercise;
  final VoidCallback onOpenProgram;
  final VoidCallback onLogWorkout;
  final bool logEnabled;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ProgramDay current = day;
    return MayosCard(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // The single "Next session" label (with the expected weekday when a
          // schedule exists) lives here as the card eyebrow; there is no
          // duplicate section heading.
          Text(
            label,
            style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            current.dayName,
            style: MayosTypography.of(context).pageHeading.copyWith(
              color: c.textPrimary,
            ),
          ),
          Text(
            displayCopyOf(context).homeExerciseCount(current.exercises.length),
            style: MayosTypography.of(context).bodySecondary
                .copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          for (final ProgramExercise exercise
              in current.exercises.take(_shownExercises))
            _NextSessionExercise(
              exercise: exercise,
              onTap: () => onOpenExercise(exercise, current.dayOrder),
            ),
          if (current.exercises.length > _shownExercises)
            InkWell(
              key: const ValueKey<String>('home.moreExercises'),
              onTap: onOpenProgram,
              borderRadius: MayosRadii.smallRadius,
              child: ConstrainedBox(
                // Android's tap-target guideline is 48 dp (#790 follow-up).
                constraints: const BoxConstraints(minHeight: 48),
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(
                    displayCopyOf(context).homeMoreExercises(
                        current.exercises.length - _shownExercises),
                    style: MayosTypography.of(context).bodySecondary
                        .copyWith(color: c.textSecondary),
                  ),
                ),
              ),
            ),
          if (current.hasCardio) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Icon(Icons.directions_run, size: 16, color: c.textMuted),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: Text(
                    current.cardio!.display(displayCopyOf(context)),
                    style: MayosTypography.of(context).bodySecondary
                        .copyWith(color: c.textSecondary),
                  ),
                ),
              ],
            ),
          ],
          if (logEnabled) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            MayosButton(
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: MayosRadii.smallRadius,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              exercise.exerciseName,
              style:
                  MayosTypography.of(context).exerciseTitle.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: 2),
            Directionality(
              textDirection: TextDirection.ltr,
              child: Text(
                exercise.prescriptionFor(
                  amrapLabel: displayCopyOf(context).amrapLabel,
                ),
                style: MayosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary),
              ),
            ),
            Text(
              displayCopyOf(context).restTime(exercise.restSecondsOrDefault),
              style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}

class _DraftsBanner extends StatelessWidget {
  const _DraftsBanner({required this.count, required this.onTap});

  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.accentSubtle,
      borderRadius: MayosRadii.mediumRadius,
      child: InkWell(
        onTap: onTap,
        borderRadius: MayosRadii.mediumRadius,
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.md, vertical: MayosSpacing.sm),
          child: Row(
            children: <Widget>[
              Icon(Icons.cloud_upload_outlined, size: 18, color: c.accent),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: Text(
                  displayCopyOf(context).pendingWorkoutDrafts(count),
                  style: MayosTypography.of(context).bodySecondary
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(Icons.info_outline, size: 16, color: c.textSecondary),
        const SizedBox(width: MayosSpacing.xs),
        Expanded(
          child: Text(
            message,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
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
          MayosSpacing.lg, MayosSpacing.md, MayosSpacing.lg, MayosSpacing.xxl),
      children: const <Widget>[
        _SkeletonBlock(widthFactor: 0.7, height: 34),
        SizedBox(height: MayosSpacing.xl),
        _SkeletonBlock(widthFactor: 0.5, height: 24),
        SizedBox(height: MayosSpacing.sm),
        _SkeletonBlock(widthFactor: 0.6, height: 14),
        SizedBox(height: MayosSpacing.xl),
        _SkeletonBlock(widthFactor: 1.0, height: 160),
        SizedBox(height: MayosSpacing.xl),
        _SkeletonBlock(widthFactor: 0.5, height: 18),
        SizedBox(height: MayosSpacing.md),
        _SkeletonBlock(widthFactor: 1.0, height: 10),
        SizedBox(height: MayosSpacing.sm),
        _SkeletonBlock(widthFactor: 1.0, height: 10),
        SizedBox(height: MayosSpacing.sm),
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
    final MayosThemeExtension c = MayosTheme.of(context);
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              message,
              textAlign: TextAlign.center,
              style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.md),
            MayosButton(
              label: displayCopyOf(context).retry,
              variant: MayosButtonVariant.secondary,
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
