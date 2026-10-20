import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';

void main() {
  test('ProgramExercise parses optional Exercise library display labels', () {
    final ProgramExercise exercise = ProgramExercise.fromJson(
      <String, dynamic>{
        'exercise_id': 'machine_press',
        'exercise_name': 'Chest Press',
        'primary_muscle': 'Chest',
        'primary_action': 'Shoulder Horizontal Adduction',
        'equipment_category': 'Machine',
        'load_type': 'plate_loaded',
        'coach_equipment': null,
      },
    );

    expect(exercise.primaryMuscle, 'Chest');
    expect(exercise.primaryAction, 'Shoulder Horizontal Adduction');
    expect(exercise.equipmentCategory, 'Machine');
    expect(exercise.loadType, 'plate_loaded');
    expect(exercise.coachEquipment, isNull);
  });

  test('ProgramExercise accepts responses without display labels', () {
    final ProgramExercise exercise = ProgramExercise.fromJson(
      <String, dynamic>{
        'exercise_id': 'older_exercise',
        'exercise_name': 'Older exercise',
      },
    );

    expect(exercise.primaryMuscle, isNull);
    expect(exercise.primaryAction, isNull);
    expect(exercise.equipmentCategory, isNull);
    expect(exercise.loadType, isNull);
    expect(exercise.coachEquipment, isNull);
  });

  test('first set group supplies legacy mirrors and total working sets', () {
    final ProgramExercise exercise = ProgramExercise.fromJson(<String, dynamic>{
      'exercise_id': 'bench',
      'exercise_name': 'Bench Press',
      'target_sets': 99,
      'target_reps_min': 1,
      'target_reps_max': 1,
      'target_rpe': 10,
      'set_groups': <Map<String, dynamic>>[
        <String, dynamic>{'sets': 2, 'reps_min': 6, 'reps_max': 8, 'target_rir': 1},
        <String, dynamic>{'sets': 3, 'reps_min': 10, 'reps_max': 12, 'target_rir': 2},
      ],
    });

    expect(exercise.targetSets, 2);
    expect(exercise.targetRepsMin, 6);
    expect(exercise.targetRepsMax, 8);
    expect(exercise.targetRpe, 9);
    expect(exercise.workingSetCount, 5);
  });
}
