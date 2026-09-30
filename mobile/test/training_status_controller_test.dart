import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/training_status_controller.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';

import 'support/fake_mayos_api.dart';

void main() {
  test(
    'loads, replaces from a commit, and restores status after restart',
    () async {
      final FakeMayosApi fake = FakeMayosApi()
        ..issuedToken = 'token-alice'
        ..currentUsername = 'alice'
        ..profileExists = true
        ..trainingStatusBody = <String, dynamic>{
          'weekly_streak': 2,
          'week_start': '2026-09-26',
          'week_done': 1,
          'week_target': 3,
          'mayos_workouts': 9,
          'next_checkpoint': 10,
          'workouts_to_next': 1,
        };
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await tokens.save('token-alice');
      final ApiClient api = ApiClient(
        tokens: tokens,
        baseUrl: 'http://test.local',
        adapter: fake.adapter,
      );
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final TrainingStatusController first = TrainingStatusController(
        api: api,
        cache: cache,
      );

      await first.refresh('account-alice');
      expect(first.state?.mayosWorkouts, 9);
      expect(fake.trainingStatusRequests, 1);

      await first.acceptCommit('account-alice', <String, dynamic>{
        'training_status': <String, dynamic>{
          'weekly_streak': 3,
          'week_start': '2026-09-26',
          'week_done': 2,
          'week_target': 3,
          'mayos_workouts': 10,
          'next_checkpoint': 25,
          'workouts_to_next': 15,
        },
      });
      first.dispose();

      final TrainingStatusController afterRestart = TrainingStatusController(
        api: api,
        cache: cache,
      );
      final TrainingStatus? restored = await afterRestart.statusForSummary(
        'account-alice',
      );
      expect(restored?.weeklyStreak, 3);
      expect(restored?.mayosWorkouts, 10);
      expect(restored?.nextCheckpoint, 25);
      afterRestart.dispose();
    },
  );
}
