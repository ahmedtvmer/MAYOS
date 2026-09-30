import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/client_session_id.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/performed_date_window.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/workout/draft_sync_service.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

const String _accountA = 'account-alice';
const String _accountB = 'account-bob';

WorkoutDraft _draft({
  required String accountId,
  int programVersion = 1,
  String? clientSessionId,
  String capturedAt = '2026-09-26T11:00:00.000Z',
  List<WarmupMovementDraft> warmupMovements =
      const <WarmupMovementDraft>[],
}) =>
    WorkoutDraft(
      clientSessionId: clientSessionId ?? newClientSessionId(),
      accountId: accountId,
      performedDate: '2026-09-26',
      performedTimezone: 'UTC',
      programVersion: programVersion,
      dayOrder: 1,
      dayName: 'Upper 1',
      capturedAt: capturedAt,
      exercises: <DraftExercise>[
        DraftExercise(
          exercise: <String, dynamic>{
            'exercise_id': 'bench_press',
            'exercise_name': 'Bench Press',
            'target_sets': 3,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.5,
            'rest_seconds': 180,
            'notes': null,
          },
          sets: const <WorkoutSetLog>[
            WorkoutSetLog(weightKg: 100, reps: 5, rpe: 8),
          ],
        ),
      ],
      warmupMovements: warmupMovements,
      readiness: 4,
      updatedAt: '2026-09-26T11:00:00.000Z',
    );

TrainingProgram _cachedProgram() => const TrainingProgram(
      programName: 'Cached Split',
      splitType: 'Full Body',
      weeklyFrequency: 3,
      days: <ProgramDay>[
        ProgramDay(
          dayName: 'Full A',
          dayOrder: 1,
          exercises: <ProgramExercise>[
            ProgramExercise(
              exerciseId: 'bench_press',
              exerciseName: 'Bench Press',
              targetSets: 3,
              targetRepsMin: 5,
              targetRepsMax: 8,
              targetRpe: 8.5,
            ),
          ],
        ),
      ],
    );

ApiClient _client(FakeMayosApi fake, TokenStore tokens) => ApiClient(
      tokens: tokens,
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );

final DateTime _fixedNow = DateTime.parse('2026-09-26T12:00:00.000Z');

DraftSyncService _service({
  required FakeMayosApi fake,
  required TokenStore tokens,
  required DraftStore store,
  DateTime Function()? now,
}) =>
    DraftSyncService(
      api: _client(fake, tokens),
      store: store,
      retryInterval: null,
      now: now ?? (() => _fixedNow),
    );

Future<TokenStore> _authedTokens(FakeMayosApi fake) async {
  fake.issuedToken = 'token-a';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-a');
  return tokens;
}

Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.settings_outlined));
  await _pumpUntilFound(tester, find.text('Appearance'));
}

/// A frozen baseline for bench press so the table logger's tick can fill its
/// empty cells from the previous session (#123).
Map<String, dynamic> _benchBaseline() => <String, dynamic>{
      'exercise_id': 'bench_press',
      'sessions_logged': 3,
      'max_weight_kg': 100.0,
      'best_e1rm_kg': 121.67,
      'last_session': <String, dynamic>{
        'performed_date': '2026-09-26',
        'sets': <Map<String, dynamic>>[
          <String, dynamic>{'weight_kg': 100.0, 'reps': 5, 'rir': 1.0},
          <String, dynamic>{'weight_kg': 95.0, 'reps': 6, 'rir': 2.0},
          <String, dynamic>{'weight_kg': 92.5, 'reps': 6, 'rir': 2.0},
        ],
      },
    };

void main() {
  group('draft storage', () {
    test('persists across a simulated restart (new service, same storage)',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();

      final DraftSyncService first =
          _service(fake: fake, tokens: tokens, store: store);
      final WorkoutDraft draft = _draft(
        accountId: _accountA,
        warmupMovements: <WarmupMovementDraft>[
          WarmupMovementDraft(
            exerciseName: 'Cat-Cow',
            sets: const <WarmupSetDraft>[
              WarmupSetDraft(reps: 10, ticked: true),
              WarmupSetDraft(reps: 10),
            ],
          ),
        ],
      );
      first.startFor(_accountA, syncImmediately: false);
      await first.saveDraft(draft);

      final DraftSyncService restarted =
          _service(fake: fake, tokens: tokens, store: store);
      restarted.startFor(_accountA, syncImmediately: false);
      await restarted.refresh();
      final List<WorkoutDraft> reloaded = restarted.drafts;
      expect(reloaded, hasLength(1));
      expect(reloaded.single.clientSessionId, draft.clientSessionId);
      expect(reloaded.single.status, DraftStatus.pending);
      expect(reloaded.single.warmupMovements.single.sets[0].ticked, isTrue);
      expect(reloaded.single.warmupMovements.single.sets[1].ticked, isFalse);
    });

    test('survives logout and is never visible to another account', () async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      await service.saveDraft(_draft(accountId: _accountA));

      service.stop(); // logout clears the session, never the drafts.
      expect(await service.unsyncedCountFor(_accountA), 1);
      expect(await store.read(_accountB), isEmpty);
    });

    test('explicit discard removes the draft while keep does not', () async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      await service.saveDraft(_draft(accountId: _accountA));

      expect(await service.unsyncedCountFor(_accountA), 1);
      await service.discardAllForAccount(_accountA);
      expect(await store.read(_accountA), isEmpty);
    });
  });

  group('sync engine', () {
    test(
        'network failure stays pending; retry sends the same client session id',
        () async {
      final FakeMayosApi fake = FakeMayosApi()
        ..commitFails = true
        ..programVersion = 1;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      final WorkoutDraft draft = _draft(
        accountId: _accountA,
        warmupMovements: <WarmupMovementDraft>[
          WarmupMovementDraft(
            exerciseId: 'cat_cow',
            exerciseName: 'Cat-Cow',
            sets: const <WarmupSetDraft>[
              WarmupSetDraft(reps: 10, ticked: true),
              WarmupSetDraft(reps: 10),
            ],
          ),
        ],
      );
      await service.saveDraft(draft);
      expect((await store.read(_accountA)).single.status, DraftStatus.pending);
      expect(fake.committedSessions, isEmpty);

      fake.commitFails = false;
      await service.retryDraft(draft.clientSessionId);

      final List<WorkoutDraft> reloaded = await store.read(_accountA);
      expect(reloaded.single.status, DraftStatus.synced);
      expect(reloaded.single.serverResponse, isNotNull);
      // A recovered draft must not retain the stale failure message.
      expect(reloaded.single.lastError, isNull);
      expect(fake.committedSessions, hasLength(1));

      final List<FakeRequest> commits = fake.adapter.requests
          .where((FakeRequest r) =>
              r.method == 'POST' && r.path == '/workouts/sessions')
          .toList(growable: false);
      expect(commits, isNotEmpty);
      expect(commits.last.body['client_session_id'], draft.clientSessionId);
      expect(commits.last.body['warmup_movements'], <Map<String, dynamic>>[
        <String, dynamic>{
          'exercise_id': 'cat_cow',
          'exercise_name': 'Cat-Cow',
          'sets': <Map<String, dynamic>>[
            <String, dynamic>{'weight_kg': null, 'reps': 10},
          ],
        },
      ]);
    });

    test(
        'lost response is reconciled via the status endpoint without a second POST',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);

      final WorkoutDraft draft = _draft(accountId: _accountA);
      // The commit reached the server (response lost), so it is stored.
      fake.sessionCommits[draft.clientSessionId] = <String, dynamic>{
        'session_id': 'session-lost',
        'total_working_sets': 1,
      };
      fake.committedSessions
          .add(<String, dynamic>{'session_id': 'session-lost'});
      await store.write(_accountA, <WorkoutDraft>[draft]);

      service.startFor(_accountA, syncImmediately: false);
      await service.syncNow();

      final List<WorkoutDraft> reloaded = await store.read(_accountA);
      expect(reloaded.single.status, DraftStatus.synced);
      expect(reloaded.single.serverResponse?['session_id'], 'session-lost');
      expect(fake.commitRequests, 0);
    });

    test('an older program version syncs as history with a version difference',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 2;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      await service.saveDraft(_draft(accountId: _accountA, programVersion: 1));

      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.status, DraftStatus.synced);
      expect(reloaded.isHistoricalProgram, isTrue);
      expect(reloaded.activeProgramVersionAtSync, 2);
      expect(reloaded.versionDifferenceLabel,
          'Logged against program v1 (current v2)');
      expect(fake.committedSessions, hasLength(1));
    });

    test('a newer program version stays needs-attention', () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 2;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      await service.saveDraft(_draft(accountId: _accountA, programVersion: 3));

      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.status, DraftStatus.needsReconciliation);
      expect(reloaded.statusLabel, 'Needs attention');
      expect(reloaded.lastError, isNotNull);
      expect(fake.committedSessions, isEmpty);
    });

    test('successful commit shows the synced state and keeps the response',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      await service.saveDraft(_draft(accountId: _accountA));

      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.status, DraftStatus.synced);
      expect(reloaded.statusLabel, 'Synced');
      expect(reloaded.serverResponse?['session_id'], isNotNull);
      expect(fake.committedSessions, hasLength(1));
    });

    testWidgets('a synced historical entry shows the version difference',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 2;
      final InMemoryDraftStore store = InMemoryDraftStore();
      await store.write(_accountA, <WorkoutDraft>[
        _draft(accountId: _accountA, programVersion: 1).copyWith(
          status: DraftStatus.synced,
          updatedAt: DateTime.now().toIso8601String(),
          serverResponse: <String, dynamic>{
            'session_id': 'session-1',
            'program_version': 1,
            'active_program_version_at_sync': 2,
            'is_historical_program': true,
          },
        ),
      ]);

      await _pumpApp(tester, fake, draftStore: store);
      await _openSettings(tester);
      await tester.tap(find.text('Workout drafts'));
      await _pumpUntilFound(
          tester, find.text('Logged against program v1 (current v2)'));

      expect(
          find.text('Logged against program v1 (current v2)'), findsOneWidget);
    });
  });

  group('concurrency and account safety', () {
    test('a draft saved during an in-flight sync is never lost', () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final Completer<void> gate = Completer<void>();
      fake.adapter.beforeRespond = (FakeRequest request) async {
        if (request.path.startsWith('/workouts/sessions/by-client-id/')) {
          await gate.future;
        }
      };
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      final WorkoutDraft first = _draft(accountId: _accountA);
      await store.write(_accountA, <WorkoutDraft>[first]);
      final Future<void> sync = service.syncNow();
      await pumpEventQueue();

      final WorkoutDraft second = _draft(accountId: _accountA);
      await service.saveDraft(second);

      gate.complete();
      await sync;

      final List<WorkoutDraft> drafts = await store.read(_accountA);
      expect(
        drafts.map((WorkoutDraft d) => d.clientSessionId),
        containsAll(<String>[first.clientSessionId, second.clientSessionId]),
      );
    });

    test(
        'a draft discarded during an in-flight sync stays discarded and is never posted',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final Completer<void> gate = Completer<void>();
      fake.adapter.beforeRespond = (FakeRequest request) async {
        if (request.path.startsWith('/workouts/sessions/by-client-id/')) {
          await gate.future;
        }
      };
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      final WorkoutDraft draft = _draft(accountId: _accountA);
      await store.write(_accountA, <WorkoutDraft>[draft]);
      final Future<void> sync = service.syncNow();
      await pumpEventQueue();

      await service.discardDraft(draft.clientSessionId);
      gate.complete();
      await sync;

      expect(await store.read(_accountA), isEmpty);
      expect(fake.commitRequests, 0);
      expect(fake.committedSessions, isEmpty);
    });

    test(
        'logout abandons an in-flight pass: no post lands under the next account',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final Completer<void> gate = Completer<void>();
      fake.adapter.beforeRespond = (FakeRequest request) async {
        if (request.path.startsWith('/workouts/sessions/by-client-id/')) {
          await gate.future;
        }
      };
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      final WorkoutDraft draft = _draft(accountId: _accountA);
      await store.write(_accountA, <WorkoutDraft>[draft]);
      final Future<void> sync = service.syncNow();
      await pumpEventQueue();

      // Logout mid-flight, then a different account logs in on the same device.
      service.stop();
      service.startFor(_accountB, syncImmediately: false);
      gate.complete();
      await sync;

      expect(fake.commitRequests, 0);
      expect(await store.read(_accountB), isEmpty);
      // A's draft is untouched (still unsynced) in A's own storage.
      expect((await store.read(_accountA)).single.isSynced, isFalse);
    });

    test('a login during an in-flight pass still syncs the new account',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final Completer<void> gate = Completer<void>();
      fake.adapter.beforeRespond = (FakeRequest request) async {
        if (request.path.startsWith('/workouts/sessions/by-client-id/')) {
          await gate.future;
        }
      };
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);

      await store
          .write(_accountA, <WorkoutDraft>[_draft(accountId: _accountA)]);
      final Future<void> sync = service.syncNow();
      await pumpEventQueue();

      // B logs in while A's pass is still blocked on the status lookup; B's
      // immediate login sync must not be dropped waiting for the timer.
      await store
          .write(_accountB, <WorkoutDraft>[_draft(accountId: _accountB)]);
      service.startFor(_accountB);
      await pumpEventQueue();

      gate.complete();
      await sync;
      for (int i = 0;
          i < 50 && (await store.read(_accountB)).single.isSynced == false;
          i++) {
        await pumpEventQueue();
      }

      expect((await store.read(_accountB)).single.isSynced, isTrue);
      expect(fake.committedSessions, hasLength(1));
    });

    test('unreadable storage is quarantined, not silently wiped', () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore()
        ..simulateCorruptStorage(_accountA, raw: '{not valid json');
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      await service.refresh();

      expect(service.drafts, isEmpty);
      expect(service.storageQuarantined, isTrue);
      expect(store.quarantinedRaw.values, contains('{not valid json'));

      // A later write starts a fresh list; the quarantine flag clears.
      await service.saveDraft(_draft(accountId: _accountA));
      expect(service.storageQuarantined, isFalse);
    });

    test('network failures back off exponentially and reset on manual retry',
        () async {
      final FakeMayosApi fake = FakeMayosApi()
        ..commitFails = true
        ..programVersion = 1;
      DateTime now = DateTime.parse('2026-09-26T12:00:00.000Z');
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service = _service(
        fake: fake,
        tokens: tokens,
        store: store,
        now: () => now,
      );
      service.startFor(_accountA, syncImmediately: false);

      final WorkoutDraft draft = _draft(accountId: _accountA);
      await service.saveDraft(draft);
      WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.attempt, 1);
      expect(reloaded.nextAttemptAt, isNotNull);
      final DateTime firstNextAttempt = DateTime.parse(reloaded.nextAttemptAt!);
      expect(firstNextAttempt.difference(now), const Duration(seconds: 30));

      // Before the backoff window elapses, a plain sync pass skips it.
      await service.syncNow();
      reloaded = (await store.read(_accountA)).single;
      expect(reloaded.attempt, 1);

      // Once due, the next failure doubles the delay.
      now = firstNextAttempt.add(const Duration(seconds: 1));
      await service.syncNow();
      reloaded = (await store.read(_accountA)).single;
      expect(reloaded.attempt, 2);
      final DateTime secondNextAttempt =
          DateTime.parse(reloaded.nextAttemptAt!);
      expect(secondNextAttempt.difference(now), const Duration(seconds: 60));

      // A manual retry resets the backoff regardless of success.
      await service.retryDraft(draft.clientSessionId);
      reloaded = (await store.read(_accountA)).single;
      expect(reloaded.attempt, 1);
    });

    test(
        'pauseForeground stops the timer; resumeForeground runs an immediate pass',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service = DraftSyncService(
        api: _client(fake, tokens),
        store: store,
        retryInterval: const Duration(seconds: 60),
        now: () => _fixedNow,
      );
      service.startFor(_accountA, syncImmediately: false);
      await store
          .write(_accountA, <WorkoutDraft>[_draft(accountId: _accountA)]);

      service.pauseForeground();
      service.resumeForeground();
      await pumpEventQueue();

      expect(fake.commitRequests, 1);
      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.isSynced, isTrue);
    });
  });

  group('program tab offline fallback', () {
    testWidgets(
        'falls back to the cached program when offline, with a banner shown only then',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..activeProgramFails = true;
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cacheStore = InMemoryWorkoutCacheStore();
      const TrainingProgram cached = TrainingProgram(
        programName: 'Cached Split',
        splitType: 'Full Body',
        weeklyFrequency: 3,
        days: <ProgramDay>[
          ProgramDay(
            dayName: 'Full A',
            dayOrder: 1,
            exercises: <ProgramExercise>[
              ProgramExercise(
                exerciseId: 'sq',
                exerciseName: 'Squat',
                targetSets: 3,
                targetRepsMin: 5,
                targetRepsMax: 8,
                targetRpe: 8.5,
              ),
            ],
          ),
        ],
      );
      await cacheStore.writeProgram(_accountA, cached);
      await _pumpApp(tester, fake,
          draftStore: draftStore, cacheStore: cacheStore);

      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Cached Split'));

      expect(find.text('Offline — showing saved program'), findsOneWidget);
      expect(find.text('Cached Split'), findsOneWidget);
    });

    testWidgets('shows no offline banner once the online fetch succeeds',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      await _pumpApp(tester, fake, draftStore: draftStore);

      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));

      expect(find.text('Offline — showing saved program'), findsNothing);
    });
  });

  group('workout logger offline banner', () {
    testWidgets('no offline banner when the cached program is refreshed online',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cacheStore = InMemoryWorkoutCacheStore();
      await cacheStore.writeProgram(_accountA, _cachedProgram());

      await _pumpApp(tester, fake,
          draftStore: draftStore, cacheStore: cacheStore);
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Log workout'));
      await tester.tap(find.text('Log workout'));
      await _pumpUntilFound(tester, find.text('Bench Press'));

      expect(find.text('Offline: showing your cached program.'), findsNothing);
    });

    testWidgets('offline banner when the program can only be served from cache',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()
        ..programVersion = 1
        ..activeProgramFails = true;
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cacheStore = InMemoryWorkoutCacheStore();
      await cacheStore.writeProgram(_accountA, _cachedProgram());

      await _pumpApp(tester, fake,
          draftStore: draftStore, cacheStore: cacheStore);
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Cached Split'));
      await tester.ensureVisible(find.text('Log workout'));
      await tester.tap(find.text('Log workout'));
      await _pumpUntilFound(tester, find.text('Bench Press'));

      expect(
          find.text('Offline: showing your cached program.'), findsOneWidget);
    });
  });

  group('workout logger timezone', () {
    testWidgets(
        'blocks Finish rather than record a date against an unknown zone',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final InMemoryDraftStore draftStore = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cacheStore = InMemoryWorkoutCacheStore();
      await cacheStore.writeProgram(_accountA, _cachedProgram());

      await _pumpApp(tester, fake,
          draftStore: draftStore, cacheStore: cacheStore, deviceTimezone: null);
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Log workout'));
      await tester.tap(find.text('Log workout'));
      await _pumpUntilFound(tester, find.text('Bench Press'));

      final Finder finish =
          find.widgetWithText(FilledButton, 'Finish workout');
      expect(finish, findsOneWidget);
      expect(tester.widget<FilledButton>(finish).onPressed, isNull);
      expect(
        find.textContaining('device timezone could not be determined'),
        findsOneWidget,
      );
    });
  });

  group('web online-only boundary', () {
    testWidgets('keeps logging available while hiding drafts when disabled',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      await _pumpApp(tester, fake,
          draftStore: InMemoryDraftStore(), offlineDraftsEnabled: false);

      await _openSettings(tester);
      expect(find.text('Workout drafts'), findsNothing);
      await tester.tap(find.byTooltip('Back'));
      await _pumpUntilFound(tester, find.text('Home'));
      await tester.tap(find.text('Program'));
      await _pumpUntilFound(tester, find.text('Upper/Lower 4x'));
      expect(find.text('Log workout'), findsOneWidget);
    });

    testWidgets('the logger is available when drafts are disabled',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: <Override>[
            offlineWorkoutDraftsEnabledProvider.overrideWithValue(false),
          ],
          child: const MaterialApp(
            home: Scaffold(body: WorkoutLoggerScreen(dayOrder: 1)),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('You are not signed in.'), findsOneWidget);
      expect(find.textContaining('available in the Android app'), findsNothing);
    });
  });

  group('logout warning', () {
    testWidgets('keep drafts and log out preserves the draft',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final InMemoryDraftStore store = InMemoryDraftStore();
      await store
          .write(_accountA, <WorkoutDraft>[_draft(accountId: _accountA)]);

      await _pumpApp(tester, fake, draftStore: store);
      await _openSettings(tester);
      await tester.tap(find.text('Log out'));
      await _pumpUntilFound(tester, find.text('Unsynced workouts'));

      expect(find.text('Keep drafts and log out'), findsOneWidget);
      expect(find.text('Discard drafts and log out'), findsOneWidget);
      expect(find.text('Cancel'), findsOneWidget);

      await tester.tap(find.text('Keep drafts and log out'));
      await _pumpUntilFound(tester, find.text('Log in'));
      expect(await store.read(_accountA), hasLength(1));
    });

    testWidgets('discard drafts and log out erases them',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final InMemoryDraftStore store = InMemoryDraftStore();
      await store
          .write(_accountA, <WorkoutDraft>[_draft(accountId: _accountA)]);

      await _pumpApp(tester, fake, draftStore: store);
      await _openSettings(tester);
      await tester.tap(find.text('Log out'));
      await _pumpUntilFound(tester, find.text('Unsynced workouts'));

      await tester.tap(find.text('Discard drafts and log out'));
      await _pumpUntilFound(tester, find.text('Log in'));
      expect(await store.read(_accountA), isEmpty);
    });
  });

  testWidgets('logging a workout saves a draft and shows the workouts screen',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
    fake.baselinesBody = <Map<String, dynamic>>[_benchBaseline()];
    final InMemoryDraftStore store = InMemoryDraftStore();
    await _pumpApp(tester, fake, draftStore: store);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Log workout'));
    await tester.tap(find.text('Log workout'));
    await _pumpUntilFound(tester, find.text('Bench Press'));

    // The tick fills the empty cells from the frozen baseline's previous set.
    final Finder firstTick = find.byKey(const ValueKey<String>('logger.tick.0.0'));
    await tester.ensureVisible(firstTick);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(firstTick);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('100'), findsOneWidget);

    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    await tester.ensureVisible(finish);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(finish);
    await _pumpUntilFound(tester, find.text("2 sets aren't ticked"));
    await tester.tap(find.text('Discard unticked sets and finish'));
    await _pumpUntilFound(tester, find.text('Performed date'));

    final Finder save = find.widgetWithText(FilledButton, 'Save workout');
    await tester.ensureVisible(save);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Workouts'));

    final List<WorkoutDraft> drafts = await store.read(_accountA);
    expect(drafts, hasLength(1));
    expect(drafts.single.exercises, isNotEmpty);
    expect(fake.commitRequests, 1);
  });

  testWidgets('an unplanned exercise is picked from the catalog with a real id',
      (WidgetTester tester) async {
    final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
    fake.baselinesBody = <Map<String, dynamic>>[_benchBaseline()];
    final InMemoryDraftStore store = InMemoryDraftStore();
    await _pumpApp(tester, fake, draftStore: store);

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Log workout'));
    await tester.tap(find.text('Log workout'));
    await _pumpUntilFound(tester, find.text('Bench Press'));

    final Finder addUnplanned =
        find.widgetWithText(OutlinedButton, 'Add exercise');
    await tester.ensureVisible(addUnplanned);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(addUnplanned);
    await _pumpUntilFound(tester, find.text('Search the exercise catalog'));

    await tester.enterText(find.byType(TextField).last, 'curl');
    await tester.tap(find.text('Search'));
    await _pumpUntilFound(tester, find.text('Bicep Curl'));
    await tester.tap(find.text('Bicep Curl'));
    await _pumpUntilFound(tester, find.text('Unplanned'));

    // One ticked working set is enough to finish; the unplanned exercise is
    // kept as a skipped exercise because nothing of it was ticked.
    final Finder firstTick = find.byKey(const ValueKey<String>('logger.tick.0.0'));
    await tester.ensureVisible(firstTick);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(firstTick);
    await tester.pump(const Duration(milliseconds: 100));

    final Finder finish = find.widgetWithText(FilledButton, 'Finish workout');
    await tester.ensureVisible(finish);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(finish);
    await _pumpUntilFound(tester, find.text("2 sets aren't ticked"));
    await tester.tap(find.text('Discard unticked sets and finish'));
    await _pumpUntilFound(tester, find.text('Performed date'));
    final Finder save = find.widgetWithText(FilledButton, 'Save workout');
    await tester.ensureVisible(save);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(save);
    await _pumpUntilFound(tester, find.text('Workouts'));

    final List<WorkoutDraft> drafts = await store.read(_accountA);
    expect(drafts, hasLength(1));
    expect(
      drafts.single.exercises.map((DraftExercise e) => e.exerciseId),
      contains('bicep_curl'),
    );
    expect(
      drafts.single.exercises
          .firstWhere((DraftExercise e) => e.exerciseId == 'bicep_curl')
          .skipped,
      isTrue,
    );
  });

  group('performed-date corrections', () {
    test('the shared window is the local today bounded three days back', () {
      final DateTime now = DateTime(2026, 9, 26, 15, 30);
      final PerformedDateWindow window = performedDateWindow(now: now);
      expect(formatPerformedDate(window.last), '2026-09-26');
      expect(formatPerformedDate(window.first), '2026-09-23');
      expect(window.contains(DateTime(2026, 9, 25)), isTrue);
      expect(window.contains(DateTime(2026, 9, 22)), isFalse);
      // An out-of-window value clamps to the nearest bound.
      expect(formatPerformedDate(window.clamp(DateTime(2026, 9, 30))),
          '2026-09-26');
      expect(formatPerformedDate(window.clamp(DateTime(2026, 9, 1))),
          '2026-09-23');
    });

    test('a window for an older draft is anchored on its capture date', () {
      final DateTime now = DateTime(2026, 9, 26, 15, 30);
      // Captured 2026-09-23: the window ends at the capture date, not today.
      final PerformedDateWindow window = performedDateWindow(
        now: now,
        captureAt: DateTime(2026, 9, 23, 8, 0),
      );
      expect(formatPerformedDate(window.last), '2026-09-23');
      expect(formatPerformedDate(window.first), '2026-09-20');
      // A later date is past the post-capture ceiling.
      expect(window.contains(DateTime(2026, 9, 24)), isFalse);
      expect(formatPerformedDate(window.clamp(DateTime(2026, 9, 26))),
          '2026-09-23');
    });

    test('a toLocale capture instant folds to its local capture date', () {
      final DateTime now = DateTime(2026, 9, 26, 15, 30);
      final DateTime capture = DateTime.utc(2026, 9, 24, 23, 0);
      final DateTime localCapture = capture.toLocal();
      final PerformedDateWindow window =
          performedDateWindow(now: now, captureAt: capture);
      expect(
          formatPerformedDate(window.last), formatPerformedDate(localCapture));
      final DateTime expectedFirst =
          DateTime(localCapture.year, localCapture.month, localCapture.day - 3);
      expect(formatPerformedDate(window.first),
          formatPerformedDate(expectedFirst));
    });

    test('an unsynced draft edited locally keeps the new date', () async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      final WorkoutDraft draft = _draft(accountId: _accountA);
      await store.write(_accountA, <WorkoutDraft>[draft]);

      final bool edited = await service.updatePendingPerformedDate(
          draft.clientSessionId, '2026-09-24');

      expect(edited, isTrue);
      expect((await store.read(_accountA)).single.performedDate, '2026-09-24');
    });

    test('a synced draft is never edited locally', () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      final WorkoutDraft synced = _draft(accountId: _accountA).copyWith(
        status: DraftStatus.synced,
        serverResponse: <String, dynamic>{'session_id': 'session-1'},
      );
      await store.write(_accountA, <WorkoutDraft>[synced]);

      final bool edited = await service.updatePendingPerformedDate(
          synced.clientSessionId, '2026-09-24');

      expect(edited, isFalse);
      expect((await store.read(_accountA)).single.performedDate, '2026-09-26');
    });

    test('correcting a synced draft updates the local date from the response',
        () async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      fake.committedSessions.add(<String, dynamic>{
        'session_id': 'session-1',
        'session_date': '2026-09-26',
      });
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      final WorkoutDraft synced = _draft(accountId: _accountA).copyWith(
        status: DraftStatus.synced,
        serverResponse: <String, dynamic>{'session_id': 'session-1'},
      );
      await store.write(_accountA, <WorkoutDraft>[synced]);

      await service.correctSyncedPerformedDate(
          synced.clientSessionId, '2026-09-25');

      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.performedDate, '2026-09-25');
      expect(reloaded.isSynced, isTrue);

      final List<FakeRequest> patches = fake.adapter.requests
          .where((FakeRequest r) =>
              r.method == 'PATCH' &&
              r.path == '/workouts/sessions/session-1/performed-date')
          .toList(growable: false);
      expect(patches, hasLength(1));
      expect(patches.single.body['performed_date'], '2026-09-25');
    });

    test('reconciling a committed draft adopts the corrected server date',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);

      final WorkoutDraft draft = _draft(accountId: _accountA);
      // The commit reached the server and was later corrected to 2026-09-24.
      fake.sessionCommits[draft.clientSessionId] = <String, dynamic>{
        'session_id': 'session-lost',
        'session_date': '2026-09-24',
      };
      await store.write(_accountA, <WorkoutDraft>[draft]);

      service.startFor(_accountA, syncImmediately: false);
      await service.syncNow();

      final WorkoutDraft reloaded = (await store.read(_accountA)).single;
      expect(reloaded.isSynced, isTrue);
      expect(reloaded.performedDate, '2026-09-24');
      expect(fake.commitRequests, 0);
    });

    test('a refused correction surfaces the service error unchanged', () async {
      final FakeMayosApi fake = FakeMayosApi()..correctionRefused = true;
      fake.committedSessions.add(<String, dynamic>{
        'session_id': 'session-1',
        'session_date': '2026-09-26',
      });
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      final WorkoutDraft synced = _draft(accountId: _accountA).copyWith(
        status: DraftStatus.synced,
        serverResponse: <String, dynamic>{'session_id': 'session-1'},
      );
      await store.write(_accountA, <WorkoutDraft>[synced]);

      await expectLater(
        service.correctSyncedPerformedDate(
            synced.clientSessionId, '2026-09-25'),
        throwsA(isA<ApiException>()),
      );
      expect((await store.read(_accountA)).single.performedDate, '2026-09-26');
    });

    test('an offline correction surfaces the network error', () async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      fake.committedSessions.add(<String, dynamic>{
        'session_id': 'session-1',
        'session_date': '2026-09-26',
      });
      final TokenStore tokens = await _authedTokens(fake);
      final InMemoryDraftStore store = InMemoryDraftStore();
      final DraftSyncService service =
          _service(fake: fake, tokens: tokens, store: store);
      service.startFor(_accountA, syncImmediately: false);
      final WorkoutDraft synced = _draft(accountId: _accountA).copyWith(
        status: DraftStatus.synced,
        serverResponse: <String, dynamic>{'session_id': 'session-1'},
      );
      await store.write(_accountA, <WorkoutDraft>[synced]);

      await expectLater(
        service.correctSyncedPerformedDate(
            synced.clientSessionId, '2026-09-25'),
        throwsA(isA<ApiException>()),
      );
    });

    testWidgets('an unsynced draft offers a bounded local date edit',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..commitFails = true;
      final InMemoryDraftStore store = InMemoryDraftStore();
      await store
          .write(_accountA, <WorkoutDraft>[_draft(accountId: _accountA)]);

      await _pumpApp(tester, fake, draftStore: store);
      await _openSettings(tester);
      await tester.tap(find.text('Workout drafts'));
      await _pumpUntilFound(tester, find.byTooltip('Edit date'));

      await tester.tap(find.byTooltip('Edit date'));
      await _pumpUntilFound(tester, find.byType(DatePickerDialog));

      expect(find.byType(DatePickerDialog), findsOneWidget);
    });

    testWidgets('a synced draft offers "Correct date"',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()..programVersion = 1;
      final InMemoryDraftStore store = InMemoryDraftStore();
      // The sync service prunes synced drafts whose updatedAt is older than 24h
      // relative to its real clock, so a fixed stamp turns this into a
      // date-dependent test.
      await store.write(_accountA, <WorkoutDraft>[
        _draft(accountId: _accountA).copyWith(
          status: DraftStatus.synced,
          serverResponse: <String, dynamic>{'session_id': 'session-1'},
          updatedAt: DateTime.now().toIso8601String(),
        ),
      ]);

      await _pumpApp(tester, fake, draftStore: store);
      await _openSettings(tester);
      await tester.tap(find.text('Workout drafts'));
      await _pumpUntilFound(tester, find.byTooltip('Correct date'));

      expect(find.byTooltip('Correct date'), findsOneWidget);
      expect(find.byTooltip('Edit date'), findsNothing);
    });
  });
}

// ---------------------------------------------------------------------------
// Widget harness
// ---------------------------------------------------------------------------

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 50}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpApp(
  WidgetTester tester,
  FakeMayosApi fake, {
  required InMemoryDraftStore draftStore,
  InMemoryWorkoutCacheStore? cacheStore,
  String? deviceTimezone = 'UTC',
  bool offlineDraftsEnabled = true,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        draftStoreProvider.overrideWithValue(draftStore),
        workoutCacheStoreProvider
            .overrideWithValue(cacheStore ?? InMemoryWorkoutCacheStore()),
        // #123's keystore-backed stores have no plugin on the test host.
        activeWorkoutStoreProvider
            .overrideWithValue(InMemoryActiveWorkoutStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value(deviceTimezone ?? 'UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value(deviceTimezone)),
        offlineWorkoutDraftsEnabledProvider
            .overrideWithValue(offlineDraftsEnabled),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));
}
