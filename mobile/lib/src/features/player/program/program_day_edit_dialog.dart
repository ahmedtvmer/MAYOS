import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';

class ProgramDayEditDialog extends StatefulWidget {
  const ProgramDayEditDialog({super.key, required this.day});

  final ProgramDay day;

  static Future<List<ProgramEditExerciseEntry>?> show(
    BuildContext context,
    ProgramDay day,
  ) =>
      showDialog<List<ProgramEditExerciseEntry>>(
        context: context,
        builder: (BuildContext context) => ProgramDayEditDialog(day: day),
      );

  @override
  State<ProgramDayEditDialog> createState() => _ProgramDayEditDialogState();
}

class _ProgramDayEditDialogState extends State<ProgramDayEditDialog> {
  late final List<ProgramEditExerciseEntry> _exercises =
      <ProgramEditExerciseEntry>[
    for (final (int index, ProgramExercise exercise)
        in widget.day.exercises.indexed)
      ProgramEditExerciseEntry(
        sourceIndex: index,
        exercise: exercise,
        prescribedSets: exercise.targetSets,
      ),
  ];

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    return AlertDialog(
      title: Text(copy.editDay),
      content: _exerciseList(context),
      actions: _actions(copy),
    );
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
            _setCount(context, exercise),
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
      onPressed: exercise.targetSets <= 1
          ? null
          : () => _changeSetCount(entry, exercise.targetSets - 1),
      icon: const Icon(Icons.remove),
    );
  }

  Widget _setCount(BuildContext context, ProgramExercise exercise) {
    final MayosCopy copy = displayCopyOf(context);
    return Semantics(
      container: true,
      label: copy.programExerciseSetCount(
        exercise.exerciseName,
        exercise.targetSets,
      ),
      child: ExcludeSemantics(
        child: SizedBox(
          width: 20,
          child: Text(
            '${exercise.targetSets}',
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
      onPressed: exercise.targetSets >= entry.prescribedSets
          ? null
          : () => _changeSetCount(entry, exercise.targetSets + 1),
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
          onPressed: () => Navigator.of(context).pop(),
          child: Text(copy.cancel),
        ),
        FilledButton(
          key: const Key('program_edit_save_button'),
          onPressed: () => Navigator.of(context).pop(_exercises.toList()),
          child: Text(copy.save),
        ),
      ];
}
