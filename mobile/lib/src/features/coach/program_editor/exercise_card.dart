part of '../coach_program_draft_screen.dart';

enum _ProgramDraftExerciseAction {
  swap,
  insertAbove,
  insertBelow,
  duplicate,
  delete,
}

class _ProgramDraftExerciseCard extends StatelessWidget {
  const _ProgramDraftExerciseCard({
    required this.dayIndex,
    required this.exerciseIndex,
    required this.exercise,
    required this.busy,
    required this.errorFor,
    required this.onChanged,
    required this.onSwap,
    required this.onInsertAbove,
    required this.onInsertBelow,
    required this.onDuplicate,
    required this.onRemove,
  });

  final int dayIndex;
  final int exerciseIndex;
  final _DraftExerciseEditor exercise;
  final bool busy;
  final String? Function(String field) errorFor;
  final ValueChanged<String> onChanged;
  final VoidCallback onSwap;
  final VoidCallback onInsertAbove;
  final VoidCallback onInsertBelow;
  final VoidCallback onDuplicate;
  final VoidCallback onRemove;

  Key _fieldKey(String field) =>
      Key('program_draft_${field}_${dayIndex}_$exerciseIndex');

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        padding: const EdgeInsets.all(MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(exercise.exerciseName,
                      style: MayosTypography.of(context).sectionHeading),
                ),
                ReorderableDragStartListener(
                  index: exerciseIndex,
                  enabled: !busy,
                  child: Tooltip(
                    key: Key(
                      'program_draft_exercise_reorder_${dayIndex}_$exerciseIndex',
                    ),
                    message: copy.reorderExercise,
                    child: const Padding(
                      padding: EdgeInsets.all(MayosSpacing.sm),
                      child: Icon(Icons.drag_handle),
                    ),
                  ),
                ),
                PopupMenuButton<_ProgramDraftExerciseAction>(
                  key: Key(
                    'program_draft_exercise_menu_${dayIndex}_$exerciseIndex',
                  ),
                  tooltip: copy.exerciseActions,
                  enabled: !busy,
                  onSelected: (_ProgramDraftExerciseAction action) {
                    switch (action) {
                      case _ProgramDraftExerciseAction.swap:
                        onSwap();
                      case _ProgramDraftExerciseAction.insertAbove:
                        onInsertAbove();
                      case _ProgramDraftExerciseAction.insertBelow:
                        onInsertBelow();
                      case _ProgramDraftExerciseAction.duplicate:
                        onDuplicate();
                      case _ProgramDraftExerciseAction.delete:
                        onRemove();
                    }
                  },
                  itemBuilder: (BuildContext context) =>
                      <PopupMenuEntry<_ProgramDraftExerciseAction>>[
                    PopupMenuItem<_ProgramDraftExerciseAction>(
                      key: Key(
                        'program_draft_exercise_swap_${dayIndex}_$exerciseIndex',
                      ),
                      value: _ProgramDraftExerciseAction.swap,
                      child: Text(copy.swapExercise),
                    ),
                    PopupMenuItem<_ProgramDraftExerciseAction>(
                      key: Key(
                        'program_draft_exercise_insert_above_${dayIndex}_$exerciseIndex',
                      ),
                      value: _ProgramDraftExerciseAction.insertAbove,
                      child: Text(copy.insertExerciseAbove),
                    ),
                    PopupMenuItem<_ProgramDraftExerciseAction>(
                      key: Key(
                        'program_draft_exercise_insert_below_${dayIndex}_$exerciseIndex',
                      ),
                      value: _ProgramDraftExerciseAction.insertBelow,
                      child: Text(copy.insertExerciseBelow),
                    ),
                    PopupMenuItem<_ProgramDraftExerciseAction>(
                      key: Key(
                        'program_draft_exercise_duplicate_${dayIndex}_$exerciseIndex',
                      ),
                      value: _ProgramDraftExerciseAction.duplicate,
                      child: Text(copy.duplicateExerciseAction),
                    ),
                    PopupMenuItem<_ProgramDraftExerciseAction>(
                      key: Key(
                        'program_draft_remove_${dayIndex}_$exerciseIndex',
                      ),
                      value: _ProgramDraftExerciseAction.delete,
                      child: Text(
                        copy.deleteExercise,
                        style: TextStyle(color: colors.danger),
                      ),
                    ),
                  ],
                  icon: const Icon(Icons.more_vert),
                ),
              ],
            ),
            _editorErrorText(context, errorFor('exercise_id'), colors),
            Row(
              children: <Widget>[
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('sets'),
                    controller: exercise.sets,
                    label: copy.workingSets,
                    enabled: !busy,
                    errorText: errorFor('target_sets'),
                    onChanged: (_) => onChanged('target_sets'),
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('reps'),
                    controller: exercise.reps,
                    label: copy.repsOrRange,
                    enabled: !busy,
                    allowRange: true,
                    errorText: errorFor('target_reps_min') ??
                        errorFor('target_reps_max'),
                    onChanged: (_) {
                      onChanged('target_reps_min');
                      onChanged('target_reps_max');
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.sm),
            SizedBox(
              width: 180,
              child: _editorNumberField(
                key: _fieldKey('rir'),
                controller: exercise.rir,
                label: copy.targetRir,
                enabled: !busy,
                decimal: true,
                errorText: errorFor('target_rir') ?? errorFor('target_rpe'),
                onChanged: (_) {
                  onChanged('target_rir');
                  onChanged('target_rpe');
                },
              ),
            ),
            const SizedBox(height: MayosSpacing.sm),
            Row(
              children: <Widget>[
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('warmup_sets'),
                    controller: exercise.warmupSets,
                    label: copy.rampedWarmupSets,
                    enabled: !busy,
                    errorText: errorFor('warmup_sets'),
                    onChanged: (_) => onChanged('warmup_sets'),
                  ),
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: _editorNumberField(
                    key: _fieldKey('rest'),
                    controller: exercise.rest,
                    label: copy.restSeconds,
                    enabled: !busy,
                    errorText: errorFor('rest_seconds'),
                    onChanged: (_) => onChanged('rest_seconds'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            TextField(
              key: _fieldKey('tempo'),
              controller: exercise.tempo,
              enabled: !busy,
              maxLength: ProgramDraftPrescription.maxTempoLength,
              inputFormatters: <TextInputFormatter>[
                LengthLimitingTextInputFormatter(
                  ProgramDraftPrescription.maxTempoLength,
                ),
              ],
              decoration: InputDecoration(
                labelText: copy.tempo,
                border: const OutlineInputBorder(),
                isDense: true,
                errorText: errorFor('tempo'),
                counterText: '',
              ),
              onChanged: (_) => onChanged('tempo'),
            ),
            const SizedBox(height: MayosSpacing.xs),
            TextField(
              key: _fieldKey('notes'),
              controller: exercise.notes,
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
                labelText: copy.notesOptional,
                border: const OutlineInputBorder(),
                errorText: errorFor('notes'),
                counterText: '',
              ),
              onChanged: (_) => onChanged('notes'),
            ),
          ],
        ),
      ),
    );
  }
}
