import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/app_failure.dart';
import '../../../core/active_workout.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/feature_copy_context.dart';
import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/effort.dart';
import '../../../core/config.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_segmented_control.dart';
import '../../../core/workout_equipment.dart';
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
    this.showProgram = true,
    this.initialTab = 'overview',
  });

  final String exerciseId;

  /// The program day the exercise was opened from. Null searches all days.
  final int? dayOrder;

  /// Whether this detail should load a matching program prescription.
  final bool showProgram;

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
  final FailureMessage? partialError;
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
    FailureMessage? partialError;

    if (widget.showProgram) {
      try {
        exercise = _programExerciseForDay(
          await api.activeProgram(),
          widget.dayOrder,
        );
      } on ApiException catch (error) {
        partialError = apiFailureMessage(error);
      }
    }
    try {
      catalog = await api.exerciseCatalogDetail(widget.exerciseId);
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }
    try {
      history = await api.exerciseHistory(widget.exerciseId);
    } on ApiException catch (error) {
      partialError ??= apiFailureMessage(error);
    }

    return _DetailData(
      exercise: exercise,
      catalog: catalog,
      history: history,
      partialError: partialError,
    );
  }

  ProgramExercise? _programExerciseForDay(
    TrainingProgram? program,
    int? dayOrder,
  ) {
    for (final ProgramDay day in program?.days ?? const <ProgramDay>[]) {
      if (dayOrder != null && day.dayOrder != dayOrder) continue;
      for (final ProgramExercise candidate in day.exercises) {
        if (candidate.exerciseId == widget.exerciseId) return candidate;
      }
    }
    return null;
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
                message: displayCopyOf(context).loadExerciseFailed,
                onRetry: _retry);
          }
          final _DetailData data = snapshot.data!;
          if (data.catalog == null && data.exercise == null) {
            return _ErrorView(
              message: data.partialError == null
                  ? displayCopyOf(context).exerciseUnavailable
                  : displayCopyOf(context).failureMessage(data.partialError!),
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
    final String name = catalog?.name ??
        exercise?.exerciseName ??
        displayCopyOf(context).exerciseFallbackName;

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
          _InlineNotice(
            message: displayCopyOf(context).failureMessage(data.partialError!),
          ),
        ],
        const SizedBox(height: MayosSpacing.xl),
        MayosSegmentedControl<String>(
          segments: <MayosSegment<String>>[
            MayosSegment<String>(
                value: 'overview', label: displayCopyOf(context).overview),
            MayosSegment<String>(
                value: 'technique', label: displayCopyOf(context).technique),
            MayosSegment<String>(
                value: 'history', label: displayCopyOf(context).history),
          ],
          selected: tab,
          onChanged: onTab,
        ),
        const SizedBox(height: MayosSpacing.xl),
        switch (tab) {
          'technique' => _TechniqueTab(catalog: catalog),
          'history' => _HistoryTab(
              history: data.history,
              equipment: catalog?.equipment ?? data.history?.equipment,
            ),
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
    final MayosThemeExtension c = MayosTheme.of(context);

    // Media is gated behind the build flag (#53: off is the kill switch) and
    // a path `/media` can serve; with neither, today's typographic header is
    // the whole hero.
    if (mayosExerciseMediaEnabled &&
        detail != null &&
        detail.hasLoadableMedia) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // A fixed 180×180 box — Gym visual's native size, never upscaled
          // past it — so loading and failure states never shift the layout.
          Align(
            alignment: Alignment.center,
            child: _CatalogMedia(detail: detail),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            gymVisualCreditShort,
            textAlign: TextAlign.center,
            style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
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
    final MayosCopy copy = displayCopyOf(context);
    final List<String> primary = <String>[
      if (detail?.primaryMuscle != null) detail!.primaryMuscle!,
      for (final String muscle in detail?.primaryMuscles ?? const <String>[])
        if (muscle.toLowerCase() != detail?.primaryMuscle?.toLowerCase())
          muscle,
    ];
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
    final String? primaryAction = detail?.primaryAction;
    final List<String> secondaryActions =
        detail?.secondaryActions ?? const <String>[];
    final bool hasChips = primary.isNotEmpty ||
        secondary.isNotEmpty ||
        showCategory ||
        equipment.isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          name,
          style: MayosTypography.of(context).display.copyWith(
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
                _TagChip(
                  label: muscle == detail?.primaryMuscle
                      ? copy.primaryMuscleLabel(muscle)
                      : titleCase(muscle),
                  tone: _ChipTone.primary,
                ),
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
        if (primaryAction != null || secondaryActions.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              if (primaryAction != null) ...<Widget>[
                Text(copy.primaryAction),
                _TagChip(
                  label: copy.primaryActionLabel(primaryAction),
                  tone: _ChipTone.primary,
                ),
              ],
              if (secondaryActions.isNotEmpty) ...<Widget>[
                Text(copy.secondaryActions),
                for (final String action in secondaryActions)
                  _TagChip(
                    label: copy.primaryActionLabel(action),
                    tone: _ChipTone.secondary,
                  ),
              ],
            ],
          ),
        ],
      ],
    );
  }
}

/// The catalog media in its fixed box (#53/#161): the animated GIF first,
/// the still picture when the GIF is missing or fails, then a calm glyph —
/// every state inside the same 180×180 footprint, centred, so loading and
/// failure never shift the layout.
class _CatalogMedia extends StatelessWidget {
  const _CatalogMedia({required this.detail});

  /// Gym visual's native size: the box never grows past it and the picture
  /// is painted `contain` inside it, so the media is never stretched larger
  /// than 180×180 logical pixels either (Gym visual's terms).
  static const double size = 180;

  final ExerciseCatalogDetail detail;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ClipRRect(
      borderRadius: MayosRadii.mediumRadius,
      child: SizedBox(
        width: size,
        height: size,
        child: ColoredBox(
          color: c.surfaceSunken,
          child: _gif(context, c),
        ),
      ),
    );
  }

  /// The GIF animates as any multi-frame network image does; a failed or
  /// absent GIF falls back to the still picture in the same box.
  Widget _gif(BuildContext context, MayosThemeExtension c) {
    final String? url = detail.gifUrl;
    if (url == null) {
      return _still(context, c);
    }
    return Image.network(
      url,
      width: size,
      height: size,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      loadingBuilder: (_, Widget child, ImageChunkEvent? progress) =>
          progress == null ? child : _placeholder(c),
      errorBuilder: (_, __, ___) => _still(context, c),
    );
  }

  Widget _still(BuildContext context, MayosThemeExtension c) {
    final String? url = detail.imageUrl;
    if (url == null) {
      return _fallback(context, c);
    }
    return Image.network(
      url,
      width: size,
      height: size,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      loadingBuilder: (_, Widget child, ImageChunkEvent? progress) =>
          progress == null ? child : _placeholder(c),
      errorBuilder: (_, __, ___) => _fallback(context, c),
    );
  }

  /// A static glyph while the bytes arrive — never a spinner, so the screen
  /// keeps no animation running (#161).
  Widget _placeholder(MayosThemeExtension c) => ColoredBox(
        color: c.surfaceSunken,
        child: Center(
          child: Icon(
            Icons.image_outlined,
            size: MayosIconSizes.medium,
            color: c.textDisabled,
          ),
        ),
      );

  Widget _fallback(BuildContext context, MayosThemeExtension c) => ColoredBox(
        color: c.secondarySurface,
        child: Center(
          child: Icon(
            Icons.fitness_center,
            size: MayosIconSizes.large,
            color: c.textMuted,
            semanticLabel: displayCopyOf(context).exerciseMediaUnavailable,
          ),
        ),
      );
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
          Flexible(
            child: Text(
              label,
              style: MayosTypography.of(context)
                  .caption
                  .copyWith(color: foreground),
            ),
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
            label: displayCopyOf(context).setsAndReps,
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: 'RIR ${minRirLabel(exercise.targetRpe)}',
            label: displayCopyOf(context).intensity,
          ),
        ),
        Expanded(
          child: _PrescriptionStat(
            value: '${exercise.restSecondsOrDefault}s',
            label: displayCopyOf(context).rest,
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
          alignment: AlignmentDirectional.centerStart,
          child: Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              value,
              maxLines: 1,
              style:
                  MayosTypography.of(context).numericSmall.copyWith(color: c.textPrimary),
            ),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
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
      if (category.isNotEmpty)
        (displayCopyOf(context).category, titleCase(category)),
      // Body part mirrors category upstream; show it only when it differs.
      if (bodyPart.isNotEmpty && !categoryIsBodyPart)
        (displayCopyOf(context).bodyPart, titleCase(bodyPart)),
      if (detail != null && detail.equipment.isNotEmpty)
        (displayCopyOf(context).equipment, titleCase(detail.equipment)),
      if (detail != null)
        (
          displayCopyOf(context).equipmentCategory,
          displayCopyOf(context).equipmentCategoryLabel(
            detail.equipmentCategory,
          ),
        ),
      if (detail?.loadType != null)
        (
          displayCopyOf(context).loadType,
          displayCopyOf(context).loadTypeLabel(detail!.loadType!),
        ),
      if (ex != null && ex.hasNotes) (displayCopyOf(context).notes, ex.notes),
    ];

    if (rows.isEmpty) {
      return _EmptyTab(
        message: displayCopyOf(context).noExerciseDetails,
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
              style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
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
      return _EmptyTab(
        message: displayCopyOf(context).noInstructionsForExercise,
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
                    style: MayosTypography.of(context).numericSmall.copyWith(
                      color: c.accent,
                      fontSize: 15,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    steps[i],
                    style: MayosTypography.of(context).body.copyWith(color: c.textPrimary),
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
  const _HistoryTab({required this.history, required this.equipment});

  final ExerciseHistory? history;
  final String? equipment;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final WorkoutCopy copy = workoutCopyOf(context);
    final List<ExerciseHistoryPoint> points =
        history?.history ?? const <ExerciseHistoryPoint>[];
    final ExerciseHistoryPoint? latest =
        points.isEmpty ? null : points.last;
    final bool latestZeroLoadUsesEquipmentLabel = latest != null &&
        zeroLoadLabelKind(latest.weightKg, equipment) != null;
    if (points.isEmpty) {
      return _EmptyTab(
        message: displayCopyOf(context).noExerciseHistory,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (history?.caption != null &&
            !latestZeroLoadUsesEquipmentLabel) ...<Widget>[
          Text(
            history!.caption!.replaceAll('**', ''),
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
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
                    textDirection: TextDirection.ltr,
                    style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
                  ),
                ),
                Expanded(
                  child: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      '${formatExerciseWeightWithUnit(
                        point.weightKg,
                        equipment: equipment,
                        languageCode: copy.languageCode,
                        unit: ' kg',
                      )} '
                      '× ${point.reps} @ RIR '
                      '${rirLabel(point.rpe)}',
                      style:
                          MayosTypography.of(context).body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ),
                if (zeroLoadLabelKind(point.weightKg, equipment) == null)
                  Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      'e1RM ${_trim(point.e1rm)}',
                      style: MayosTypography.of(context).caption
                          .copyWith(color: c.textSecondary),
                    ),
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
        style: MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
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
            FilledButton(
                onPressed: onRetry, child: Text(displayCopyOf(context).retry)),
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
