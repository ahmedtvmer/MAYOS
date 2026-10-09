part of '../coach_program_draft_screen.dart';

class _ProgramDraftDayCard extends StatelessWidget {
  const _ProgramDraftDayCard({
    required this.index,
    required this.dayCount,
    required this.day,
    required this.busy,
    required this.dayNameError,
    required this.cardioError,
    required this.dayError,
    required this.buildWarmupCard,
    required this.buildExerciseCard,
    required this.onReorderExercises,
    required this.onChanged,
    required this.onMove,
    required this.onDuplicate,
    required this.onRemove,
    required this.onAddWarmup,
    required this.onAddExercise,
  });

  final int index;
  final int dayCount;
  final _DraftDayEditor day;
  final bool busy;
  final String? dayNameError;
  final String? cardioError;
  final String? dayError;
  final Widget Function(int movementIndex) buildWarmupCard;
  final Widget Function(int exerciseIndex) buildExerciseCard;
  final void Function(int oldIndex, int newIndex) onReorderExercises;
  final ValueChanged<String> onChanged;
  final ValueChanged<int> onMove;
  final VoidCallback onDuplicate;
  final VoidCallback onRemove;
  final VoidCallback onAddWarmup;
  final VoidCallback onAddExercise;

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    copy.trainingDayNumber(index + 1),
                    style: MayosTypography.of(context).sectionHeading,
                  ),
                ),
                IconButton(
                  key: Key('program_draft_day_up_$index'),
                  tooltip: copy.moveDayUp,
                  onPressed: busy || index == 0 ? null : () => onMove(-1),
                  icon: const Icon(Icons.arrow_upward),
                ),
                IconButton(
                  key: Key('program_draft_day_down_$index'),
                  tooltip: copy.moveDayDown,
                  onPressed: busy || index == dayCount - 1
                      ? null
                      : () => onMove(1),
                  icon: const Icon(Icons.arrow_downward),
                ),
                IconButton(
                  key: Key('program_draft_day_duplicate_$index'),
                  tooltip: copy.duplicateDay,
                  onPressed: busy || dayCount >= ProgramDraftPrescription.maxDays
                      ? null
                      : onDuplicate,
                  icon: const Icon(Icons.copy_outlined),
                ),
                IconButton(
                  key: Key('program_draft_day_remove_$index'),
                  tooltip: copy.removeDay,
                  onPressed: busy ? null : onRemove,
                  icon: Icon(Icons.delete_outline, color: colors.danger),
                ),
              ],
            ),
            TextField(
              key: Key('program_draft_day_name_$index'),
              controller: day.dayName,
              enabled: !busy,
              decoration: InputDecoration(
                labelText: copy.dayName,
                border: const OutlineInputBorder(),
                errorText: dayNameError,
              ),
              onChanged: (_) => onChanged('day_name'),
            ),
            if (dayError != null) _editorErrorText(context, dayError!, colors),
            const SizedBox(height: MayosSpacing.md),
            Text(workoutCopyOf(context).warmup,
                style: MayosTypography.of(context).sectionHeading),
            const SizedBox(height: MayosSpacing.xs),
            for (int movementIndex = 0;
                movementIndex < day.warmups.length;
                movementIndex++)
              buildWarmupCard(movementIndex),
            MayosButton(
              key: Key('program_draft_warmup_add_$index'),
              label: copy.addWarmupMovement,
              icon: Icons.add,
              variant: MayosButtonVariant.tertiary,
              onPressed: busy ? null : onAddWarmup,
            ),
            const SizedBox(height: MayosSpacing.md),
            Text(
              copy.workingSets,
              style: MayosTypography.of(context).sectionHeading,
            ),
            const SizedBox(height: MayosSpacing.xs),
            ReorderableListView.builder(
              buildDefaultDragHandles: false,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: day.exercises.length,
              onReorderItem: onReorderExercises,
              itemBuilder: (BuildContext context, int exerciseIndex) =>
                  KeyedSubtree(
                key: ObjectKey(day.exercises[exerciseIndex]),
                child: buildExerciseCard(exerciseIndex),
              ),
            ),
            MayosButton(
              key: Key('program_draft_add_exercise_$index'),
              label: copy.addExercise,
              icon: Icons.add,
              variant: MayosButtonVariant.secondary,
              onPressed: busy ? null : onAddExercise,
            ),
            const SizedBox(height: MayosSpacing.md),
            TextField(
              key: Key('program_draft_cardio_$index'),
              controller: day.cardio,
              enabled: !busy,
              minLines: 1,
              maxLines: 3,
              maxLength: ProgramDraftPrescription.maxProgramNotesLength,
              inputFormatters: <TextInputFormatter>[
                LengthLimitingTextInputFormatter(
                  ProgramDraftPrescription.maxProgramNotesLength,
                ),
              ],
              decoration: InputDecoration(
                labelText: copy.cardioNote,
                border: const OutlineInputBorder(),
                errorText: cardioError,
                counterText: '',
              ),
              onChanged: (_) => onChanged('cardio'),
            ),
          ],
        ),
      ),
    );
  }
}
