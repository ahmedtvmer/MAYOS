import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/display_language/catalog.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/ui/myos_table_frame.dart';
import '../../router.dart';
import '../player/workout/logger_card_widgets.dart'
    show ExerciseCatalogThumbnail;

void openCoachExerciseDetail(BuildContext context, String exerciseId) {
  context.push(
    '$exerciseDetailPath/${Uri.encodeComponent(exerciseId)}?coach=1&library=1',
  );
}

String? coachCatalogExerciseId(String? exerciseId) {
  if (exerciseId == null ||
      exerciseId.isEmpty ||
      exerciseId.startsWith('coach:')) {
    return null;
  }
  return exerciseId;
}

String coachExerciseEquipmentLabel(
  BuildContext context,
  ProgramExercise exercise,
) {
  final CoachCopy coachCopy = coachCopyOf(context);
  final MyosCopy catalogCopy = displayCopyOf(context);
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

String _machineEquipmentLabel(MyosCopy copy, String? loadType) {
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
  String? muscle,
) {
  final String? normalizedMuscle = muscle?.trim();
  if (normalizedMuscle == null || normalizedMuscle.isEmpty) return null;
  return displayCopyOf(context).primaryMuscleLabel(normalizedMuscle);
}

class CoachExerciseTableFrame extends StatelessWidget {
  const CoachExerciseTableFrame({
    super.key,
    required this.columns,
    required this.child,
    this.decorated = true,
    this.scrollable = true,
  });

  final MyosTableColumns columns;
  final Widget child;
  final bool decorated;
  final bool scrollable;

  @override
  Widget build(BuildContext context) => MyosTableFrame(
        columns: columns,
        child: child,
        decorated: decorated,
        scrollable: scrollable,
      );
}

/// Keeps the catalog image fixed while the exercise name and cue wrap beside it.
class CoachExerciseCell extends StatelessWidget {
  const CoachExerciseCell({
    super.key,
    required this.imagePath,
    required this.name,
    this.muscleLine,
    this.secondaryLine,
    this.exerciseId,
  });

  final String? imagePath;
  final String name;
  final String? muscleLine;
  final String? secondaryLine;
  final String? exerciseId;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    final VoidCallback? onTap = exerciseId == null
        ? null
        : () => openCoachExerciseDetail(context, exerciseId!);
    final Widget title = Text(
      name,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
      style: MyosTypography.of(context)
          .body
          .copyWith(color: colors.textPrimary),
    );
    final Widget content = Row(
      children: <Widget>[
        ExerciseCatalogThumbnail(imagePath: imagePath),
        const SizedBox(width: MyosSpacing.xs),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: <Widget>[
              if (onTap == null)
                title
              else
                Semantics(
                  button: true,
                  label: workoutCopyOf(context).exerciseDetails(name),
                  onTap: onTap,
                  child: title,
                ),
              _CoachExerciseMuscleLine(label: muscleLine),
              if (secondaryLine != null && secondaryLine!.isNotEmpty)
                Text(
                  secondaryLine!,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: MyosTypography.of(context)
                      .caption
                      .copyWith(color: colors.textSecondary),
                ),
            ],
          ),
        ),
      ],
    );
    return onTap == null
        ? content
        : GestureDetector(
            behavior: HitTestBehavior.opaque,
            excludeFromSemantics: true,
            onTap: onTap,
            child: content,
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
      style: MyosTypography.of(context)
          .caption
          .copyWith(color: MyosTheme.of(context).textSecondary),
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
        style: MyosTypography.of(context)
            .bodySecondary
            .copyWith(color: MyosTheme.of(context).textPrimary),
      );
}

enum CoachStatusChipTone { neutral, active, pending }

/// Semantic colors keep each status chip legible in both MYOS themes.
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
    final MyosThemeExtension colors = MyosTheme.of(context);
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
        horizontal: MyosSpacing.sm,
        vertical: MyosSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: toneColors.background,
        borderRadius: MyosRadii.pillRadius,
        border: Border.all(color: toneColors.border),
      ),
      child: Text(
        label,
        style: MyosTypography.of(context)
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
    final MyosThemeExtension colors = MyosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MyosSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ExerciseCatalogThumbnail(imagePath: imagePath),
          const SizedBox(width: MyosSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  name,
                  style: MyosTypography.of(context)
                      .body
                      .copyWith(color: colors.textPrimary),
                ),
                _CoachExerciseMuscleLine(label: muscleLine),
                const SizedBox(height: MyosSpacing.xxs),
                Text(
                  prescription,
                  style: MyosTypography.of(context)
                      .caption
                      .copyWith(color: colors.textSecondary),
                ),
                if (secondaryLine != null && secondaryLine!.isNotEmpty)
                  Text(
                    secondaryLine!,
                    style: MyosTypography.of(context)
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
