import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/auth/google_auth_gateway.dart';
import 'package:mayos_mobile/src/features/player/workout/draft_sync_service.dart';
import 'package:mayos_mobile/src/features/shared/mode_switch.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_google_auth.dart';
import 'support/fake_mayos_api.dart';

/// Sign-in methods in Settings (#116): the section is driven by `GET /auth/me`
/// and every Google and API call runs against the two fakes.

const String _accountAlice = 'account-alice';

Future<void> _pumpUntilFound(WidgetTester tester, Finder finder,
    {int attempts = 60}) async {
  for (int i = 0; i < attempts; i++) {
    if (finder.evaluate().isNotEmpty) {
      for (int j = 0; j < 4; j++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<void> _seedSignedIn(
  FakeMayosApi fake,
  InMemoryTokenStore tokens, {
  required bool hasPassword,
  required bool googleLinked,
}) async {
  await tokens.save('token-alice');
  await tokens.saveAccountId(_accountAlice);
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  fake.passwords['alice'] = 'correct-horse-1';
  fake.hasPassword = hasPassword;
  fake.linkedSignIns
    ..clear()
    ..addAll(googleLinked ? <String>['google'] : <String>[]);
}

/// The signed-in app with both fakes wired: the Google SDK, the API, and the
/// in-memory stores the account-deletion erase path needs.
Future<void> _pumpProfile(
  WidgetTester tester,
  FakeMayosApi fake,
  InMemoryTokenStore tokens, {
  FakeGoogleAuthGateway? google,
  InMemoryDraftStore? drafts,
  InMemoryWorkoutCacheStore? cache,
  InMemoryChatCacheStore? chat,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryDraftStore draftStore = drafts ?? InMemoryDraftStore();
  final InMemoryWorkoutCacheStore cacheStore =
      cache ?? InMemoryWorkoutCacheStore();
  final InMemoryChatCacheStore chatStore = chat ?? InMemoryChatCacheStore();

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        draftStoreProvider.overrideWithValue(draftStore),
        workoutCacheStoreProvider.overrideWithValue(cacheStore),
        chatCacheStoreProvider.overrideWithValue(chatStore),
        activeWorkoutStoreProvider
            .overrideWithValue(InMemoryActiveWorkoutStore()),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        deviceTimezoneProvider
            .overrideWithValue(Future<String>.value('Europe/London')),
        if (google != null)
          googleAuthGatewayProvider.overrideWithValue(google),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          client.onAccountDeleted =
              ref.watch(accountDeletedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(tester, find.text('Home'));

  if (find.byIcon(Icons.settings_outlined).evaluate().isNotEmpty) {
    await tester.tap(find.byIcon(Icons.settings_outlined));
  } else {
    await tester.tap(find.byType(ModeAvatarButton));
    await _pumpUntilFound(tester, find.text('Settings'));
    await tester.tap(find.text('Settings'));
  }
  await _pumpUntilFound(tester, find.text('Appearance'));
  await tester.tap(find.text('Profile'));
  await _pumpUntilFound(tester, find.text('Training profile'));
  await tester.scrollUntilVisible(
    find.text('Sign-in methods'),
    300,
    scrollable: find.byType(Scrollable).first,
  );
  await _pumpUntilFound(tester, find.text('Sign-in methods'));
}

/// Brings a finder into view inside the profile list before tapping it.
Future<void> _reveal(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      finder,
      300,
      scrollable: find.byType(Scrollable).first,
    );
  }
  await _pumpUntilFound(tester, finder);
}

void main() {
  group('sign-in methods section', () {
    testWidgets('a password-only account offers change password and connect',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      expect(find.text('Sign-in methods'), findsOneWidget);
      expect(find.text('Password set'), findsOneWidget);
      expect(find.text('Change password'), findsOneWidget);
      expect(find.text('Set password'), findsNothing);
      expect(find.text('Not connected'), findsOneWidget);
      expect(find.text('Connected'), findsNothing);
      expect(find.text('Connect Google'), findsOneWidget);
      expect(find.byKey(const Key('connect_google_button')), findsOneWidget);
      expect(find.byKey(const Key('disconnect_google_button')), findsNothing);
      expect(find.text('Set a password first'), findsNothing);
    });

    testWidgets(
        'a Google-only account offers set password and a disabled disconnect',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: false, googleLinked: true);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      expect(find.text('No password yet'), findsOneWidget);
      expect(find.byKey(const Key('set_password_button')), findsOneWidget);
      expect(find.text('Set password'), findsOneWidget);
      expect(find.text('Change password'), findsNothing);
      expect(find.text('Connected'), findsOneWidget);
      expect(find.text('Set a password first'), findsOneWidget);
      expect(find.byKey(const Key('connect_google_button')), findsNothing);

      // Disconnecting would leave no way back in, so it is disabled (#114).
      final MayosButton disconnect = tester
          .widget<MayosButton>(find.byKey(const Key('disconnect_google_button')));
      expect(disconnect.onPressed, isNull);
      expect(fake.linkedSignIns, contains('google'));
    });

    testWidgets('an account with both methods can disconnect',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: true);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      expect(find.text('Password set'), findsOneWidget);
      expect(find.text('Change password'), findsOneWidget);
      expect(find.text('Connected'), findsOneWidget);
      expect(find.text('Set a password first'), findsNothing);
      expect(
        tester
            .widget<MayosButton>(find.byKey(const Key('disconnect_google_button')))
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('the connect button stays hidden where Google is unavailable',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(
        tester,
        fake,
        tokens,
        google:
            FakeGoogleAuthGateway(buttonStyle: GoogleSignInButtonStyle.hidden),
      );

      expect(find.text('Not connected'), findsOneWidget);
      expect(find.text('Connect Google'), findsNothing);
      expect(find.byKey(const Key('connect_google_button')), findsNothing);
    });
  });

  group('connect Google', () {
    testWidgets('a successful connect posts the ID token and re-reads auth/me',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
        ..idToken = 'fresh-connect-token';
      await _pumpProfile(tester, fake, tokens, google: google);

      await _reveal(tester, find.byKey(const Key('connect_google_button')));
      final int meBefore = fake
          .adapter.requests
          .where((r) => r.path == '/auth/me')
          .length;
      await tester.tap(find.byKey(const Key('connect_google_button')));
      await _pumpUntilFound(tester, find.text('Google account connected.'));

      expect(google.authenticateCalls, 1);
      expect(fake.linkGoogleRequests, 1);
      expect(fake.lastLinkGoogleIdToken, 'fresh-connect-token');
      expect(fake.linkedSignIns, contains('google'));
      expect(find.text('Connected'), findsOneWidget);
      expect(
        fake.adapter.requests.where((r) => r.path == '/auth/me').length,
        greaterThan(meBefore),
      );
      expect(find.byKey(const Key('connect_google_button')), findsNothing);
    });

    testWidgets('a subject connected to another account is shown clearly',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()
        ..googleLinkConflictElsewhere = true;
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('connect_google_button')));
      await tester.tap(find.byKey(const Key('connect_google_button')));
      await _pumpUntilFound(tester, find.text(
          'This Google account is already connected to another MAYOS account'));

      expect(fake.linkGoogleRequests, 1);
      expect(fake.linkedSignIns, isEmpty);
      expect(find.text('Not connected'), findsOneWidget);
    });

    testWidgets('a different Google account already connected is shown clearly',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi()
        ..googleLinkConflictDifferent = true;
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('connect_google_button')));
      await tester.tap(find.byKey(const Key('connect_google_button')));
      await _pumpUntilFound(tester, find.text(
          'This account already has a different Google account connected. Disconnect it first.'));

      expect(fake.linkGoogleRequests, 1);
      expect(fake.linkedSignIns, isEmpty);
      expect(find.text('Not connected'), findsOneWidget);
    });
  });

  group('disconnect Google', () {
    testWidgets('asks for confirmation and then disconnects',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: true);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('disconnect_google_button')));
      await tester.tap(find.byKey(const Key('disconnect_google_button')));
      await _pumpUntilFound(tester, find.text('Disconnect Google?'));

      // Cancelling changes nothing.
      await tester.tap(find.text('Cancel'));
      await _pumpUntilFound(tester, find.text('Connected'));
      expect(fake.unlinkGoogleRequests, 0);
      expect(fake.linkedSignIns, contains('google'));

      await tester.tap(find.byKey(const Key('disconnect_google_button')));
      await _pumpUntilFound(tester, find.text('Disconnect Google?'));
      await tester.tap(find.byKey(const Key('disconnect_google_confirm_button')));
      await _pumpUntilFound(tester, find.text('Google disconnected.'));

      expect(fake.unlinkGoogleRequests, 1);
      expect(fake.linkedSignIns, isEmpty);
      expect(find.text('Not connected'), findsOneWidget);
    });
  });

  group('change password', () {
    testWidgets('replacing a password ends the session with an explanation',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('change_password_button')));
      await tester.tap(find.byKey(const Key('change_password_button')));
      await _pumpUntilFound(
          tester, find.byKey(const Key('change_password_current_field')));

      await tester.enterText(
          find.byKey(const Key('change_password_current_field')), 'wrong-pass');
      await tester.enterText(
          find.byKey(const Key('change_password_new_field')), 'brand-new-pass');
      await tester.enterText(
          find.byKey(const Key('change_password_confirm_field')),
          'brand-new-pass');
      await tester.tap(find.byKey(const Key('change_password_confirm_button')));
      await _pumpUntilFound(tester, find.text('Invalid credentials.'));
      expect(fake.changePasswordRequests, 1);

      await tester.enterText(
          find.byKey(const Key('change_password_current_field')),
          'correct-horse-1');
      await tester.tap(find.byKey(const Key('change_password_confirm_button')));
      await _pumpUntilFound(tester, find.text('Log in'));

      expect(fake.changePasswordRequests, 2);
      expect(fake.lastChangePasswordNew, 'brand-new-pass');
      expect(fake.passwords['alice'], 'brand-new-pass');
      expect(find.textContaining('Password changed'), findsOneWidget);
    });
  });

  group('set password', () {
    testWidgets('refuses a weak password, then sets it and unlocks disconnect',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: false, googleLinked: true);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('set_password_button')));
      await tester.tap(find.byKey(const Key('set_password_button')));
      await _pumpUntilFound(tester, find.text('Set a password'));

      await tester.enterText(
          find.byKey(const Key('set_password_field')), 'short');
      await tester.enterText(
          find.byKey(const Key('set_password_confirm_field')), 'short');
      await tester.tap(find.byKey(const Key('set_password_confirm_button')));
      await _pumpUntilFound(tester, find.text('Use at least 8 characters.'));
      expect(fake.setPasswordRequests, 0);

      await tester.enterText(
          find.byKey(const Key('set_password_field')), 'correct-horse-1');
      await tester.enterText(
          find.byKey(const Key('set_password_confirm_field')),
          'correct-horse-1');
      await tester.tap(find.byKey(const Key('set_password_confirm_button')));
      await _pumpUntilFound(tester, find.text('Password set. You can now disconnect Google.'));

      expect(fake.setPasswordRequests, 1);
      expect(fake.lastSetPassword, 'correct-horse-1');
      expect(fake.hasPassword, isTrue);
      expect(find.text('Password set'), findsOneWidget);
      expect(find.text('Change password'), findsOneWidget);
      expect(
        tester
            .widget<MayosButton>(find.byKey(const Key('disconnect_google_button')))
            .onPressed,
        isNotNull,
      );
    });
  });

  group('delete account', () {
    testWidgets('a Google-only account deletes with a fresh Google ID token',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      final InMemoryDraftStore drafts = InMemoryDraftStore();
      final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
      final InMemoryChatCacheStore chat = InMemoryChatCacheStore();
      await _seedSignedIn(fake, tokens, hasPassword: false, googleLinked: true);
      await drafts.write(_accountAlice, <WorkoutDraft>[
        WorkoutDraft(
          clientSessionId: generateUuidV4(),
          accountId: _accountAlice,
          performedDate: '2026-09-26',
          performedTimezone: 'UTC',
          programVersion: 1,
          dayOrder: 1,
          dayName: 'Upper 1',
          capturedAt: '2026-09-26T11:00:00.000Z',
          exercises: const <DraftExercise>[],
          readiness: 4,
          updatedAt: '2026-09-26T11:00:00.000Z',
        ),
      ]);
      final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
        ..idToken = 'fresh-delete-token';
      fake.googleDeleteIdToken = 'fresh-delete-token';
      await _pumpProfile(tester, fake, tokens,
          google: google, drafts: drafts, cache: cache, chat: chat);

      await _reveal(tester, find.byKey(const Key('delete_account_button')));
      await tester.tap(find.byKey(const Key('delete_account_button')));
      await _pumpUntilFound(tester, find.text('Delete account?'));

      // No password exists, so there is no password field to fill in.
      expect(find.byKey(const Key('delete_account_password_field')),
          findsNothing);
      expect(find.textContaining('signing in with Google'), findsOneWidget);

      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(tester, find.text('Log in'));

      expect(google.authenticateCalls, 1);
      expect(fake.deleteAccountRequests, 1);
      expect(fake.lastDeleteGoogleIdToken, 'fresh-delete-token');
      expect(fake.lastDeletePassword, isNull);
      expect(fake.accountDeleted, isTrue);
      // The SDK signs out with the account, exactly as logout and a 401 do.
      expect(google.clearSdkStateCalls, 1);
      expect(await drafts.read(_accountAlice), isEmpty);
      expect(await tokens.read(), isNull);
      expect(find.textContaining('account was deleted'), findsOneWidget);
    });

    testWidgets('a cancelled Google sheet deletes nothing',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: false, googleLinked: true);
      final FakeGoogleAuthGateway google = FakeGoogleAuthGateway()
        ..idToken = null;
      await _pumpProfile(tester, fake, tokens, google: google);

      await _reveal(tester, find.byKey(const Key('delete_account_button')));
      await tester.tap(find.byKey(const Key('delete_account_button')));
      await _pumpUntilFound(tester, find.text('Delete account?'));
      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(
          tester, find.text('Google sign-in was cancelled. Your account was not deleted.'));

      expect(google.authenticateCalls, 1);
      expect(google.clearSdkStateCalls, 0);
      expect(fake.deleteAccountRequests, 0);
      expect(fake.accountDeleted, isFalse);
      expect(find.text('Delete account?'), findsOneWidget);
    });

    testWidgets('an account with a password keeps the password prompt',
        (WidgetTester tester) async {
      final FakeMayosApi fake = FakeMayosApi();
      final InMemoryTokenStore tokens = InMemoryTokenStore();
      await _seedSignedIn(fake, tokens, hasPassword: true, googleLinked: false);
      await _pumpProfile(tester, fake, tokens,
          google: FakeGoogleAuthGateway());

      await _reveal(tester, find.byKey(const Key('delete_account_button')));
      await tester.tap(find.byKey(const Key('delete_account_button')));
      await _pumpUntilFound(tester, find.text('Delete account?'));

      expect(
          find.byKey(const Key('delete_account_password_field')), findsOneWidget);

      await tester.enterText(
          find.byKey(const Key('delete_account_password_field')), 'wrong-pass');
      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(tester, find.text('Invalid credentials.'));
      expect(fake.accountDeleted, isFalse);

      await tester.enterText(find.byKey(const Key('delete_account_password_field')),
          'correct-horse-1');
      await tester.tap(find.byKey(const Key('delete_account_confirm_button')));
      await _pumpUntilFound(tester, find.text('Log in'));

      // The wrong password was refused first, then the right one deleted.
      expect(fake.deleteAccountRequests, 2);
      expect(fake.lastDeletePassword, 'correct-horse-1');
      expect(fake.lastDeleteGoogleIdToken, isNull);
    });
  });
}
