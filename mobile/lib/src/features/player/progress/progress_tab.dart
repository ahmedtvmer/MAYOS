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
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_segmented_control.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'progress_chart.dart';

/// The player Progress tab (#48).
///
/// Every figure is derived from the persisted training ledger:
/// * **Strength** charts the per-session estimated 1RM (kg) from
///   `GET /dashboard/exercises/{id}/history` for an exercise the player has
///   actually logged (`GET /dashboard/exercises`).
/// * **Volume** charts weighted working sets per muscle over a real 7/28/90 day
///   window from `GET /dashboard/volume?days=N`.
///
/// There is no Overview tab: no endpoint provides a real session/PR summary
/// (and no fabricated percentage, body metric, or readiness is ever shown).
class ProgressTab extends ConsumerStatefulWidget {
  const ProgressTab({super.key});

  @override
  ConsumerState<ProgressTab> createState() => _ProgressTabState();
}

class _ProgressTabState extends ConsumerState<ProgressTab> {
  static const List<int> _volumePeriods = <int>[7, 28, 90];

  bool _loading = true;
  String? _loadError;

  /// A non-fatal refresh failure: the last loaded data stays visible with a
  /// quiet notice (honest offline behaviour) instead of blanking the screen.
  String? _notice;

  List<LoggedExercise> _exercises = const <LoggedExercise>[];
  String? _selectedExerciseId;
  ExerciseHistory? _history;
  String? _historyError;
  bool _historyLoading = false;

  Map<String, double> _volume = const <String, double>{};
  String? _volumeError;
  bool _volumeLoading = false;
  int _volumeDays = 7;

  int? _selectedPoint;
  String _section = 'strength';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
      _notice = null;
    });
    final List<LoggedExercise> exercises;
    try {
      exercises = await ref.read(apiClientProvider).loggedExercises();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (_exercises.isNotEmpty) {
          _notice = _failureMessage(error);
        } else {
          _loadError = _failureMessage(error);
        }
      });
      return;
    }
    if (!mounted) return;
    final String? selected = exercises.any(
      (LoggedExercise e) => e.id == _selectedExerciseId,
    )
        ? _selectedExerciseId
        : (exercises.isEmpty ? null : exercises.first.id);
    setState(() {
      _exercises = exercises;
      _selectedExerciseId = selected;
      _selectedPoint = null;
      _loading = false;
    });
    await Future.wait<void>(<Future<void>>[
      if (selected != null) _loadHistory(selected),
      _loadVolume(_volumeDays),
    ]);
  }

  Future<void> _loadHistory(String exerciseId) async {
    setState(() {
      _historyLoading = true;
      _historyError = null;
      _selectedPoint = null;
    });
    try {
      final ExerciseHistory history =
          await ref.read(apiClientProvider).exerciseHistory(exerciseId);
      if (!mounted || _selectedExerciseId != exerciseId) return;
      setState(() {
        _history = history;
        _historyLoading = false;
      });
    } on ApiException catch (error) {
      if (!mounted || _selectedExerciseId != exerciseId) return;
      setState(() {
        _historyError = _failureMessage(error);
        _historyLoading = false;
      });
    }
  }

  Future<void> _loadVolume(int days) async {
    setState(() {
      _volumeLoading = true;
      _volumeError = null;
    });
    try {
      final Map<String, double> volume =
          await ref.read(apiClientProvider).volume(days: days);
      if (!mounted || _volumeDays != days) return;
      setState(() {
        _volume = volume;
        _volumeLoading = false;
      });
    } on ApiException catch (error) {
      if (!mounted || _volumeDays != days) return;
      setState(() {
        _volumeError = _failureMessage(error);
        _volumeLoading = false;
      });
    }
  }

  void _selectExercise(String exerciseId) {
    setState(() {
      _selectedExerciseId = exerciseId;
      _history = null;
    });
    _loadHistory(exerciseId);
  }

  void _selectPeriod(int days) {
    if (days == _volumeDays) return;
    setState(() => _volumeDays = days);
    _loadVolume(days);
  }

  void _goToProgram() {
    ref.read(playerShellTabProvider.notifier).state = 1;
  }

  String _failureMessage(ApiException error) =>
      isNetworkFailure(error) ? needsConnectionMessage : error.message;

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return _ErrorView(message: _loadError!, onRetry: _load);
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(MayosSpacing.lg, MayosSpacing.md,
            MayosSpacing.lg, MayosSpacing.xxl),
        children: <Widget>[
          Text(
            'Progress',
            style: MayosTypography.display.copyWith(
              fontSize: 34,
              color: c.textPrimary,
            ),
          ),
          if (_notice != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            _InlineNotice(message: _notice!),
          ],
          const SizedBox(height: MayosSpacing.lg),
          if (_exercises.isEmpty)
            _NoHistoryState(onGoToProgram: _goToProgram)
          else ...<Widget>[
            MayosSegmentedControl<String>(
              segments: const <MayosSegment<String>>[
                MayosSegment<String>(value: 'strength', label: 'Strength'),
                MayosSegment<String>(value: 'volume', label: 'Volume'),
              ],
              selected: _section,
              onChanged: (String value) => setState(() => _section = value),
            ),
            const SizedBox(height: MayosSpacing.xl),
            if (_section == 'volume')
              _VolumeSection(
                volume: _volume,
                days: _volumeDays,
                periods: _volumePeriods,
                loading: _volumeLoading,
                error: _volumeError,
                onPeriod: _selectPeriod,
                onRetry: () => _loadVolume(_volumeDays),
              )
            else
              _StrengthSection(
                exercises: _exercises,
                selectedId: _selectedExerciseId,
                history: _history,
                loading: _historyLoading,
                error: _historyError,
                selectedPoint: _selectedPoint,
                onSelectExercise: _selectExercise,
                onSelectPoint: (int index) =>
                    setState(() => _selectedPoint = index),
                onRetry: () {
                  final String? id = _selectedExerciseId;
                  if (id != null) _loadHistory(id);
                },
              ),
          ],
        ],
      ),
    );
  }
}

class _StrengthSection extends StatelessWidget {
  const _StrengthSection({
    required this.exercises,
    required this.selectedId,
    required this.history,
    required this.loading,
    required this.error,
    required this.selectedPoint,
    required this.onSelectExercise,
    required this.onSelectPoint,
    required this.onRetry,
  });

  final List<LoggedExercise> exercises;
  final String? selectedId;
  final ExerciseHistory? history;
  final bool loading;
  final String? error;
  final int? selectedPoint;
  final ValueChanged<String> onSelectExercise;
  final ValueChanged<int> onSelectPoint;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    LoggedExercise? selected;
    for (final LoggedExercise exercise in exercises) {
      if (exercise.id == selectedId) {
        selected = exercise;
        break;
      }
    }
    final String name = selected?.name ?? 'Exercise';
    final List<ExerciseHistoryPoint> points =
        history?.history ?? const <ExerciseHistoryPoint>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        _ExerciseSelector(
          exercises: exercises,
          selectedId: selectedId,
          onSelected: onSelectExercise,
        ),
        const SizedBox(height: MayosSpacing.xl),
        MayosSectionHeader(
          title: 'Estimated 1RM',
          subtitle: '$name · kg · all logged sessions',
        ),
        if (loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: MayosSpacing.xl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (error != null)
          _InlineError(message: error!, onRetry: onRetry)
        else if (points.isEmpty)
          Text(
            'No sets recorded for $name yet. Log a workout to start a trend.',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          )
        else ...<Widget>[
          _StrengthChart(
            exerciseName: name,
            points: points,
            selectedIndex: selectedPoint,
            onSelectPoint: onSelectPoint,
          ),
          if (points.length < 2) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              'Only one session logged. A trend needs at least two sessions.',
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
          ],
          if (selectedPoint != null &&
              selectedPoint! < points.length) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            _PointCallout(point: points[selectedPoint!]),
          ],
          const SizedBox(height: MayosSpacing.xl),
          MayosSectionHeader(title: 'Recent sessions'),
          for (final ExerciseHistoryPoint point in points.reversed)
            _SessionRow(point: point),
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            label: 'View exercise',
            icon: Icons.arrow_forward,
            variant: MayosButtonVariant.secondary,
            expand: false,
            onPressed: () =>
                context.push('$exerciseDetailPath/$selectedId?tab=history'),
          ),
        ],
      ],
    );
  }
}

class _ExerciseSelector extends StatelessWidget {
  const _ExerciseSelector({
    required this.exercises,
    required this.selectedId,
    required this.onSelected,
  });

  final List<LoggedExercise> exercises;
  final String? selectedId;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.xs),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: selectedId,
          isExpanded: true,
          borderRadius: BorderRadius.circular(MayosRadii.medium),
          dropdownColor: c.surfaceElevated,
          icon: Icon(Icons.expand_more, color: c.textSecondary),
          style: MayosTypography.body.copyWith(color: c.textPrimary),
          onChanged: (String? value) {
            if (value != null) onSelected(value);
          },
          items: <DropdownMenuItem<String>>[
            for (final LoggedExercise exercise in exercises)
              DropdownMenuItem<String>(
                value: exercise.id,
                child: Text(
                  exercise.name,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _StrengthChart extends StatelessWidget {
  const _StrengthChart({
    required this.exerciseName,
    required this.points,
    required this.selectedIndex,
    required this.onSelectPoint,
  });

  final String exerciseName;
  final List<ExerciseHistoryPoint> points;
  final int? selectedIndex;
  final ValueChanged<int> onSelectPoint;

  @override
  Widget build(BuildContext context) {
    return MayosCard(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.xs, MayosSpacing.md, MayosSpacing.sm, MayosSpacing.xs),
      child: ProgressLineChart(
        key: const Key('progress.chart'),
        points: <ProgressChartPoint>[
          for (final ExerciseHistoryPoint point in points)
            ProgressChartPoint(date: point.date, value: point.e1rm),
        ],
        metricLabel: 'Estimated 1RM',
        unit: 'kg',
        exerciseName: exerciseName,
        selectedIndex: selectedIndex,
        onPointSelected: onSelectPoint,
      ),
    );
  }
}

class _PointCallout extends StatelessWidget {
  const _PointCallout({required this.point});

  final ExerciseHistoryPoint point;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      key: const Key('progress.callout'),
      width: double.infinity,
      padding: const EdgeInsets.all(MayosSpacing.md),
      decoration: BoxDecoration(
        color: c.accentSubtle,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Session · ${shortDate(point.date)}',
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            '${_formatValue(point.weightKg)} kg × ${point.reps} reps @ RPE '
            '${_formatValue(point.rpe)}',
            style: MayosTypography.numericSmall.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: 2),
          Text(
            'e1RM ${_formatValue(point.e1rm)} kg',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
        ],
      ),
    );
  }
}

class _SessionRow extends StatelessWidget {
  const _SessionRow({required this.point});

  final ExerciseHistoryPoint point;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Row(
        children: <Widget>[
          SizedBox(
            width: 64,
            child: Text(
              shortDate(point.date),
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ),
          Expanded(
            child: Text(
              '${_formatValue(point.weightKg)} kg × ${point.reps} @ RPE '
              '${_formatValue(point.rpe)}',
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
          ),
          const SizedBox(width: MayosSpacing.xs),
          Text(
            'e1RM ${_formatValue(point.e1rm)}',
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          ),
        ],
      ),
    );
  }
}

class _VolumeSection extends StatelessWidget {
  const _VolumeSection({
    required this.volume,
    required this.days,
    required this.periods,
    required this.loading,
    required this.error,
    required this.onPeriod,
    required this.onRetry,
  });

  final Map<String, double> volume;
  final int days;
  final List<int> periods;
  final bool loading;
  final String? error;
  final ValueChanged<int> onPeriod;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
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
        MayosSegmentedControl<int>(
          segments: <MayosSegment<int>>[
            for (final int period in periods)
              MayosSegment<int>(value: period, label: '$period days'),
          ],
          selected: days,
          onChanged: onPeriod,
        ),
        const SizedBox(height: MayosSpacing.xl),
        MayosSectionHeader(
          title: 'Weighted sets',
          subtitle: 'Last $days days · working sets per muscle',
        ),
        if (loading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: MayosSpacing.xl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (error != null)
          _InlineError(message: error!, onRetry: onRetry)
        else if (muscles.isEmpty)
          Text(
            'No weighted sets logged in the last $days days.',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          )
        else ...<Widget>[
          Text(
            '${_formatValue(total)} weighted sets',
            style: MayosTypography.numericSmall.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            'Primary muscle counts 1 per working set, each secondary 0.5.',
            style: MayosTypography.caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MayosSpacing.md),
          for (final MapEntry<String, double> entry in muscles)
            _MuscleVolumeBar(
              muscle: entry.key,
              value: entry.value,
              fraction: entry.value / muscles.first.value,
            ),
        ],
      ],
    );
  }
}

class _MuscleVolumeBar extends StatelessWidget {
  const _MuscleVolumeBar({
    required this.muscle,
    required this.value,
    required this.fraction,
  });

  final String muscle;
  final double value;
  final double fraction;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  muscle,
                  style: MayosTypography.bodySecondary
                      .copyWith(color: c.textPrimary),
                ),
              ),
              const SizedBox(width: MayosSpacing.xs),
              Text(
                _formatValue(value),
                style: MayosTypography.numericSmall
                    .copyWith(color: c.textSecondary),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.xs),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: SizedBox(
              height: 6,
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: fraction.clamp(0.0, 1.0),
                child: DecoratedBox(
                  decoration: BoxDecoration(color: c.chartPrimary),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NoHistoryState extends StatelessWidget {
  const _NoHistoryState({required this.onGoToProgram});

  final VoidCallback onGoToProgram;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          'No training history yet',
          style: MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          'Log a workout and your strength trend, volume, and per-exercise '
          'records will appear here.',
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosButton(
          label: 'Go to Program',
          icon: Icons.article_outlined,
          variant: MayosButtonVariant.secondary,
          expand: false,
          onPressed: onGoToProgram,
        ),
      ],
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          message,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          label: 'Retry',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: onRetry,
        ),
      ],
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
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
        ),
      ],
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
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.md),
            MayosButton(
              label: 'Retry',
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
  if ((value - value.roundToDouble()).abs() < 0.05) {
    return value.round().toString();
  }
  return value.toStringAsFixed(1);
}
