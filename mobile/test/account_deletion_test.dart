import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/display_language.dart';
import 'package:mayos_mobile/src/core/client_session_id.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/features/player/workout/draft_sync_service.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

const String _accountAlice = 'account-alice';

WorkoutDraft _draft() => WorkoutDraft(
      clientSessionId: newClientSessionId(),
      accountId: _accountAlice,
      performedDate: '2026-09-26',
      performedTimezone: 'UTC',
      programVersion: 1,
      dayOrder: 1,
      dayName: 'Upper 1',
      capturedAt: '2026-09-26T11:00:00.000Z',
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
      readiness: 4,
      updatedAt: '2026-09-26T11:00:00.000Z',
    );

TrainingProgram _program() => const TrainingProgram(
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

Prescription _prescription() => const Prescription(
      targets: <PrescriptionTarget>[
        PrescriptionTarget(
          exerciseId: 'bench_press',
          exerciseName: 'Bench Press',
          isBarbell: true,
          effectiveSets: 3,
          targetRpeCap: 8.5,
          projectedWeight: 102.5,
        ),
      ],
    );

Future<void> _seedSignedIn(FakeMayosApi fake, InMemoryTokenStore tokens) async {
  await tokens.save('token-alice');
  await tokens.saveAccountId(_accountAlice);
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.passwords['alice'] = 'correct-horse-1';
}

ApiClient _api(FakeMayosApi fake, TokenStore tokens) {
  final ApiClient client = ApiClient(
    tokens: tokens,
    baseUrl: 'http://test.local',
    adapter: fake.adapter,
  );
  return client;
}

ProviderContainer _container({
  required FakeMayosApi fake,
  required InMemoryTokenStore tokens,
  required InMemoryDraftStore drafts,
  required InMemoryWorkoutCacheStore cache,
  required InMemoryChatCacheStore chat,
  DisplayLanguageStore? displayLanguageStore,
}) {
  return ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
      appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
      draftStoreProvider.overrideWithValue(drafts),
      workoutCacheStoreProvider.overrideWithValue(cache),
      chatCacheStoreProvider.overrideWithValue(chat),
      if (displayLanguageStore != null)
        displayLanguageStoreProvider.overrideWithValue(displayLanguageStore),
      // The keystore-backed stores of #123 have no plugin on the test host;
      // the in-memory fakes keep the account-deletion erase path real.
      activeWorkoutStoreProvider
          .overrideWithValue(InMemoryActiveWorkoutStore()),
      baselineCacheStoreProvider
          .overrideWithValue(InMemoryBaselineCacheStore()),
      apiClientProvider.overrideWith((ref) {
        final ApiClient client = _api(fake, ref.watch(tokenStoreProvider));
        client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
        client.onAccountDeleted =
            ref.watch(accountDeletedEventsProvider).signal;
        return client;
      }),
    ],
  );
}

Future<InMemoryDraftStore> _seedLocalData(
  InMemoryTokenStore tokens,
  InMemoryDraftStore drafts,
  InMemoryWorkoutCacheStore cache,
  InMemoryChatCacheStore chat,
) async {
  await drafts.write(_accountAlice, <WorkoutDraft>[_draft()]);
  await cache.writeProgram(_accountAlice, _program());
  await cache.writePrescription(_accountAlice, 1, _prescription());
  await chat.writeDisclosureAccepted(_accountAlice);
  await chat.writeHistory(_accountAlice, const <ChatMessage>[
    ChatMessage(id: 'm1', role: 'user', content: 'hello'),
  ]);
  return drafts;
}

/// Player mode carries the header Settings icon; Coach mode reaches Settings
/// from the mode sheet (#119).
Future<void> _openSettings(WidgetTester tester) async {
  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
}

void main() {
  group('account deletion', () {
    test('delete with the password erases local data and ends the session',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      final InMemoryDisplayLanguageStore displayLanguage =
          InMemoryDisplayLanguageStore();
      await displayLanguage.writeAccount(_accountAlice, 'ar');
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);

      final ProviderContainer container = _container(
          fake: fake,
          tokens: tokens,
          drafts: drafts,
          cache: cache,
          chat: chat,
          displayLanguageStore: displayLanguage);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);
      await auth.initialize();
      expect(container.read(authControllerProvider).isAuthenticated, isTrue);

      await auth.deleteAccount('correct-horse-1');

      final RequestMatch req = _findRequest(fake, 'DELETE', '/auth/account');
      expect(req.body['password'], 'correct-horse-1');

      final AuthState state = container.read(authControllerProvider);
      expect(state.status, AuthStatus.unauthenticated);
      expect(state.notice, contains('deleted'));

      expect(await drafts.read(_accountAlice), isEmpty);
      expect(await cache.readProgram(_accountAlice), isNull);
      expect(await cache.readPrescription(_accountAlice, 1), isNull);
      expect(await chat.readDisclosureAccepted(_accountAlice), isFalse);
      expect(await chat.readHistory(_accountAlice), isEmpty);
      expect(await displayLanguage.readAccount(_accountAlice), isNull);
      expect(await tokens.read(), isNull);
      expect(await tokens.readAccountId(), isNull);
    });

    test('wrong password changes nothing and keeps data', () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);
      await auth.initialize();

      await expectLater(
        auth.deleteAccount('wrong-password'),
        throwsA(isA<ApiException>()),
      );

      expect(container.read(authControllerProvider).isAuthenticated, isTrue);
      expect(await drafts.read(_accountAlice), hasLength(1));
      expect(await cache.readProgram(_accountAlice), isNotNull);
      expect(await chat.readDisclosureAccepted(_accountAlice), isTrue);
      expect(await tokens.read(), isNotNull);
    });

    test('offline deletion shows the shared needs-connection message',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      fake.failOffline('DELETE', '/auth/account');
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);
      await auth.initialize();

      try {
        await auth.deleteAccount('correct-horse-1');
        fail('expected an ApiException');
      } on ApiException catch (error) {
        expect(isNetworkFailure(error), isTrue);
        expect(
            mutationFailureMessage(error).englishText, needsConnectionMessage);
      }

      expect(await drafts.read(_accountAlice), hasLength(1));
      expect(container.read(authControllerProvider).isAuthenticated, isTrue);
    });

    test('another device erases drafts when a request reports account_deleted',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);

      // The account was deleted elsewhere: the next status check says so.
      fake.accountDeleted = true;
      await auth.initialize();

      final AuthState state = container.read(authControllerProvider);
      expect(state.status, AuthStatus.unauthenticated);
      expect(state.notice, contains('deleted'));
      expect(await drafts.read(_accountAlice), isEmpty);
      expect(await cache.readProgram(_accountAlice), isNull);
      expect(await chat.readDisclosureAccepted(_accountAlice), isFalse);
      expect(await tokens.read(), isNull);
    });

    test('a draft-sync 401 account_deleted erases drafts without a prompt',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);
      await auth.initialize();

      final DraftSyncService sync = DraftSyncService(
        api: container.read(apiClientProvider),
        store: drafts,
        retryInterval: null,
      );
      addTearDown(sync.dispose);
      sync.startFor(_accountAlice, syncImmediately: false);

      fake.accountDeleted = true;
      await sync.syncNow();
      for (int i = 0; i < 20; i++) {
        await Future<void>.delayed(Duration.zero);
        if ((await drafts.read(_accountAlice)).isEmpty) {
          break;
        }
      }
      expect(await drafts.read(_accountAlice), isEmpty);
      expect(container.read(authControllerProvider).isAuthenticated, isFalse);
    });

    test('an ordinary 401 does not erase drafts', () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await _seedLocalData(tokens, drafts, cache, chat);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);

      fake.tokenValid = false; // stale/expired session, not a deletion
      await auth.initialize();

      expect(container.read(authControllerProvider).status,
          AuthStatus.unauthenticated);
      expect(await drafts.read(_accountAlice), hasLength(1));
      expect(await cache.readProgram(_accountAlice), isNotNull);
      expect(await tokens.read(), isNull);
    });
  });

  group('profile delete flow', () {
    testWidgets('warning, wrong password error, then login with confirmation',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens);
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await drafts.write(_accountAlice, <WorkoutDraft>[_draft()]);

      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        ProviderScope(
          overrides: <Override>[
            tokenStoreProvider.overrideWithValue(tokens),
            appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
            draftStoreProvider.overrideWithValue(drafts),
            workoutCacheStoreProvider.overrideWithValue(cache),
            chatCacheStoreProvider.overrideWithValue(chat),
            activeWorkoutStoreProvider
                .overrideWithValue(InMemoryActiveWorkoutStore()),
            baselineCacheStoreProvider
                .overrideWithValue(InMemoryBaselineCacheStore()),
            deviceTimezoneProvider
                .overrideWithValue(Future<String>.value('America/New_York')),
            apiClientProvider.overrideWith((ref) {
              final ApiClient client =
                  _api(fake, ref.watch(tokenStoreProvider));
              client.onUnauthorized =
                  ref.watch(unauthorizedEventsProvider).signal;
              client.onAccountDeleted =
                  ref.watch(accountDeletedEventsProvider).signal;
              return client;
            }),
          ],
          child: const MayosApp(),
        ),
      );
      await _pumpUntilFound(tester, find.text('Home'));

      await _openSettings(tester);

      await tester.tap(find.text('Profile'));
      await _pumpUntilFound(tester, find.text('Training profile'));

      await tester.scrollUntilVisible(
        find.byKey(const Key('delete_account_button')),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.byKey(const Key('delete_account_button')));
      await _pumpUntilFound(tester, find.text('Delete account?'));

      // A wrong password keeps the account and the local drafts.
      await tester.enterText(
          find.byKey(const Key('delete_account_password_field')), 'wrong-pass');
      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(tester, find.text('Invalid credentials.'));
      expect(await drafts.read(_accountAlice), hasLength(1));

      // The correct password deletes and routes to login with confirmation.
      await tester.enterText(
          find.byKey(const Key('delete_account_password_field')),
          'correct-horse-1');
      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(tester, find.text('Log in'));
      expect(find.textContaining('account was deleted'), findsOneWidget);
      expect(await drafts.read(_accountAlice), isEmpty);
    });
  });

  group('pre-upgrade and resume signals', () {
    test('erases via the stored JWT sub when no account id was stored',
        () async {
      final FakeMayosApi fake = FakeMayosApi();
      fake.accountDeleted = true;
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      // A pre-upgrade install: a token exists, but no persisted account id.
      await tokens.save(_jwtWithSubject(_accountAlice));
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await drafts.write(_accountAlice, <WorkoutDraft>[_draft()]);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);

      await container.read(authControllerProvider.notifier).initialize();

      expect(container.read(authControllerProvider).status,
          AuthStatus.unauthenticated);
      expect(await drafts.read(_accountAlice), isEmpty);
      expect(await tokens.readAccountId(), isNull);
    });

    test('app-resume refresh erases on account_deleted', () async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens);
      await drafts.write(_accountAlice, <WorkoutDraft>[_draft()]);
      final ProviderContainer container = _container(
          fake: fake, tokens: tokens, drafts: drafts, cache: cache, chat: chat);
      addTearDown(container.dispose);
      final AuthController auth =
          container.read(authControllerProvider.notifier);
      await auth.initialize();
      expect(container.read(authControllerProvider).isAuthenticated, isTrue);

      // The app is resumed after the account was deleted elsewhere.
      fake.accountDeleted = true;
      await auth.refreshAccount();
      for (int i = 0; i < 20; i++) {
        await Future<void>.delayed(Duration.zero);
        if ((await drafts.read(_accountAlice)).isEmpty) {
          break;
        }
      }

      expect(container.read(authControllerProvider).isAuthenticated, isFalse);
      expect(await drafts.read(_accountAlice), isEmpty);
      expect(await tokens.read(), isNull);
    });
  });

  group('account-namespaced key matching', () {
    test('erasing one account never touches an id that is its prefix',
        () async {
      FlutterSecureStorage.setMockInitialValues(<String, String>{
        'drafts.acc': 'a',
        'drafts.acc.corrupt.1': 'b',
        'drafts.acc2': 'c',
        'program.acc': 'p',
        'program.acc2': 'q',
        'prescription.acc.1': 'r',
        'prescription.acc2.1': 's',
      });
      const FlutterSecureStorage storage = FlutterSecureStorage();

      await SecureDraftStore().deleteForAccount('acc');
      await SecureWorkoutCacheStore().deleteForAccount('acc');

      expect(await storage.read(key: 'drafts.acc'), isNull);
      expect(await storage.read(key: 'drafts.acc.corrupt.1'), isNull);
      expect(await storage.read(key: 'drafts.acc2'), 'c');
      expect(await storage.read(key: 'program.acc'), isNull);
      expect(await storage.read(key: 'program.acc2'), 'q');
      expect(await storage.read(key: 'prescription.acc.1'), isNull);
      expect(await storage.read(key: 'prescription.acc2.1'), 's');
    });
  });
}

String _jwtWithSubject(String subject) {
  final String header = base64Url
      .encode(utf8.encode('{"alg":"HS256","typ":"JWT"}'))
      .replaceAll('=', '');
  final String payload =
      base64Url.encode(utf8.encode('{"sub":"$subject"}')).replaceAll('=', '');
  return '$header.$payload.signature';
}

class RequestMatch {
  const RequestMatch(this.body);
  final Map<String, dynamic> body;
}

RequestMatch _findRequest(FakeMayosApi fake, String method, String path) {
  final FakeRequest request = fake.adapter.requests.lastWhere(
    (FakeRequest r) => r.method == method && r.path == path,
  );
  return RequestMatch(request.body);
}

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 40}) async {
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
