import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/active_program.dart';
import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../assignment/program_request_dialog.dart';
import '../exercise_picker_dialog.dart';
import '../workout/deload_banner.dart';
import '../workout/active_workout_prompt.dart';
import 'program_authority_recovery.dart';

enum _SwapDirection { apply, undo }

class _ProgramSwap {
  const _ProgramSwap({
    required this.dayName,
    required this.sourceId,
    required this.sourceName,
    required this.replacement,
    required this.allOccurrences,
    this.authorityNotice,
  });

  final String dayName;
  final String sourceId;
  final String sourceName;
  final ExerciseCatalogEntry replacement;
  final bool allOccurrences;
  final String? authorityNotice;
}

class _SubstitutionRecovery {
  const _SubstitutionRecovery({
    required this.selectedDay,
    required this.selectedExercise,
    required this.replacement,
    required this.previousPlayerControlsProgram,
  });

  final ProgramDay selectedDay;
  final ProgramExercise selectedExercise;
  final ExerciseCatalogEntry replacement;
  final bool previousPlayerControlsProgram;
}

class ProgramTab extends ConsumerStatefulWidget {
  const ProgramTab({super.key});

  @override
  ConsumerState<ProgramTab> createState() => _ProgramTabState();
}

class _ProgramTabState extends ConsumerState<ProgramTab> {
  bool _loading = true;
  bool _generating = false;
  bool _substituting = false;
  bool _pickerBusy = false;
  String? _loadError;
  String? _actionError;
  TrainingProgram? _program;
  Map<int, DeloadDecision> _deloadByDay = <int, DeloadDecision>{};

  /// The player's active assignment, or null when none (used for coach
  /// provenance). [_assignmentKnown] is false when the assignment lookup failed
  /// (e.g. offline), so the label never wrongly claims a coach is "former".
  Assignment? _assignment;
  bool _assignmentKnown = false;

  /// True only when [_program] is being served from the offline cache after
  /// an online fetch failed (ADR 020/033) — never merely because a cache
  /// exists alongside a successful fetch.
  bool _fromCache = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String? get _accountId =>
      ref.read(authControllerProvider).session?.account.accountId;

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    final String? accountId = _accountId;
    final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
    try {
      final ActiveProgram result = await loadActiveProgram(
        api: ref.read(apiClientProvider),
        cache: cache,
        accountId: accountId,
      );
      if (!mounted) return;
      _updateProgram(
        result.program,
        accountId,
        fromCache: result.fromCache,
        loading: false,
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loadError = error.message;
        _loading = false;
      });
    }
    // Coach provenance: an active assignment means the publishing coach is
    // still the player's coach; without one, the coach is former (#40/#53).
    try {
      final Assignment? assignment =
          await ref.read(apiClientProvider).myAssignment();
      if (!mounted) return;
      setState(() {
        _assignment = assignment;
        _assignmentKnown = true;
      });
    } on ApiException {
      // Leave the label as "Published by your coach" rather than guessing.
    }
  }

  void _updateProgram(
    TrainingProgram? program,
    String? accountId, {
    required bool fromCache,
    bool? loading,
    bool? generating,
  }) {
    setState(() {
      _program = program;
      _deloadByDay = <int, DeloadDecision>{};
      _fromCache = fromCache;
      if (loading != null) _loading = loading;
      if (generating != null) _generating = generating;
    });
    if (program != null) {
      unawaited(_loadProgramDeload(program, accountId));
    }
  }

  Future<void> _loadProgramDeload(
    TrainingProgram program,
    String? accountId,
  ) async {
    if (accountId == null || program.days.isEmpty) return;
    final ApiClient api = ref.read(apiClientProvider);
    final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
    Prescription? prescription = await loadDayPrescription(
      api: api,
      cache: cache,
      accountId: accountId,
      dayOrder: program.days.first.dayOrder,
    );
    for (final ProgramDay day in program.days.skip(1)) {
      if (prescription != null) break;
      try {
        prescription = await cache.readPrescription(accountId, day.dayOrder);
      } on Object {
        // One unreadable day cache does not prevent trying the others.
      }
    }
    if (!mounted || _program?.version != program.version) return;
    if (prescription == null) return;
    final DeloadDecision decision = prescription.deload;
    setState(() {
      _deloadByDay = <int, DeloadDecision>{
        for (final ProgramDay day in program.days) day.dayOrder: decision,
      };
    });
  }

  List<Widget> _deloadBannerFor(ProgramDay day) {
    final DeloadDecision? deload = _deloadByDay[day.dayOrder];
    if (deload == null) return const <Widget>[];
    return <Widget>[
      DeloadBanner(
        key: ValueKey<String>('program.deload.${day.dayOrder}'),
        decision: deload,
        onOpenAssistant: () => context.push(chatPath),
      ),
      const SizedBox(height: MayosSpacing.md),
    ];
  }

  Future<void> _generate() async {
    setState(() {
      _generating = true;
      _actionError = null;
    });
    try {
      final TrainingProgram program =
          await ref.read(apiClientProvider).playerGenerateProgram();
      final String? accountId = _accountId;
      if (accountId != null) {
        unawaited(cacheActiveProgram(
            ref.read(workoutCacheStoreProvider), accountId, program));
      }
      if (!mounted) return;
      _updateProgram(
        program,
        accountId,
        fromCache: false,
        generating: false,
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _generating = false;
        _actionError = mutationFailureMessage(error);
      });
    }
  }

  Future<void> _onSubstituteExercise(
    ProgramDay day,
    ProgramExercise exercise,
  ) async {
    if (_substituting || _pickerBusy) return;
    setState(() => _pickerBusy = true);
    ExerciseCatalogEntry? replacement;
    try {
      replacement = await _pickProgramReplacement(day, exercise);
      if (replacement == null || !mounted) return;
      if (_program?.playerControlsProgram == true) {
        await _substitutePlayerProgram(day, exercise, replacement);
      } else {
        await _requestSubstitution(day, exercise, replacement);
      }
    } on ApiException catch (error) {
      if (ProgramAuthorityRecovery.isRefusal(error) && replacement != null) {
        await _refreshAndRouteSubstitution(day, exercise, replacement, error);
      } else if (mounted) {
        _showSwapError(error);
      }
    } finally {
      if (mounted) setState(() => _pickerBusy = false);
    }
  }

  Future<void> _substitutePlayerProgram(
    ProgramDay day,
    ProgramExercise exercise,
    ExerciseCatalogEntry replacement, {
    String? authorityNotice,
  }) async {
    final int otherDays = _otherDaysWith(day, exercise.exerciseId);
    final bool? allOccurrences =
        otherDays == 0 ? false : await _chooseSubstitutionScope(otherDays);
    if (allOccurrences == null || !mounted) return;
    await _performProgramSwap(
      _ProgramSwap(
        dayName: day.dayName,
        sourceId: exercise.exerciseId,
        sourceName: exercise.exerciseName,
        replacement: replacement,
        allOccurrences: allOccurrences,
        authorityNotice: authorityNotice,
      ),
      _SwapDirection.apply,
    );
  }

  Future<void> _refreshAndRouteSubstitution(
    ProgramDay selectedDay,
    ProgramExercise selectedExercise,
    ExerciseCatalogEntry replacement,
    ApiException error,
  ) async {
    final _SubstitutionRecovery recovery = _SubstitutionRecovery(
      selectedDay: selectedDay,
      selectedExercise: selectedExercise,
      replacement: replacement,
      previousPlayerControlsProgram: _program?.playerControlsProgram ?? false,
    );
    if (mounted) setState(() => _substituting = false);
    try {
      final ProgramAuthorityRefresh result = await ProgramAuthorityRecovery(
        api: ref.read(apiClientProvider),
        cache: ref.read(workoutCacheStoreProvider),
        accountId: _accountId,
      ).refreshAfterRefusal(error);
      final TrainingProgram? refreshedProgram = result.program;
      if (mounted) {
        setState(() {
          _program = refreshedProgram;
          _fromCache = false;
        });
      }
      if (!mounted) return;
      final ProgramAuthorityRoute route =
          ProgramAuthorityRecovery.routeAfterRefusal(
        result,
        previousPlayerControlsProgram: recovery.previousPlayerControlsProgram,
      );
      await _continueAfterAuthorityRefresh(refreshedProgram, recovery, route);
    } on ApiException catch (refreshError) {
      if (mounted) _showSwapError(refreshError);
    }
  }

  Future<void> _continueAfterAuthorityRefresh(
    TrainingProgram? program,
    _SubstitutionRecovery recovery,
    ProgramAuthorityRoute route,
  ) async {
    if (program == null || route == ProgramAuthorityRoute.unavailable) {
      _showAuthorityMessage(
          'Your program changed. Refresh before substituting.');
      return;
    }
    if (route == ProgramAuthorityRoute.inconsistent ||
        route == ProgramAuthorityRoute.unchanged) {
      _showAuthorityMessage('Program authority changed again. Try once more.');
      return;
    }
    await _continueWithRefreshedProgram(program, recovery);
  }

  Future<void> _continueWithRefreshedProgram(
    TrainingProgram program,
    _SubstitutionRecovery recovery,
  ) async {
    final (ProgramDay, ProgramExercise)? target =
        _findRefreshedSubstitutionTarget(program, recovery);
    if (target == null) {
      _showAuthorityMessage(
          'The program changed. Choose the exercise and replacement again.');
      return;
    }
    await _routeSubstitutionForRefreshedProgram(
      program,
      target.$1,
      target.$2,
      recovery.replacement,
    );
  }

  (ProgramDay, ProgramExercise)? _findRefreshedSubstitutionTarget(
    TrainingProgram program,
    _SubstitutionRecovery recovery,
  ) {
    final ProgramDay? day = _findDay(program, recovery.selectedDay.dayName);
    final ProgramExercise? exercise = day == null
        ? null
        : _findExercise(day, recovery.selectedExercise.exerciseId);
    if (day == null ||
        exercise == null ||
        day.exercises.any((ProgramExercise item) =>
            item.exerciseId == recovery.replacement.id)) {
      return null;
    }
    return (day, exercise);
  }

  Future<void> _routeSubstitutionForRefreshedProgram(
    TrainingProgram program,
    ProgramDay day,
    ProgramExercise exercise,
    ExerciseCatalogEntry replacement,
  ) async {
    if (program.playerControlsProgram) {
      await _substitutePlayerProgram(
        day,
        exercise,
        replacement,
        authorityNotice:
            'Program authority changed. Continuing with direct substitution.',
      );
      return;
    }
    _showAuthorityMessage(
        'Program authority changed. Opening a request for your coach.');
    await _requestSubstitution(day, exercise, replacement);
  }

  ProgramDay? _findDay(TrainingProgram program, String dayName) {
    for (final ProgramDay day in program.days) {
      if (day.dayName == dayName) return day;
    }
    return null;
  }

  ProgramExercise? _findExercise(ProgramDay day, String exerciseId) {
    for (final ProgramExercise exercise in day.exercises) {
      if (exercise.exerciseId == exerciseId) return exercise;
    }
    return null;
  }

  void _showAuthorityMessage(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _requestSubstitution(
    ProgramDay day,
    ProgramExercise exercise,
    ExerciseCatalogEntry replacement,
  ) async {
    final ProgramRequestDraft? draft = await showDialog<ProgramRequestDraft>(
      context: context,
      builder: (BuildContext context) => ProgramRequestDialog.forSubstitution(
        substitution: ProgramSubstitutionRequestPrefill(
          dayName: day.dayName,
          exerciseId: exercise.exerciseId,
          exerciseName: exercise.exerciseName,
          replacementExerciseId: replacement.id,
          replacementName: replacement.name,
        ),
      ),
    );
    if (draft == null || !mounted) return;
    await _submitSubstitutionRequest(draft, exercise, replacement);
  }

  Future<void> _submitSubstitutionRequest(
    ProgramRequestDraft draft,
    ProgramExercise exercise,
    ExerciseCatalogEntry replacement,
  ) async {
    setState(() {
      _substituting = true;
      _actionError = null;
    });
    try {
      await ref.read(apiClientProvider).createPlayerProgramRequest(
            kind: draft.kind,
            dayName: draft.dayName,
            exerciseId: draft.exerciseId,
            replacementExerciseId: draft.replacementExerciseId,
            desiredWeeklyFrequency: draft.desiredWeeklyFrequency,
            desiredSplitPreference: draft.desiredSplitPreference,
            reason: draft.reason,
          );
    } on ApiException {
      if (mounted) setState(() => _substituting = false);
      rethrow;
    }
    if (!mounted) return;
    setState(() => _substituting = false);
    _showSubstitutionRequestSent(exercise, replacement);
  }

  void _showSubstitutionRequestSent(
    ProgramExercise exercise,
    ExerciseCatalogEntry replacement,
  ) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(
            'Your coach has been asked to replace ${exercise.exerciseName} '
            'with ${replacement.name}.',
          ),
        ),
      );
  }

  Future<ExerciseCatalogEntry?> _pickProgramReplacement(
    ProgramDay day,
    ProgramExercise exercise,
  ) async {
    final String? targetMuscle = await exerciseTargetMuscle(
      ref.read(apiClientProvider),
      exercise.exerciseId,
    );
    if (!mounted) return null;
    return showDialog<ExerciseCatalogEntry>(
      context: context,
      builder: (BuildContext context) => ExercisePickerDialog(
        title: 'Substitute exercise',
        targetMuscle: targetMuscle,
        excludeExerciseIds: <String>{
          for (final ProgramExercise item in day.exercises) item.exerciseId,
        },
        emptyFilteredMessage: 'Every match is already in this day.',
      ),
    );
  }

  int _otherDaysWith(ProgramDay selectedDay, String exerciseId) {
    return (_program?.days ?? const <ProgramDay>[]).where((ProgramDay day) {
      return day.dayName != selectedDay.dayName &&
          day.exercises.any(
              (ProgramExercise exercise) => exercise.exerciseId == exerciseId);
    }).length;
  }

  Future<bool?> _chooseSubstitutionScope(int otherDayCount) {
    bool allOccurrences = false;
    return showDialog<bool>(
      context: context,
      builder: (BuildContext context) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: const Text('Substitute exercise?'),
          content: SizedBox(
            width: kExercisePickerDialogWidth,
            child: CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: allOccurrences,
              title: Text('Also replace on $otherDayCount other days'),
              onChanged: (bool? value) => setDialogState(
                () => allOccurrences = value ?? false,
              ),
            ),
          ),
          actions: <Widget>[
            MayosButton(
              label: 'Cancel',
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: () => Navigator.of(context).pop(),
            ),
            MayosButton(
              label: 'Substitute',
              expand: false,
              onPressed: () => Navigator.of(context).pop(allOccurrences),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _performProgramSwap(_ProgramSwap swap, _SwapDirection direction,
      {int? restoreVersion, int? expectedActiveVersion}) async {
    if (!mounted) return;
    setState(() {
      _substituting = true;
      _actionError = null;
    });
    try {
      final ProgramSubstitutionResult swapResult = await _requestProgramSwap(
        swap,
        direction,
        restoreVersion: restoreVersion,
        expectedActiveVersion: expectedActiveVersion,
      );
      if (!mounted) return;
      setState(() {
        _program = swapResult.program;
        _fromCache = false;
        _substituting = false;
      });
      _showSwapResult(swap, direction, swapResult);
    } on ApiException catch (error) {
      if (direction == _SwapDirection.apply &&
          error.errorCode == 'coach_controlled') {
        if (mounted) setState(() => _substituting = false);
        rethrow;
      }
      if (mounted) _showSwapError(error);
    }
  }

  Future<ProgramSubstitutionResult> _requestProgramSwap(
      _ProgramSwap swap, _SwapDirection direction,
      {int? restoreVersion, int? expectedActiveVersion}) async {
    final bool undo = direction == _SwapDirection.undo;
    final ApiClient api = ref.read(apiClientProvider);
    final ProgramSubstitutionResult mutation;
    if (undo) {
      mutation = await api.undoProgramSubstitution(
        restoreVersion: restoreVersion!,
        expectedActiveVersion: expectedActiveVersion!,
      );
    } else {
      mutation = await api.substituteProgramExercise(
        dayName: swap.dayName,
        exerciseId: swap.sourceId,
        replacementExerciseId: swap.replacement.id,
        allOccurrences: swap.allOccurrences,
        expectedActiveVersion: _program?.version,
      );
    }
    final String? accountId = _accountId;
    if (accountId != null) {
      unawaited(cacheActiveProgram(
        ref.read(workoutCacheStoreProvider),
        accountId,
        mutation.program,
      ));
    }
    return mutation;
  }

  void _showSwapResult(
    _ProgramSwap swap,
    _SwapDirection direction,
    ProgramSubstitutionResult swapResult,
  ) {
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar();
    if (direction == _SwapDirection.undo) {
      messenger.showSnackBar(
        const SnackBar(content: Text('Substitution undone.')),
      );
      return;
    }
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          <String>[
            if (swap.authorityNotice != null) swap.authorityNotice!,
            '${swap.sourceName} replaced with ${swap.replacement.name}.',
          ].join(' '),
        ),
        duration: const Duration(seconds: 10),
        action: SnackBarAction(
          label: 'Undo',
          onPressed: () => unawaited(
            _performProgramSwap(
              swap,
              _SwapDirection.undo,
              restoreVersion: swapResult.previousVersion,
              expectedActiveVersion: swapResult.version,
            ),
          ),
        ),
      ),
    );
  }

  void _showSwapError(ApiException error) {
    final String message = mutationFailureMessage(error);
    setState(() {
      _substituting = false;
      _actionError = message;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  void _openExercise(ProgramDay day, ProgramExercise exercise) {
    context
        .push('$exerciseDetailPath/${exercise.exerciseId}?day=${day.dayOrder}');
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return _CenteredMessage(
        message: _loadError!,
        actionLabel: 'Retry',
        onAction: _load,
      );
    }
    final TrainingProgram? program = _program;
    if (program == null) {
      return _CenteredMessage(
        message: 'No active program yet. Complete onboarding to build one.',
        error: _actionError,
        actionLabel: 'Regenerate program',
        onAction: _generating ? null : _generate,
        loading: _generating,
      );
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(MayosSpacing.lg, MayosSpacing.md,
            MayosSpacing.lg, MayosSpacing.xxl),
        children: <Widget>[
          if (_fromCache) ...<Widget>[
            const _OfflineBanner(),
            const SizedBox(height: MayosSpacing.md),
          ],
          Text(
            program.programName,
            style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            '${program.splitType} · ${program.weeklyFrequency} '
            '${program.weeklyFrequency == 1 ? 'day' : 'days'}/week',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          if (program.isCoachPublished) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            _ProvenanceLabel(
              former: _assignmentKnown && _assignment == null,
            ),
          ],
          if (_actionError != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              _actionError!,
              style: MayosTypography.bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.md),
          Align(
            alignment: Alignment.centerLeft,
            child: MayosButton(
              label: 'Regenerate program',
              icon: Icons.auto_awesome,
              variant: MayosButtonVariant.tertiary,
              loading: _generating,
              expand: false,
              onPressed: _generating ? null : _generate,
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          for (final ProgramDay day in program.days)
            Padding(
              padding: const EdgeInsets.only(bottom: MayosSpacing.md),
              child: MayosCard(
                padding: EdgeInsets.zero,
                child: ExpansionTile(
                  initiallyExpanded: day.dayOrder == 1,
                  tilePadding:
                      const EdgeInsets.symmetric(horizontal: MayosSpacing.md),
                  childrenPadding: const EdgeInsets.fromLTRB(
                      MayosSpacing.md, 0, MayosSpacing.md, MayosSpacing.md),
                  shape: const Border(),
                  collapsedShape: const Border(),
                  title: Text(
                    'Day ${day.dayOrder}: ${day.dayName}',
                    style: MayosTypography.sectionHeading
                        .copyWith(color: c.textPrimary),
                  ),
                  children: <Widget>[
                    ..._deloadBannerFor(day),
                    MayosButton(
                      label: 'Log workout',
                      icon: Icons.edit_note,
                      onPressed: () {
                        // Runs the Resume/Discard guard and creates the
                        // workout before routing to the logger (#123).
                        startWorkoutFromDay(
                          context,
                          ref,
                          day: day,
                          programVersion: program.version,
                        );
                      },
                    ),
                    const SizedBox(height: MayosSpacing.md),
                    if (day.hasWarmup) ...<Widget>[
                      const _SectionLabel('Warm-up'),
                      for (final WarmupExercise warmup in day.warmupExercises)
                        _WarmupRow(warmup: warmup),
                    ],
                    const _SectionLabel('Working sets'),
                    for (final ProgramExercise exercise in day.exercises)
                      _ExerciseRow(
                        exercise: exercise,
                        onTap: () => _openExercise(day, exercise),
                        onSubstitute: _substituting || _pickerBusy
                            ? null
                            : () => unawaited(
                                  _onSubstituteExercise(day, exercise),
                                ),
                      ),
                    if (day.hasCardio) ...<Widget>[
                      const _SectionLabel('Cardio'),
                      _CardioRow(cardio: day.cardio!),
                    ],
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// A centered message with an optional action, used for the load-failure and
/// no-program states.
class _CenteredMessage extends StatelessWidget {
  const _CenteredMessage({
    required this.message,
    this.actionLabel,
    this.onAction,
    this.loading = false,
    this.error,
  });

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;
  final bool loading;
  final String? error;

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
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
            if (error != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.sm),
              Text(
                error!,
                textAlign: TextAlign.center,
                style: MayosTypography.bodySecondary.copyWith(color: c.danger),
              ),
            ],
            if (actionLabel != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.lg),
              MayosButton(
                label: actionLabel!,
                loading: loading,
                expand: false,
                onPressed: onAction,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ProvenanceLabel extends StatelessWidget {
  const _ProvenanceLabel({required this.former});

  final bool former;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Row(
      children: <Widget>[
        Icon(
          former ? Icons.person_off_outlined : Icons.verified_user_outlined,
          size: 16,
          color: former ? c.textMuted : c.textSecondary,
        ),
        const SizedBox(width: MayosSpacing.xxs),
        Text(
          former ? 'Former coach' : 'Published by your coach',
          style: MayosTypography.caption.copyWith(
            color: former ? c.textMuted : c.textSecondary,
          ),
        ),
      ],
    );
  }
}

/// One tappable working-set row: exercise name, prescription, and warm-up/rest,
/// opening the read-only exercise detail.
class _ExerciseRow extends StatelessWidget {
  const _ExerciseRow({
    required this.exercise,
    required this.onTap,
    required this.onSubstitute,
  });

  final ProgramExercise exercise;
  final VoidCallback onTap;
  final VoidCallback? onSubstitute;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return InkWell(
      onTap: onTap,
      borderRadius: MayosRadii.smallRadius,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    exercise.exerciseName,
                    style: MayosTypography.exerciseTitle.copyWith(
                      color: c.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    exercise.prescription,
                    style: MayosTypography.bodySecondary.copyWith(
                      color: c.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    <String>[
                      if (exercise.hasWarmupSets)
                        '${exercise.warmupSets} warm-up '
                            '${exercise.warmupSets == 1 ? 'set' : 'sets'}',
                      exercise.restLabel,
                    ].join(' · '),
                    style: MayosTypography.caption.copyWith(color: c.textMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Icon(Icons.chevron_right, size: 20, color: c.textMuted),
            ),
            PopupMenuButton<String>(
              tooltip: 'More actions for ${exercise.exerciseName}',
              enabled: onSubstitute != null,
              onSelected: (String value) {
                if (value == 'substitute') onSubstitute?.call();
              },
              itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                const PopupMenuItem<String>(
                  value: 'substitute',
                  height: kMayosMinTapTarget,
                  child: Text('Substitute exercise'),
                ),
              ],
              icon: Icon(Icons.more_vert, color: c.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}

class _WarmupRow extends StatelessWidget {
  const _WarmupRow({required this.warmup});

  final WarmupExercise warmup;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    // ExpansionTile centres its children, so a shrink-wrapping row must be
    // explicitly left-aligned to sit flush with the section label and the
    // working-set rows.
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              warmup.exerciseName,
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: 2),
            Text(
              warmup.prescription,
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}

class _CardioRow extends StatelessWidget {
  const _CardioRow({required this.cardio});

  final String cardio;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(Icons.directions_run, size: 16, color: c.textMuted),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              cardio,
              style: MayosTypography.bodySecondary.copyWith(
                color: c.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OfflineBanner extends StatelessWidget {
  const _OfflineBanner();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.sm),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.cloud_off, size: 18, color: c.textSecondary),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              'Offline — showing saved program',
              style: MayosTypography.bodySecondary.copyWith(
                color: c.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding:
          const EdgeInsets.only(top: MayosSpacing.md, bottom: MayosSpacing.xxs),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Text(
          text,
          style: MayosTypography.caption.copyWith(
            color: c.textMuted,
            letterSpacing: 0.6,
          ),
        ),
      ),
    );
  }
}
