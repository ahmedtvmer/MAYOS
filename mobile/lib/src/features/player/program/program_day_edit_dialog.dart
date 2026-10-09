import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';

class ProgramDayEditDialog extends StatefulWidget {
  const ProgramDayEditDialog({super.key, required this.day});

  final ProgramDay day;

  static Future<List<ProgramExercise>?> show(
    BuildContext context,
    ProgramDay day,
  ) =>
      showDialog<List<ProgramExercise>>(
        context: context,
        builder: (BuildContext context) => ProgramDayEditDialog(day: day),
      );

  @override
  State<ProgramDayEditDialog> createState() => _ProgramDayEditDialogState();
}

class _ProgramDayEditDialogState extends State<ProgramDayEditDialog> {
  late final List<ProgramExercise> _exercises =
      List<ProgramExercise>.of(widget.day.exercises);

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
      _exercises.length * 72.0,
    );
    return SizedBox(
      width: math.min(420.0, screenSize.width - 80),
      height: listHeight,
      child: ListView.separated(
        itemCount: _exercises.length,
        separatorBuilder: (BuildContext context, int index) =>
            const Divider(height: 1),
        itemBuilder: (BuildContext context, int index) =>
            _exerciseRow(context, index),
      ),
    );
  }

  Widget _exerciseRow(BuildContext context, int index) {
    final ProgramExercise exercise = _exercises[index];
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(exercise.exerciseName),
      trailing: IconButton(
        tooltip: displayCopyOf(context)
            .removeExerciseNamed(exercise.exerciseName),
        onPressed: _exercises.length == 1
            ? null
            : () => setState(() => _exercises.removeWhere(
                  (ProgramExercise pending) => identical(pending, exercise),
                )),
        icon: const Icon(Icons.remove_circle_outline),
      ),
    );
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
