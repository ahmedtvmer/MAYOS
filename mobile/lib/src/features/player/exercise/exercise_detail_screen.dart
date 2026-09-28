import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/effort.dart';
import '../../../core/config.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_segmented_control.dart';
import '../../../providers.dart';

/// Read-only exercise detail (#53): a typographic/muscle-group hero, the
/// prescription stat trio when opened from a program day, and Overview /
/// Technique / History tabs backed by real catalog and dashboard data.
///
/// The hero stays fully useful without media; exercise media is gated behind
/// [mayosExerciseMediaEnabled] and a loadable URL, neither of which exist yet.
class ExerciseDetailScreen extends ConsumerStatefulWidget {
  const ExerciseDetailScreen({
    super.key,
    required this.exerciseId,
    this.dayOrder,
    this.initialTab = 'overview',
  });

  final String exerciseId;

  /// The program day the exercise was opened from, so prescription context
  /// (sets × reps, RIR, rest, notes) can be shown. Null when opened elsewhere.
  final int? dayOrder;

  /// Which tab to open on. Progress (#48) opens this screen on `history`.
  final String initialTab;

  @override
  ConsumerState<ExerciseDetailScreen> createState() =>
      _ExerciseDetailScreenState();
}

class _DetailData {
  const _DetailData({
    required this.exercise,
    required this.catalog,
    required this.history,
    this.partialError,
  });

  final ProgramExercise? exercise;
  final ExerciseCatalogDetail? catalog;
  final ExerciseHistory? history;
  final String? partialError;
}

class _ExerciseDetailScreenState extends ConsumerState<ExerciseDetailScreen> {
  late Future<_DetailData> _future;
  late String _tab;

  @override
  void initState() {
    super.initState();
    _tab = widget.initialTab;
    _future = _load();
  }

  Future<_DetailData> _load() async {
    final ApiClient api = ref.read(apiClientProvider);
    ProgramExercise? exercise;
    ExerciseCatalogDetail? catalog;
    ExerciseHistory? history;
    String? partialError;

    try {
      final TrainingProgram? program = await api.activeProgram();
      for (final ProgramDay day in program?.days ?? const <ProgramDay>[]) {
        if (widget.dayOrder != null && day.dayOrder != widget.dayOrder) {
          continue;
        }
        for (final ProgramExercise candidate in day.exercises) {
          if (candidate.exerciseId == widget.exerciseId) {
            exercise = candidate;
            break;
          }
        }
        if (exercise != null) break;
      }
    } on ApiException catch (error) {
      partialError = error.message;
    }
    try {
      catalog = await api.exerciseCatalogDetail(widget.exerciseId);
    } on ApiException catch (error) {
      partialError ??= error.message;
    }
    try {
      history = await api.exerciseHistory(widget.exerciseId);
    } on ApiException catch (error) {
      partialError ??= error.message;
    }

    return _DetailData(
      exercise: exercise,
      catalog: catalog,
      history: history,
      partialError: partialError,
    );
  }

  Future<void> _retry() async {
    final Future<_DetailData> future = _load();
    setState(() => _future = future);
    await future;
  }

  @override
  Widget build(BuildContext context) {
    return MayosScaffold(
      header: const MayosAppHeader(showBack: true),
      body: FutureBuilder<_DetailData>(
        future: _future,
        builder: (BuildContext context, AsyncSnapshot<_DetailData> snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return _ErrorView(
                message: 'Could not load this exercise.', onRetry: _retry);
          }
          final _DetailData data = snapshot.data!;
          if (data.catalog == null && data.exercise == null) {
            return _ErrorView(
              message: data.partialError ?? 'This exercise is not available.',
              onRetry: _retry,
            );
          }
          return _DetailBody(
              data: data,
              tab: _tab,
              onTab: (String tab) => setState(() => _tab = tab));
        },
      ),
    );
  }
}

class _DetailBody extends StatelessWidget {
  const _DetailBody({
    required this.data,
    required this.tab,
    required this.onTab,
  });

  final _DetailData data;
  final String tab;
  final ValueChanged<String> onTab;

  @override
  Widget build(BuildContext context) {
    final ExerciseCatalogDetail? catalog = data.catalog;
    final ProgramExercise? exercise = data.exercise;
    final String name = catalog?.name ?? exercise?.exerciseName ?? 'Exercise';

    return ListView(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.lg, MayosSpacing.xxl),
      children: <Widget>[
        _Hero(name: name, catalog: catalog),
        if (exercise != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xl),
          _PrescriptionTrio(exercise: exercise),
        ],
        if (data.partialError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          _InlineNotice(message: data.partialError!),
        ],
        const SizedBox(height: MayosSpacing.xl),
        MayosSegmentedControl<String>(
          segments: const <MayosSegment<String>>[
            MayosSegment<String>(value: 'overview', label: 'Overview'),
            MayosSegment<String>(value: 'technique', label: 'Technique'),
            MayosSegment<String>(value: 'history', label: 'History'),
          ],
          selected: tab,
          onChanged: onTab,
        ),
        const SizedBox(height: MayosSpacing.xl),
        switch (tab) {
          'technique' => _TechniqueTab(catalog: catalog),
          'history' => _HistoryTab(history: data.history),
          _ => _OverviewTab(catalog: catalog, exercise: exercise),
        },
      ],
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.name, required this.catalog});

  final String name;
  final ExerciseCatalogDetail? catalog;

  @override
  Widget build(BuildContext context) {
    final ExerciseCatalogDetail? detail = catalog;

    // Media is gated behind the build flag AND a loadable absolute URL; the
    // catalog stores relative ExerciseDB file paths, so today the hero is
    // always the typographic header (see MEDIA-PROVENANCE.md).
    if (mayosExerciseMediaEnabled &&
        detail != null &&
        detail.hasLoadableMedia) {
      final String url = detail.imagePath ?? detail.gifPath!;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: Image.network(
              url,
              height: 200,
              width: double.infinity,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) =>
                  _typographicHeader(context, name, detail),
            ),
          ),
          const SizedBox(height: MayosSpacing.md),
          _typographicHeader(context, name, detail),
        ],
      );
    }

    return _typographicHeader(context, name, detail);
  }

  Widget _typographicHeader(
      BuildContext context, String name, ExerciseCatalogDetail? detail) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<String> primary = detail?.primaryMuscles ?? const <String>[];
    final Set<String> primaryLower =
        primary.map((String m) => m.toLowerCase()).toSet();
    // Secondary muscles only, without repeating a primary muscle.
    final List<String> secondary = <String>[
      for (final String muscle in detail?.secondaryMuscles ?? const <String>[])
        if (!primaryLower.contains(muscle.toLowerCase())) muscle,
    ];
    // Category/body part are the same field upstream; never repeat a label that
    // is already shown as a muscle chip.
    final String category = detail?.category ?? '';
    final bool showCategory = category.isNotEmpty &&
        !primaryLower.contains(category.toLowerCase()) &&
        !secondary
            .map((String m) => m.toLowerCase())
            .contains(category.toLowerCase());
    final String equipment = detail?.equipment ?? '';
    final bool hasChips = primary.isNotEmpty ||
        secondary.isNotEmpty ||
        showCategory ||
        equipment.isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          name,
          style: MayosTypography.display.copyWith(
            fontSize: 34,
            color: c.textPrimary,
          ),
        ),
        if (hasChips) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (final String muscle in primary)
                _TagChip(label: titleCase(muscle), tone: _ChipTone.primary),
              for (final String muscle in secondary)
                _TagChip(label: titleCase(muscle), tone: _ChipTone.secondary),
              if (showCategory)
                _TagChip(label: titleCase(category), tone: _ChipTone.secondary),
              if (equipment.isNotEmpty)
                _TagChip(
                  label: titleCase(equipment),
                  tone: _ChipTone.equipment,
                  icon: Icons.fitness_center,
                ),
            ],
          ),
        ],
      ],
    );
  }
}

/// Chip emphasis: primary muscles highlighted, secondary muted, equipment
/// distinct with a small icon.
enum _ChipTone { primary, secondary, equipment }

class _TagChip extends StatelessWidget {
  const _TagChip({
    required this.label,
    this.tone = _ChipTone.secondary,
    this.icon,
  });

  final String label;
  final _ChipTone tone;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool highlighted = tone == _ChipTone.primary;
    final Color background = highlighted ? c.accentSubtle : c.secondarySurface;
    final Color foreground = highlighted ? c.accent : c.textSecondary;
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(MayosRadii.pill),
        border: Border.all(color: highlighted ? Colors.transparent : c.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (icon != null) ...<Widget>[
            Icon(icon, size: 13, color: foreground),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: MayosTypography.caption.copyWith(color: foreground),
          ),
        ],
      ),
    );
  }
}

class _PrescriptionTrio extends StatelessWidget {
  const _PrescriptionTrio({required this.exercise});

  final ProgramExercise exercise;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: _PrescriptionStat(
            value: '${exercise.targetSets} × '
                '${exercise.targetRepsMin}–${exercise.targetRepsMax}',
            label: 'Sets × reps',
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: 'RIR ${minRirLabel(exercise.targetRpe)}',
            label: 'Intensity',
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: '${exercise.restSeconds}s',
            label: 'Rest',
          ),
        ),
      ],
    );
  }
}

class _PrescriptionStat extends StatelessWidget {
  const _PrescriptionStat({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(
            value,
            maxLines: 1,
            style: MayosTypography.numericSmall.copyWith(color: c.textPrimary),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: MayosTypography.caption.copyWith(color: c.textMuted),
        ),
      ],
    );
  }
}

class _OverviewTab extends StatelessWidget {
  const _OverviewTab({required this.catalog, required this.exercise});

  final ExerciseCatalogDetail? catalog;
  final ProgramExercise? exercise;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ExerciseCatalogDetail? detail = catalog;
    final ProgramExercise? ex = exercise;
    final String category = detail?.category ?? '';
    final String bodyPart = detail?.bodyPart ?? '';
    final bool categoryIsBodyPart = category.isNotEmpty &&
        bodyPart.isNotEmpty &&
        category.toLowerCase() == bodyPart.toLowerCase();
    final List<(String, String?)> rows = <(String, String?)>[
      if (category.isNotEmpty) ('Category', titleCase(category)),
      // Body part mirrors category upstream; show it only when it differs.
      if (bodyPart.isNotEmpty && !categoryIsBodyPart)
        ('Body part', titleCase(bodyPart)),
      if (detail != null && detail.equipment.isNotEmpty)
        ('Equipment', titleCase(detail.equipment)),
      if (ex != null && ex.hasNotes) ('Notes', ex.notes),
    ];

    if (rows.isEmpty) {
      return _EmptyTab(
        message: 'No details are available for this exercise.',
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        for (int i = 0; i < rows.length; i++) ...<Widget>[
          _DetailRow(label: rows[i].$1, value: rows[i].$2!),
          if (i < rows.length - 1)
            Divider(height: 1, thickness: 1, color: c.border),
        ],
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 108,
            child: Text(
              label,
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
          ),
        ],
      ),
    );
  }
}

class _TechniqueTab extends StatelessWidget {
  const _TechniqueTab({required this.catalog});

  final ExerciseCatalogDetail? catalog;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String? instructions = catalog?.instructions;
    if (instructions == null || instructions.trim().isEmpty) {
      return const _EmptyTab(
        message: 'Instructions aren\'t available for this exercise yet.',
      );
    }
    final List<String> steps = instructions
        .split('\n')
        .map((String line) => line.trim())
        .where((String line) => line.isNotEmpty)
        .toList(growable: false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (int i = 0; i < steps.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                SizedBox(
                  width: 28,
                  child: Text(
                    '${i + 1}',
                    style: MayosTypography.numericSmall.copyWith(
                      color: c.accent,
                      fontSize: 15,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    steps[i],
                    style: MayosTypography.body.copyWith(color: c.textPrimary),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _HistoryTab extends StatelessWidget {
  const _HistoryTab({required this.history});

  final ExerciseHistory? history;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ExerciseHistoryPoint> points =
        history?.history ?? const <ExerciseHistoryPoint>[];
    if (points.isEmpty) {
      return const _EmptyTab(
        message:
            'No history for this exercise yet. Log a workout to see it here.',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (history?.caption != null) ...<Widget>[
          Text(
            history!.caption!.replaceAll('**', ''),
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
        ],
        for (final ExerciseHistoryPoint point in points.reversed)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Row(
              children: <Widget>[
                SizedBox(
                  width: 88,
                  child: Text(
                    point.date,
                    style: MayosTypography.caption.copyWith(color: c.textMuted),
                  ),
                ),
                Expanded(
                  child: Text(
                    '${_trim(point.weightKg)} kg × ${point.reps} @ RIR '
                    '${rirLabel(point.rpe)}',
                    style: MayosTypography.body.copyWith(color: c.textPrimary),
                  ),
                ),
                Text(
                  'e1RM ${_trim(point.e1rm)}',
                  style:
                      MayosTypography.caption.copyWith(color: c.textSecondary),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _EmptyTab extends StatelessWidget {
  const _EmptyTab({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.md),
      child: Text(
        message,
        style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
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
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

String _trim(double value) => value == value.roundToDouble()
    ? value.round().toString()
    : value.toStringAsFixed(1);

/// Title-cases a catalog label for display ("barbell" → "Barbell",
/// "upper back" → "Upper Back"). Catalog values are stored lowercase.
String titleCase(String value) => value
    .split(' ')
    .where((String word) => word.isNotEmpty)
    .map((String word) =>
        '${word[0].toUpperCase()}${word.substring(1).toLowerCase()}')
    .join(' ');
