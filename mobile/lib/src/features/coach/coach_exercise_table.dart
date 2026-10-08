import 'package:flutter/material.dart';

import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../player/workout/logger_card_widgets.dart'
    show ExerciseCatalogThumbnail;

/// Keeps the catalog image fixed while the exercise name and cue wrap beside it.
class CoachExerciseCell extends StatelessWidget {
  const CoachExerciseCell({
    super.key,
    required this.imagePath,
    required this.name,
    this.secondaryLine,
  });

  final String? imagePath;
  final String name;
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
    this.secondaryLine,
  });

  final String? imagePath;
  final String name;
  final String prescription;
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
