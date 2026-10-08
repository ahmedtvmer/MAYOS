import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/models.dart';

void main() {
  test('coach session exercise parses optional library labels', () {
    final CoachPlayerSessionExercise exercise =
        CoachPlayerSessionExercise.fromJson(<String, dynamic>{
      'exercise_id': 'sq',
      'name': 'Squat',
      'sets': 2,
      'reps': 9,
      'volume_kg': 920,
      'image_path': 'images/squat.jpg',
      'primary_muscle': 'Quads',
      'primary_action': 'Knee Extension',
    });

    expect(exercise.exerciseId, 'sq');
    expect(exercise.imagePath, 'images/squat.jpg');
    expect(exercise.primaryMuscle, 'Quads');
    expect(exercise.primaryAction, 'Knee Extension');
  });

  test('coach session models tolerate missing exercise enrichment', () {
    final CoachPlayerSessionExercise exercise =
        CoachPlayerSessionExercise.fromJson(<String, dynamic>{
      'name': 'Legacy Squat',
      'sets': 1,
      'reps': 5,
      'volume_kg': 500,
    });
    final CoachPlayerRecentSession session = CoachPlayerRecentSession.fromJson(
      <String, dynamic>{
        'session_id': 'session-1',
        'session_date': '2026-09-26',
        'split_name': 'Full A',
        'sets_count': 1,
        'total_volume_kg': 500,
      },
    );

    expect(exercise.exerciseId, isNull);
    expect(exercise.imagePath, isNull);
    expect(exercise.primaryMuscle, isNull);
    expect(exercise.primaryAction, isNull);
    expect(session.exercises, isEmpty);
  });

  test('coach records and exercise rows parse optional image and muscle labels', () {
    final PersonalRecord record = PersonalRecord.fromJson(<String, dynamic>{
      'exercise_id': 'sq',
      'name': 'Squat',
      'record_type': 'max_weight',
      'reps': 5,
      'value': 100,
      'achieved_at': '2026-09-26',
      'image_path': 'images/squat.jpg',
      'primary_muscle': 'Quads',
    });
    final CoachPlayerExercise exercise = CoachPlayerExercise.fromJson(
      <String, dynamic>{
        'id': 'sq',
        'name': 'Squat',
        'image_path': 'images/squat.jpg',
        'primary_muscle': 'Quads',
      },
    );
    final PersonalRecord legacyRecord = PersonalRecord.fromJson(
      <String, dynamic>{
        'exercise_id': 'old',
        'name': 'Old Exercise',
        'record_type': 'max_weight',
        'reps': 5,
        'value': 100,
        'achieved_at': '2026-09-26',
      },
    );
    final CoachPlayerExercise legacyExercise = CoachPlayerExercise.fromJson(
      <String, dynamic>{'id': 'old', 'name': 'Old Exercise'},
    );

    expect(record.imagePath, 'images/squat.jpg');
    expect(record.primaryMuscle, 'Quads');
    expect(exercise.imagePath, 'images/squat.jpg');
    expect(exercise.primaryMuscle, 'Quads');
    expect(legacyRecord.imagePath, isNull);
    expect(legacyRecord.primaryMuscle, isNull);
    expect(legacyExercise.imagePath, isNull);
    expect(legacyExercise.primaryMuscle, isNull);
  });
}
