import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/effort.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_button.dart';
import 'coach_exercise_table.dart';

class CoachProgramView extends StatefulWidget {
  const CoachProgramView({
    super.key,
    required this.active,
    required this.program,
  });

  final CoachActiveProgram active;
  final TrainingProgram program;

  @override
  State<CoachProgramView> createState() => _CoachProgramViewState();
}

class _CoachProgramViewState extends State<CoachProgramView> {
  static const int _collapsedExerciseCount = 8;
  static const List<double> _columnWidths = <double>[
    40,
    330,
    150,
    125,
    90,
    95,
    80,
    80
  ];

  int _selectedDayIndex = 0;
  bool _showAllExercises = false;

  @override
  void didUpdateWidget(covariant CoachProgramView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.program.version != widget.program.version ||
        oldWidget.program.days.length != widget.program.days.length) {
      _selectedDayIndex = 0;
      _showAllExercises = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final int selectedIndex = widget.program.days.isEmpty
        ? 0
        : _selectedDayIndex.clamp(0, widget.program.days.length - 1).toInt();
    final ProgramDay? selectedDay =
        widget.program.days.isEmpty ? null : widget.program.days[selectedIndex];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        _summaryHeader(context, copy),
        if (widget.program.days.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          _dayTabs(context, selectedIndex),
          const SizedBox(height: MayosSpacing.sm),
          if (selectedDay != null) _selectedDay(context, copy, selectedDay),
        ],
      ],
    );
  }

  Widget _summaryHeader(BuildContext context, CoachCopy copy) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _programTitle(context, copy),
          const SizedBox(height: MayosSpacing.xs),
          _programFacts(context, copy),
          const SizedBox(height: MayosSpacing.md),
          _programStats(context, copy),
        ],
      );

  Widget _programTitle(BuildContext context, CoachCopy copy) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final TrainingProgram program = widget.program;
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: MayosSpacing.xs,
      runSpacing: MayosSpacing.xs,
      children: <Widget>[
        Text(
          program.programName,
          style: MayosTypography.of(context)
              .sectionHeading
              .copyWith(color: colors.textPrimary),
        ),
        if (program.version != null)
          CoachStatusChip(label: copy.programVersionChip(program.version!)),
        CoachStatusChip(
          label: copy.activeProgramStatus,
          tone: CoachStatusChipTone.active,
        ),
        if (widget.active.hasDraft)
          CoachStatusChip(
            key: const Key('coach_program_pending_draft'),
            label: copy.pendingProgramDraft,
            tone: CoachStatusChipTone.pending,
          ),
      ],
    );
  }

  Widget _programFacts(BuildContext context, CoachCopy copy) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final String provenance = widget.active.provenance == 'coach'
        ? copy.publishedByYou
        : copy.generatedAutomatically;
    final String? activeDate = widget.active.activeSince?.split('T').first;
    return Wrap(
      spacing: MayosSpacing.xs,
      runSpacing: MayosSpacing.xxs,
      children: <Widget>[
        _factText(context, colors, provenance),
        if (activeDate != null)
          _factText(context, colors, copy.activeProgramSince(activeDate)),
        if (widget.active.editedByPlayer)
          _factText(context, colors, copy.editedByPlayer),
      ],
    );
  }

  Widget _factText(
    BuildContext context,
    MayosThemeExtension colors,
    String factText,
  ) =>
      Text(
        factText,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: colors.textSecondary),
      );

  Widget _programStats(BuildContext context, CoachCopy copy) {
    final List<ProgramExercise> exercises = <ProgramExercise>[
      for (final ProgramDay day in widget.program.days) ...day.exercises,
    ];
    return Row(
      children: <Widget>[
        Expanded(
          child: _stat(context, copy, (
            key: 'coach_program_stat_training_days',
            count: widget.program.days.length,
            label: copy.trainingDaysSummary,
          )),
        ),
        Expanded(
          child: _stat(context, copy, (
            key: 'coach_program_stat_total_exercises',
            count: exercises.length,
            label: copy.totalExercisesSummary,
          )),
        ),
        Expanded(
          child: _stat(context, copy, (
            key: 'coach_program_stat_working_sets',
            count: _workingSetCount(exercises),
            label: copy.workingSetsSummary,
          )),
        ),
      ],
    );
  }

  int _workingSetCount(Iterable<ProgramExercise> exercises) =>
      exercises.fold<int>(
        0,
        (int total, ProgramExercise exercise) => total + exercise.targetSets,
      );

  Widget _stat(
    BuildContext context,
    CoachCopy copy,
    ({String key, int count, String label}) stat,
  ) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Semantics(
      key: Key(stat.key),
      label: copy.programStatSemantics(stat.count, stat.label),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '${stat.count}',
            style: MayosTypography.of(context)
                .sectionHeading
                .copyWith(color: colors.textPrimary),
          ),
          Text(
            stat.label,
            maxLines: 2,
            style: MayosTypography.of(context)
                .caption
                .copyWith(color: colors.textSecondary),
          ),
        ],
      ),
    );
  }

  Widget _dayTabs(BuildContext context, int selectedIndex) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: <Widget>[
            for (int index = 0; index < widget.program.days.length; index++)
              Padding(
                padding: const EdgeInsetsDirectional.only(end: MayosSpacing.xs),
                child: ChoiceChip(
                  key: Key('coach_program_day_tab_$index'),
                  label: Text(widget.program.days[index].dayName),
                  selected: index == selectedIndex,
                  onSelected: (_) => setState(() {
                    _selectedDayIndex = index;
                    _showAllExercises = false;
                  }),
                ),
              ),
          ],
        ),
      );

  Widget _selectedDay(
    BuildContext context,
    CoachCopy copy,
    ProgramDay day,
  ) {
    return Container(
      padding: const EdgeInsets.all(MayosSpacing.md),
      decoration: _daySectionDecoration(context),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _dayHeading(context, copy, day),
          const SizedBox(height: MayosSpacing.sm),
          _dayExerciseRows(context, copy, day),
        ],
      ),
    );
  }

  BoxDecoration _daySectionDecoration(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return BoxDecoration(
      color: colors.surface,
      borderRadius: MayosRadii.mediumRadius,
      border: Border.all(color: colors.border),
    );
  }

  Widget _dayHeading(BuildContext context, CoachCopy copy, ProgramDay day) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          day.dayName,
          style: MayosTypography.of(context)
              .sectionHeading
              .copyWith(color: colors.textPrimary),
        ),
        const SizedBox(height: MayosSpacing.xxs),
        Text(
          copy.programDaySummary(
            day.exercises.length,
            _workingSetCount(day.exercises),
          ),
          style: MayosTypography.of(context)
              .bodySecondary
              .copyWith(color: colors.textSecondary),
        ),
      ],
    );
  }

  Widget _dayExerciseRows(
    BuildContext context,
    CoachCopy copy,
    ProgramDay day,
  ) {
    final int shownCount = _shownExerciseCount(day);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        if (isDesktopLayout(context))
          _desktopExerciseTable(context, copy, day, shownCount)
        else
          _phoneExerciseRows(context, copy, day, shownCount),
        if (!_showAllExercises &&
            day.exercises.length > _collapsedExerciseCount &&
            day.exercises.length - shownCount > 0)
          _showRemainingButton(
            context,
            copy,
            day.exercises.length - shownCount,
          ),
      ],
    );
  }

  int _shownExerciseCount(ProgramDay day) =>
      !_showAllExercises && day.exercises.length > _collapsedExerciseCount
          ? _collapsedExerciseCount
          : day.exercises.length;

  Widget _desktopExerciseTable(
    BuildContext context,
    CoachCopy copy,
    ProgramDay day,
    int shownCount,
  ) =>
      CoachExerciseTableFrame(
        widths: _columnWidths,
        child: Column(
          children: <Widget>[
            CoachExerciseTableHeader(
              labels: _tableLabels(copy),
              widths: _columnWidths,
              alignments: <TextAlign>[
                TextAlign.center,
                TextAlign.start,
                TextAlign.start,
                TextAlign.start,
                TextAlign.start,
                TextAlign.start,
                TextAlign.start,
                TextAlign.start,
              ],
            ),
            _desktopExerciseRows(context, copy, day, shownCount),
          ],
        ),
      );

  List<String> _tableLabels(CoachCopy copy) => <String>[
        copy.programNumberColumn,
        copy.programExerciseColumn,
        copy.programActionColumn,
        copy.programEquipmentColumn,
        copy.programSetsColumn,
        copy.programRepsColumn,
        copy.programRirColumn,
        copy.programRestColumn,
      ];

  Widget _desktopExerciseRows(
    BuildContext context,
    CoachCopy copy,
    ProgramDay day,
    int shownCount,
  ) =>
      Column(
        children: <Widget>[
          for (int index = 0; index < shownCount; index++)
            _desktopExerciseRow(context, copy, day.exercises[index], index),
        ],
      );

  Widget _desktopExerciseRow(
    BuildContext context,
    CoachCopy copy,
    ProgramExercise exercise,
    int index,
  ) =>
      CoachExerciseTableRow(
        widths: _columnWidths,
        cells: <Widget>[
          Text('${index + 1}', textAlign: TextAlign.center),
          CoachExerciseCell(
            imagePath: exercise.imagePath,
            name: exercise.exerciseName,
            muscleLine: coachExerciseMuscleLabel(
              context,
              exercise.primaryMuscle ??
                  (exercise.isCoachExercise ? exercise.bodyPart : null),
            ),
            secondaryLine: _secondaryLine(copy, exercise),
          ),
          CoachExerciseActionCell(primaryAction: exercise.primaryAction),
          for (final String cellText in
              _programTableValues(context, copy, exercise))
            _tableValue(context, cellText),
        ],
      );

  List<String> _programTableValues(
    BuildContext context,
    CoachCopy copy,
    ProgramExercise exercise,
  ) =>
      <String>[
        coachExerciseEquipmentLabel(context, exercise),
        copy.programSetsCell(exercise.targetSets, exercise.warmupSets),
        copy.programExerciseRepRange(
          exercise.targetRepsMin,
          exercise.targetRepsMax,
        ),
        copy.programRirCell(minRirLabel(exercise.targetRpe)),
        displayCopyOf(context).restTime(exercise.restSecondsOrDefault),
      ];

  Widget _tableValue(BuildContext context, String cellText) => Text(
        cellText,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: MayosTypography.of(context)
            .bodySecondary
            .copyWith(color: MayosTheme.of(context).textPrimary),
      );

  Widget _phoneExerciseRows(
    BuildContext context,
    CoachCopy copy,
    ProgramDay day,
    int shownCount,
  ) =>
      Column(
        children: <Widget>[
          for (int index = 0; index < shownCount; index++) ...<Widget>[
            if (index > 0) const Divider(height: 1),
            _phoneExerciseRow(context, copy, day.exercises[index]),
          ],
        ],
      );

  Widget _phoneExerciseRow(
    BuildContext context,
    CoachCopy copy,
    ProgramExercise exercise,
  ) =>
      CoachCompactExerciseRow(
        imagePath: exercise.imagePath,
        name: exercise.exerciseName,
        muscleLine: coachExerciseMuscleLabel(
          context,
          exercise.primaryMuscle ??
              (exercise.isCoachExercise ? exercise.bodyPart : null),
        ),
        prescription: _compactPrescription(copy, exercise),
        secondaryLine: _phoneSecondaryLine(context, copy, exercise),
      );

  String _compactPrescription(CoachCopy copy, ProgramExercise exercise) =>
      copy.compactProgramPrescription((
        sets: copy.programSetsCell(exercise.targetSets, exercise.warmupSets),
        reps: copy.programExerciseRepRange(
          exercise.targetRepsMin,
          exercise.targetRepsMax,
        ),
        rir: copy.programRirCell(minRirLabel(exercise.targetRpe)),
        rest: displayCopyOf(context).restTime(exercise.restSecondsOrDefault),
        equipment: coachExerciseEquipmentLabel(context, exercise),
      ));

  String _phoneSecondaryLine(
    BuildContext context,
    CoachCopy copy,
    ProgramExercise exercise,
  ) {
    final String secondaryLine = _secondaryLine(copy, exercise);
    final String actionLine =
        coachExerciseActionDetailLine(context, exercise.primaryAction);
    return secondaryLine.isEmpty
        ? actionLine
        : '$actionLine${copy.programDetailSeparator}$secondaryLine';
  }

  String _secondaryLine(CoachCopy copy, ProgramExercise exercise) {
    final List<String> details = <String>[
      if (exercise.tempo != null && exercise.tempo!.isNotEmpty)
        copy.programTempo(exercise.tempo!),
      if (exercise.notes != null && exercise.notes!.isNotEmpty)
        copy.programNotes(exercise.notes!),
    ];
    return details.join(copy.programDetailSeparator);
  }

  Widget _showRemainingButton(
    BuildContext context,
    CoachCopy copy,
    int remaining,
  ) =>
      MayosButton(
        key: const Key('coach_program_show_remaining'),
        label: copy.showRemainingProgramExercises(remaining),
        icon: Icons.expand_more,
        variant: MayosButtonVariant.tertiary,
        expand: true,
        onPressed: () => setState(() => _showAllExercises = true),
      );
}
