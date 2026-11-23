import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../exercise_picker_dialog.dart';

/// What the Program tab reports back after trying to save the edited day.
class ProgramDaySaveOutcome {
  /// The day was saved, or the program must reload: close the dialog.
  const ProgramDaySaveOutcome.close()
      : closeDialog = true,
        error = null;

  /// Nothing was saved: keep the dialog and the Player's edits open (#787).
  const ProgramDaySaveOutcome.keepEditing([this.error]) : closeDialog = false;

  final bool closeDialog;
  final String? error;
}

typedef ProgramDaySave = Future<ProgramDaySaveOutcome> Function(
  List<ProgramEditExerciseEntry> exercises,
);

class ProgramDayEditDialog extends StatefulWidget {
  const ProgramDayEditDialog({
    super.key,
    required this.day,
    required this.onSave,
  });

  final ProgramDay day;

  /// Saves the edited day; the dialog stays open unless the outcome closes it.
  final ProgramDaySave onSave;

  static Future<void> show(
    BuildContext context,
    ProgramDay day, {
    required ProgramDaySave onSave,
  }) =>
      showDialog<void>(
        context: context,
        builder: (BuildContext context) =>
            ProgramDayEditDialog(day: day, onSave: onSave),
      );

  @override
  State<ProgramDayEditDialog> createState() => _ProgramDayEditDialogState();
}

class _ProgramDayEditDialogState extends State<ProgramDayEditDialog> {
  bool _saving = false;
  String? _saveError;

  late final List<ProgramEditExerciseEntry> _exercises =
      <ProgramEditExerciseEntry>[
    for (final (int index, ProgramExercise exercise)
        in widget.day.exercises.indexed)
      ProgramEditExerciseEntry(
        sourceIndex: index,
        exercise: exercise,
        prescribedSets: exercise.workingSetCount,
        maximumSets: math.max(4, exercise.workingSetCount),
      ),
  ];

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    return AlertDialog(
      title: Text(copy.editDay),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (_saveError != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                _saveError!,
                key: const Key('program_edit_save_error'),
                style: MayosTypography.of(context).bodySecondary.copyWith(
                      color: MayosTheme.of(context).danger,
                    ),
              ),
            ),
          _exerciseList(context),
        ],
      ),
      actions: _actions(copy),
    );
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _saveError = null;
    });
    final ProgramDaySaveOutcome outcome =
        await widget.onSave(_exercises.toList());
    if (!mounted) return;
    if (outcome.closeDialog) {
      Navigator.of(context).pop();
      return;
    }
    setState(() {
      _saving = false;
      _saveError = outcome.error;
    });
  }

  Widget _exerciseList(BuildContext context) {
    final Size screenSize = MediaQuery.sizeOf(context);
    final double listHeight = math.min(
      screenSize.height * 0.55,
      _exercises.length * 104.0,
    );
    return SizedBox(
      width: math.min(420.0, screenSize.width - 80),
      height: listHeight,
      child: ReorderableListView.builder(
        buildDefaultDragHandles: false,
        onReorderItem: _reorderExercise,
        itemCount: _exercises.length,
        itemBuilder: (BuildContext context, int index) =>
            _exerciseRow(context, index),
      ),
    );
  }

  Widget _exerciseRow(BuildContext context, int index) {
    final ProgramEditExerciseEntry entry = _exercises[index];
    final ProgramExercise exercise = entry.exercise;
    return Column(
      key: ObjectKey(entry),
      children: <Widget>[
        Row(
          children: <Widget>[
            _reorderHandle(context, entry, index),
            Expanded(child: Text(exercise.exerciseName)),
            _removeButton(context, entry),
          ],
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: <Widget>[
            _decreaseSetButton(context, entry),
            _setCount(context, entry),
            _increaseSetButton(context, entry),
          ],
        ),
        if (index < _exercises.length - 1) const Divider(height: 1),
      ],
    );
  }

  Widget _reorderHandle(
    BuildContext context,
    ProgramEditExerciseEntry entry,
    int index,
  ) =>
      Semantics(
        container: true,
        label: displayCopyOf(context).reorderProgramExercise(
              entry.exercise.exerciseName,
            ),
        child: ReorderableDragStartListener(
          index: index,
          child: const SizedBox(
            width: 48,
            height: 48,
            child: Icon(Icons.drag_handle),
          ),
        ),
      );

  Widget _decreaseSetButton(
    BuildContext context,
    ProgramEditExerciseEntry entry,
  ) {
    final ProgramExercise exercise = entry.exercise;
    final MayosCopy copy = displayCopyOf(context);
    return IconButton(
      key: Key('program_edit_decrease_${entry.sourceIndex}'),
      tooltip: copy.decreaseProgramExerciseSets(exercise.exerciseName),
      // Any exercise can go down to one set; no row is locked (#824).
      onPressed: entry.prescribedSets <= 1
          ? null
          : () => _changeSetCount(entry, entry.prescribedSets - 1),
      icon: const Icon(Icons.remove),
    );
  }

  Widget _setCount(BuildContext context, ProgramEditExerciseEntry entry) {
    final ProgramExercise exercise = entry.exercise;
    final MayosCopy copy = displayCopyOf(context);
    return Semantics(
      container: true,
      label: copy.programExerciseSetCount(
        exercise.exerciseName,
        entry.prescribedSets,
      ),
      child: ExcludeSemantics(
        child: SizedBox(
          width: 20,
          child: Text(
            '${entry.prescribedSets}',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }

  Widget _increaseSetButton(
    BuildContext context,
    ProgramEditExerciseEntry entry,
  ) {
    final MayosCopy copy = displayCopyOf(context);
    final ProgramExercise exercise = entry.exercise;
    return IconButton(
      key: Key('program_edit_increase_${entry.sourceIndex}'),
      tooltip: copy.increaseProgramExerciseSets(exercise.exerciseName),
      onPressed: entry.prescribedSets >= entry.maximumSets
          ? null
          : () => _changeSetCount(entry, entry.prescribedSets + 1),
      icon: const Icon(Icons.add),
    );
  }

  Widget _removeButton(BuildContext context, ProgramEditExerciseEntry entry) {
    final MayosCopy copy = displayCopyOf(context);
    final ProgramExercise exercise = entry.exercise;
    return IconButton(
      tooltip: copy.removeExerciseNamed(exercise.exerciseName),
      onPressed: _exercises.length == 1
          ? null
          : () => setState(() => _exercises.removeWhere(
                (ProgramEditExerciseEntry pending) => identical(pending, entry),
              )),
      icon: const Icon(Icons.remove_circle_outline),
    );
  }

  void _changeSetCount(ProgramEditExerciseEntry entry, int targetSets) {
    setState(() {
      final int index = _exercises.indexWhere(
        (ProgramEditExerciseEntry pending) => identical(pending, entry),
      );
      _exercises[index] = entry.copyWith(
        exercise: entry.exercise.copyWith(targetSets: targetSets),
        prescribedSets: targetSets,
      );
    });
  }

  void _reorderExercise(int oldIndex, int newIndex) {
    setState(() {
      final ProgramEditExerciseEntry entry = _exercises.removeAt(oldIndex);
      _exercises.insert(newIndex, entry);
    });
  }

  List<Widget> _actions(MayosCopy copy) => <Widget>[
        TextButton(
          onPressed: _exercises.length >= 10 ? null : _addExercise,
          child: Text(copy.addProgramExercise),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(copy.cancel),
        ),
        FilledButton(
          key: const Key('program_edit_save_button'),
          onPressed: _saving ? null : _save,
          child: Text(copy.save),
        ),
      ];

  Future<void> _addExercise() async {
    final selection = await ExercisePickerDialog.show(
      context,
      excludeExerciseIds: _exercises.map((item) => item.exercise.exerciseId).toSet(),
    );
    if (selection == null || !mounted) return;
    final entry = selection.$1;
    final ProgramExercise exercise = ProgramExercise(
      exerciseId: entry.id,
      exerciseName: entry.name,
      targetSets: 2,
      targetRepsMin: 8,
      targetRepsMax: 12,
      targetRpe: 8,
      equipment: entry.equipment,
      primaryMuscle: entry.primaryMuscle,
      primaryAction: entry.primaryAction,
      equipmentCategory: entry.equipmentCategory,
    );
    setState(() => _exercises.add(ProgramEditExerciseEntry(
      sourceIndex: -_exercises.length - 1,
      exercise: exercise,
      prescribedSets: 2,
      maximumSets: 4,
      showAllEquipment: selection.$2,
    )));
  }
}
