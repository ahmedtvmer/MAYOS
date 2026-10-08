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
}
