import 'package:flutter/material.dart';

import '../../core/display_language/catalog.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../player/workout/logger_card_widgets.dart'
    show ExerciseCatalogThumbnail;

String coachExerciseEquipmentLabel(
  BuildContext context,
  ProgramExercise exercise,
) {
  final CoachCopy coachCopy = coachCopyOf(context);
  final MayosCopy catalogCopy = displayCopyOf(context);
  final String? coachEquipment = exercise.coachEquipment;
  if (coachEquipment != null && coachEquipment.isNotEmpty) {
    return coachCopy.programEquipmentValue(coachEquipment);
  }
  return switch (exercise.equipmentCategory) {
    'Machine' => _machineEquipmentLabel(catalogCopy, exercise.loadType),
    'Free weight' => _freeWeightEquipmentLabel(coachCopy, exercise.equipment),
    'Cable' || 'Bodyweight' || 'Band' || 'Other' =>
      catalogCopy.equipmentCategoryLabel(exercise.equipmentCategory!),
    _ => coachCopy.programEquipmentValue(
        exercise.equipment ?? coachCopy.missingProgramEquipment,
      ),
  };
}

String _machineEquipmentLabel(MayosCopy copy, String? loadType) {
  if (loadType == 'selectorized' || loadType == 'plate_loaded') {
    return copy.loadTypeLabel(loadType!);
  }
  return copy.equipmentCategoryLabel('Machine');
}

String _freeWeightEquipmentLabel(CoachCopy copy, String? equipment) {
  final String label = equipment == null
      ? copy.missingProgramEquipment
      : _titleCaseEquipment(equipment);
  return copy.programEquipmentValue(label);
}

String _titleCaseEquipment(String equipment) => equipment.replaceAllMapped(
      RegExp(r'[A-Za-z]+'),
      (Match match) {
        final String word = match.group(0)!;
        return '${word[0].toUpperCase()}${word.substring(1).toLowerCase()}';
      },
    );

String coachExerciseActionLabel(BuildContext context, String? primaryAction) {
  final String? action = primaryAction?.trim();
  if (action == null || action.isEmpty) {
    return coachCopyOf(context).missingProgramEquipment;
  }
  return displayCopyOf(context).primaryActionLabel(action);
}

String coachExerciseActionDetailLine(
  BuildContext context,
  String? primaryAction,
) =>
    coachCopyOf(context).programActionDetail(
      coachExerciseActionLabel(context, primaryAction),
    );

String? coachExerciseMuscleLabel(
  BuildContext context,
  ProgramExercise exercise,
) {
  final String? muscle = exercise.primaryMuscle ??
      (exercise.isCoachExercise ? exercise.bodyPart : null);
  final String? normalizedMuscle = muscle?.trim();
  if (normalizedMuscle == null || normalizedMuscle.isEmpty) return null;
  return displayCopyOf(context).primaryMuscleLabel(normalizedMuscle);
}

/// Keeps the catalog image fixed while the exercise name and cue wrap beside it.
class CoachExerciseCell extends StatelessWidget {
  const CoachExerciseCell({
    super.key,
    required this.imagePath,
    required this.name,
    this.muscleLine,
    this.secondaryLine,
  });

  final String? imagePath;
  final String name;
  final String? muscleLine;
  final String? secondaryLine;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Row(
      children: <Widget>[
        ExerciseCatalogThumbnail(imagePath: imagePath),
        const SizedBox(width: MayosSpacing.xs),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: <Widget>[
              Text(
                name,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: MayosTypography.of(context)
                    .body
                    .copyWith(color: colors.textPrimary),
              ),
              _CoachExerciseMuscleLine(label: muscleLine),
              if (secondaryLine != null && secondaryLine!.isNotEmpty)
                Text(
                  secondaryLine!,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: MayosTypography.of(context)
                      .caption
                      .copyWith(color: colors.textSecondary),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CoachExerciseMuscleLine extends StatelessWidget {
  const _CoachExerciseMuscleLine({required this.label});

  final String? label;

  @override
  Widget build(BuildContext context) {
    if (label == null || label!.isEmpty) return const SizedBox.shrink();
    return Text(
      label!,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
      style: MayosTypography.of(context)
          .caption
          .copyWith(color: MayosTheme.of(context).textSecondary),
    );
  }
}

class CoachExerciseActionCell extends StatelessWidget {
  const CoachExerciseActionCell({
    super.key,
    required this.primaryAction,
  });

  final String? primaryAction;

  @override
  Widget build(BuildContext context) => Text(
        coachExerciseActionLabel(context, primaryAction),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: MayosTheme.of(context).textPrimary),
      );
}

/// Matching column widths keep the header labels aligned with each exercise row.
class CoachExerciseTableHeader extends StatelessWidget {
  const CoachExerciseTableHeader({
    super.key,
    required this.labels,
    required this.widths,
    required this.alignments,
  })  : assert(labels.length == widths.length),
        assert(labels.length == alignments.length);

  final List<String> labels;
  final List<double> widths;
  final List<TextAlign> alignments;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.xs,
        vertical: MayosSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceSunken,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: <Widget>[
          for (int index = 0; index < labels.length; index++)
            SizedBox(
              width: widths[index],
              child: Text(
                labels[index],
                textAlign: alignments[index],
                style: MayosTypography.of(context)
                    .captionStrong
                    .copyWith(color: colors.textMuted),
              ),
            ),
        ],
      ),
    );
  }
}

/// Shared row padding and separators keep each table easy to scan.
class CoachExerciseTableRow extends StatelessWidget {
  const CoachExerciseTableRow({
    super.key,
    required this.cells,
    required this.widths,
  }) : assert(cells.length == widths.length);

  final List<Widget> cells;
  final List<double> widths;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.xs,
        vertical: MayosSpacing.xxs,
      ),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: <Widget>[
          for (int index = 0; index < cells.length; index++)
            SizedBox(width: widths[index], child: cells[index]),
        ],
      ),
    );
  }
}

enum CoachStatusChipTone { neutral, active, pending }

/// Semantic colors keep each status chip legible in both MAYOS themes.
class CoachStatusChip extends StatelessWidget {
  const CoachStatusChip({
    super.key,
    required this.label,
    this.tone = CoachStatusChipTone.neutral,
  });

  final String label;
  final CoachStatusChipTone tone;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final ({Color foreground, Color background, Color border}) toneColors =
        switch (tone) {
      CoachStatusChipTone.neutral => (
          foreground: colors.textSecondary,
          background: colors.surfaceSunken,
          border: colors.border,
        ),
      CoachStatusChipTone.active => (
          foreground: colors.success,
          background: colors.successTint,
          border: colors.success,
        ),
      CoachStatusChipTone.pending => (
          foreground: colors.warning,
          background: colors.accentSubtle,
          border: colors.warning,
        ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.sm,
        vertical: MayosSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: toneColors.background,
        borderRadius: MayosRadii.pillRadius,
        border: Border.all(color: toneColors.border),
      ),
      child: Text(
        label,
        style: MayosTypography.of(context)
            .captionStrong
            .copyWith(color: toneColors.foreground),
      ),
    );
  }
}

/// The fixed thumbnail leaves the remaining phone width for prescriptions to wrap.
class CoachCompactExerciseRow extends StatelessWidget {
  const CoachCompactExerciseRow({
    super.key,
    required this.imagePath,
    required this.name,
    required this.prescription,
    this.muscleLine,
    this.secondaryLine,
  });

  final String? imagePath;
  final String name;
  final String prescription;
  final String? muscleLine;
  final String? secondaryLine;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ExerciseCatalogThumbnail(imagePath: imagePath),
          const SizedBox(width: MayosSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  name,
                  style: MayosTypography.of(context)
                      .body
                      .copyWith(color: colors.textPrimary),
                ),
                _CoachExerciseMuscleLine(label: muscleLine),
                const SizedBox(height: MayosSpacing.xxs),
                Text(
                  prescription,
                  style: MayosTypography.of(context)
                      .caption
                      .copyWith(color: colors.textSecondary),
                ),
                if (secondaryLine != null && secondaryLine!.isNotEmpty)
                  Text(
                    secondaryLine!,
                    style: MayosTypography.of(context)
                        .caption
                        .copyWith(color: colors.textMuted),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
