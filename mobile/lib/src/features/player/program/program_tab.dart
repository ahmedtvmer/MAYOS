import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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

/// A cache read on the offline path may never block indefinitely.
const Duration _cacheReadTimeout = Duration(seconds: 3);

class ProgramTab extends ConsumerStatefulWidget {
  const ProgramTab({super.key});

  @override
  ConsumerState<ProgramTab> createState() => _ProgramTabState();
}

class _ProgramTabState extends ConsumerState<ProgramTab> {
  bool _loading = true;
  bool _generating = false;
  String? _loadError;
  String? _actionError;
  TrainingProgram? _program;

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
      final TrainingProgram? online =
          await ref.read(apiClientProvider).activeProgram();
      if (online != null && accountId != null) {
        unawaited(_cacheProgram(cache, accountId, online));
      }
      if (!mounted) return;
      setState(() {
        _program = online;
        _fromCache = false;
        _loading = false;
      });
    } on ApiException catch (error) {
      final TrainingProgram? cached =
          accountId == null ? null : await _readCachedProgram(cache, accountId);
      if (!mounted) return;
      if (cached != null) {
        setState(() {
          _program = cached;
          _fromCache = true;
          _loading = false;
        });
      } else {
        setState(() {
          _loadError = error.message;
          _loading = false;
        });
      }
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
        unawaited(_cacheProgram(
            ref.read(workoutCacheStoreProvider), accountId, program));
      }
      if (!mounted) return;
      setState(() {
        _generating = false;
        _program = program;
        _fromCache = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _generating = false;
        _actionError = mutationFailureMessage(error);
      });
    }
  }

  /// Caching the fetched program is fire-and-forget: a slow or failing store
  /// must never hide (or delay showing) an otherwise-successful online fetch
  /// (ADR 020/033).
  Future<void> _cacheProgram(WorkoutCacheStore cache, String accountId,
      TrainingProgram program) async {
    try {
      await cache.writeProgram(accountId, program);
    } on Object {
      // Offline logging simply won't have this program cached; not fatal here.
    }
  }

  Future<TrainingProgram?> _readCachedProgram(
      WorkoutCacheStore cache, String accountId) async {
    try {
      return await cache.readProgram(accountId).timeout(_cacheReadTimeout);
    } on Object {
      return null;
    }
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
          if (program.version != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            Text(
              'Version ${program.version}',
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ],
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
                    if (ref.watch(
                        offlineWorkoutDraftsEnabledProvider)) ...<Widget>[
                      MayosButton(
                        label: 'Log workout',
                        icon: Icons.edit_note,
                        onPressed: () =>
                            context.go('$logWorkoutPath/${day.dayOrder}'),
                      ),
                      const SizedBox(height: MayosSpacing.md),
                    ],
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

/// One tappable working-set row: exercise name, prescription, warm-up/rest, and
/// notes, opening the read-only exercise detail.
class _ExerciseRow extends StatelessWidget {
  const _ExerciseRow({required this.exercise, required this.onTap});

  final ProgramExercise exercise;
  final VoidCallback onTap;

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
                  if (exercise.hasNotes) ...<Widget>[
                    const SizedBox(height: 2),
                    Text(
                      exercise.notes!,
                      style: MayosTypography.caption.copyWith(
                        color: c.textSecondary,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Icon(Icons.chevron_right, size: 20, color: c.textMuted),
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
            if (warmup.hasNotes) ...<Widget>[
              const SizedBox(height: 2),
              Text(
                warmup.notes!,
                style: MayosTypography.caption.copyWith(color: c.textSecondary),
              ),
            ],
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
