import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/shared_program_text.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/router.dart';

import 'support/coach_layout_harness.dart';
import 'support/fake_mayos_api.dart';

class FakeSharedProgramTextSource implements SharedProgramTextSource {
  FakeSharedProgramTextSource({this.initialText});

  final SharedProgramText? initialText;
  final StreamController<SharedProgramText> _events =
      StreamController<SharedProgramText>.broadcast();

  void share(String text) => _events.add(SharedProgramText(text));

  @override
  Future<SharedProgramText?> initial() async => initialText;

  @override
  Stream<SharedProgramText> get events => _events.stream;
}

void main() {
  testWidgets('cold start with shared text reaches the Coach chooser',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Day 1\nBench Press 3x8'),
    );
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) => _addPlayer(fake),
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('shared_program_chooser')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).choosePlayerForSharedProgram),
          findsOneWidget,
        );
        expect(find.text('bob'), findsOneWidget);
        final BuildContext context = current.element(
          find.byKey(const Key('shared_program_chooser')),
        );
        expect(
          ProviderScope.containerOf(context)
              .read(sharedProgramTextStoreProvider)
              .pending
              ?.text,
          'Day 1\nBench Press 3x8',
        );
      },
    );
  });

  testWidgets('warm share replaces text without stacking the chooser route',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource();
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) => _addPlayer(fake),
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      prepare: (WidgetTester current, String language) async {
        await _pumpUntil(
          current,
          () => find.byKey(const Key('coach_roster_list_screen'))
              .evaluate()
              .isNotEmpty,
        );
        source.share('First text');
      },
      ready: (_) => find.byKey(const Key('shared_program_chooser')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        final BuildContext initialContext = current.element(
          find.byKey(const Key('shared_program_chooser')),
        );
        final router =
            ProviderScope.containerOf(initialContext).read(routerProvider);
        final int routeCount =
            router.routerDelegate.currentConfiguration.matches.length;
        expect(
          router.routeInformationProvider.value.uri.path,
          sharedProgramPath,
        );
        source.share('Replacement text');
        await current.pump();
        await current.pump(const Duration(milliseconds: 100));
        expect(
          router.routerDelegate.currentConfiguration.matches.length,
          routeCount,
        );
        final BuildContext context = current.element(
          find.byKey(const Key('shared_program_chooser')),
        );
        expect(
          ProviderScope.containerOf(context)
              .read(sharedProgramTextStoreProvider)
              .pending
              ?.text,
          'Replacement text',
        );
        await current.tap(find.text('bob').hitTestable());
        await _pumpUntil(
          current,
          () => find.byKey(const Key('coach_program_import_screen'))
              .evaluate()
              .isNotEmpty,
        );
        expect(
          current.widget<TextField>(
            find.byKey(const Key('program_import_paste_input')),
          ).controller!.text,
          'Replacement text',
        );
        expect(
          ProviderScope.containerOf(current.element(
            find.byKey(const Key('coach_program_import_screen')),
          )).read(sharedProgramTextStoreProvider).pending,
          isNull,
        );
      },
    );
  });

  testWidgets('signed-out sharing continues through sign-in and stays local',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Private chat text'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured
          ..tokenValid = false
          ..passwords['alice'] = 'password';
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('login_username')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      allowedInnerStrips: (_) => find.byType(TextField),
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).sharedProgramSignInRequired),
          findsNothing,
        );
        expect(fake.programImportRequests, 0);
        await current.enterText(
          find.byKey(const Key('login_username')),
          'alice',
        );
        await current.enterText(
          find.byKey(const Key('login_password')),
          'password',
        );
        await current.tap(find.byKey(const Key('login_submit')));
        await _pumpUntil(
          current,
          () => find.byKey(const Key('shared_program_chooser'))
              .evaluate()
              .isNotEmpty,
        );
        expect(
          find.text(CoachCopy(language).choosePlayerForSharedProgram),
          findsOneWidget,
        );
        expect(fake.programImportRequests, 0);
        final BuildContext context = current.element(
          find.byKey(const Key('shared_program_chooser')),
        );
        expect(
          ProviderScope.containerOf(context)
              .read(sharedProgramTextStoreProvider)
              .pending
              ?.text,
          'Private chat text',
        );
      },
    );
  });

  testWidgets('Player-only account sees localized Coach-only message',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Bench Press 3x8'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured..coach = false;
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('shared_program_chooser')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).sharedProgramCoachOnly),
          findsOneWidget,
        );
        expect(fake.programImportRequests, 0);
        await current.tap(find.text(CoachCopy(language).sharedProgramGoHome));
        await _pumpUntil(
          current,
          () {
            final BuildContext context = current.element(
              find.byType(MaterialApp).first,
            );
            return ProviderScope.containerOf(context)
                    .read(routerProvider)
                    .routeInformationProvider
                    .value
                    .uri
                    .path ==
                homePath;
          },
        );
      },
    );
  });

  testWidgets(
      'signed-out Player-only sharing returns to the Coach-only message',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Bench Press 3x8'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured
          ..coach = false
          ..tokenValid = false
          ..passwords['alice'] = 'password';
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('login_username')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      allowedInnerStrips: (_) => find.byType(TextField),
      assertions: (WidgetTester current, String language) async {
        await current.enterText(
          find.byKey(const Key('login_username')),
          'alice',
        );
        await current.enterText(
          find.byKey(const Key('login_password')),
          'password',
        );
        await current.tap(find.byKey(const Key('login_submit')));
        await _pumpUntil(
          current,
          () => find.byKey(const Key('shared_program_chooser'))
              .evaluate()
              .isNotEmpty,
        );
        expect(
          find.text(CoachCopy(language).sharedProgramCoachOnly),
          findsOneWidget,
        );
        expect(fake.programImportRequests, 0);
      },
    );
  });

  testWidgets('Player mode switches to Coach before showing shared chooser',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Bench Press 3x8'),
    );
    final InMemoryAppModeStore modeStore = InMemoryAppModeStore(
      <String, AppMode>{'account-alice': AppMode.player},
    );
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        fake.profileExists = false;
        _addPlayer(fake);
      },
      modeStore: modeStore,
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('shared_program_chooser')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(find.text('bob'), findsOneWidget);
        expect(modeStore.values['account-alice'], AppMode.coach);
      },
    );
  });

  testWidgets('file refusals show localized chooser messages',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText.refused(
        SharedProgramTextError.invalidUtf8,
      ),
    );
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) => _addPlayer(fake),
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (_) => find.byKey(const Key('shared_program_chooser')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).sharedProgramRefusal(
            SharedProgramTextError.invalidUtf8,
          )),
          findsOneWidget,
        );
      },
    );
  });

  for (final SharedProgramTextError error
      in SharedProgramTextError.values) {
    testWidgets('refusal ${error.code} can return to roster in both languages',
        (WidgetTester tester) async {
      final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
        initialText: SharedProgramText.refused(error),
      );
      await expectCoachPhoneLayout(
        tester,
        configureFake: (FakeMayosApi fake) => _addPlayer(fake),
        providerOverrides: <Override>[
          sharedProgramTextSourceProvider.overrideWithValue(source),
        ],
        ready: (String language) =>
            find.text(CoachCopy(language).sharedProgramRefusal(error)),
        pageScrollable: (_) => find.byType(Scrollable).first,
        assertions: (WidgetTester current, String language) async {
          await current.tap(
            find.text(CoachCopy(language).sharedProgramBackToRoster),
          );
          await _expectRosterAndClearedStore(current);
        },
      );
    });
  }

  testWidgets('unavailable shared text can return to roster in both languages',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource();
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) => _addPlayer(fake),
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      prepare: (WidgetTester current, String language) async {
        await _pumpUntil(
          current,
          () => find.byKey(const Key('coach_roster_list_screen'))
              .evaluate()
              .isNotEmpty,
        );
        final BuildContext context = current.element(
          find.byKey(const Key('coach_roster_list_screen')),
        );
        ProviderScope.containerOf(context).read(routerProvider).go(
              sharedProgramPath,
            );
      },
      ready: (String language) =>
          find.text(CoachCopy(language).sharedProgramUnavailable),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        await current.tap(
          find.text(CoachCopy(language).sharedProgramBackToRoster),
        );
        await _expectRosterAndClearedStore(current);
      },
    );
  });

  testWidgets('empty Coach roster can return to roster in both languages',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Squat 3x8'),
    );
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {},
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (String language) =>
          find.text(CoachCopy(language).noAssignedPlayers),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        await current.tap(
          find.text(CoachCopy(language).sharedProgramBackToRoster),
        );
        await _expectRosterAndClearedStore(current);
      },
    );
  });

  testWidgets('assignment failure actions are localized and retryable',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Squat 3x8'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured..coachAssignmentsNetworkFails = true;
        _addPlayer(fake);
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (String language) =>
          find.text(CoachCopy(language).sharedProgramAssignmentsUnavailable),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).sharedProgramRetry),
          findsOneWidget,
        );
        expect(
          find.text(CoachCopy(language).sharedProgramBackToRoster),
          findsOneWidget,
        );
        fake.coachAssignmentsNetworkFails = false;
        await current.tap(find.text(CoachCopy(language).sharedProgramRetry));
        await _pumpUntil(current, () => find.text('bob').evaluate().isNotEmpty);
        expect(
          ProviderScope.containerOf(current.element(
            find.byKey(const Key('shared_program_chooser')),
          )).read(sharedProgramTextStoreProvider).pending?.text,
          'Squat 3x8',
        );
      },
    );
  });

  testWidgets('assignment failure can return to roster in both languages',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Squat 3x8'),
    );
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi fake) {
        fake.coachAssignmentsNetworkFails = true;
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      ready: (String language) =>
          find.text(CoachCopy(language).sharedProgramAssignmentsUnavailable),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        await current.tap(
          find.text(CoachCopy(language).sharedProgramBackToRoster),
        );
        await _expectRosterAndClearedStore(current);
      },
    );
  });

  testWidgets('capability off shows unavailable state without sending text',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Bench Press 3x8'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured
          ..programImportTextAvailable = false;
        _addPlayer(fake);
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      prepare: (WidgetTester current, String language) =>
          _openChooserAndChoosePlayer(current),
      ready: (_) => find.byKey(const Key('coach_program_import_screen')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          find.text(CoachCopy(language).textImportUnavailable),
          findsOneWidget,
        );
        expect(fake.programImportRequests, 0);
      },
    );
  });

  testWidgets('over-cap shared text is prefilled and submit stays blocked',
      (WidgetTester tester) async {
    const int limit = 20000;
    final String overCapText = 'x' * (limit + 1);
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: SharedProgramText(overCapText),
    );
    final FakeMayosApi fake = createCoachFake()
      ..programImportResult['import_mode'] = 'text';
    _addPlayer(fake);
    await pumpCoachApp(
      tester,
      fake,
      logicalSize: const Size(360, 800),
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
    );
    await _pumpUntil(
      tester,
      () => find
          .byKey(const Key('shared_program_chooser'))
          .evaluate()
          .isNotEmpty,
    );
    await tester.tap(find.text('bob').hitTestable());
    await _pumpUntil(
      tester,
      () => find.byKey(const Key('coach_program_import_screen'))
          .evaluate()
          .isNotEmpty,
    );
    expect(
      tester.widget<TextField>(
        find.byKey(const Key('program_import_paste_input')),
      ).controller!.text,
      overCapText,
    );
    expect(
      find.text(CoachCopy('en').programImportOverLimit(limit)),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('program_import_submit_paste')));
    await tester.pump();
    expect(fake.programImportRequests, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'Coach chooses a Player and submits shared text in Arabic and English',
      (WidgetTester tester) async {
    final FakeSharedProgramTextSource source = FakeSharedProgramTextSource(
      initialText: const SharedProgramText('Day 1\nBench Press 3x8'),
    );
    late FakeMayosApi fake;
    await expectCoachPhoneLayout(
      tester,
      configureFake: (FakeMayosApi configured) {
        fake = configured;
        _addPlayer(fake);
        fake.programImportResult['import_mode'] = 'text';
      },
      providerOverrides: <Override>[
        sharedProgramTextSourceProvider.overrideWithValue(source),
      ],
      prepare: (WidgetTester current, String language) =>
          _openChooserAndChoosePlayer(current),
      ready: (_) => find.byKey(const Key('coach_program_import_screen')),
      pageScrollable: (_) => find.byType(Scrollable).first,
      assertions: (WidgetTester current, String language) async {
        expect(
          current.widget<TextField>(
            find.byKey(const Key('program_import_paste_input')),
          ).controller!.text,
          'Day 1\nBench Press 3x8',
        );
        await current.tap(find.byKey(const Key('program_import_submit_paste')));
        await _pumpUntil(
          current,
          () => fake.programImportRequests > 0,
        );
        expect(fake.programImportRequests, 1);
      },
    );
  });
}

void _addPlayer(FakeMayosApi fake) {
  fake.assignments.add(<String, dynamic>{
    'assignment_id': 'assignment-1',
    'player_username': 'bob',
    'started_at': '2026-10-01T00:00:00Z',
    'status': 'active',
  });
}

Future<void> _openChooserAndChoosePlayer(WidgetTester tester) async {
  await _pumpUntil(
    tester,
    () => find.byKey(const Key('shared_program_chooser')).evaluate().isNotEmpty,
  );
  await tester.tap(find.text('bob').hitTestable());
  await _pumpUntil(
    tester,
    () => find.byKey(const Key('coach_program_import_screen'))
        .evaluate()
        .isNotEmpty,
  );
}

Future<void> _expectRosterAndClearedStore(WidgetTester tester) async {
  await _pumpUntil(
    tester,
    () => find.byKey(const Key('coach_roster_list_screen'))
        .evaluate()
        .isNotEmpty,
  );
  final BuildContext context = tester.element(
    find.byKey(const Key('coach_roster_list_screen')),
  );
  expect(
    ProviderScope.containerOf(context)
        .read(sharedProgramTextStoreProvider)
        .pending,
    isNull,
  );
}

Future<void> _pumpUntil(WidgetTester tester, bool Function() condition) async {
  for (int attempt = 0; attempt < 60 && !condition(); attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(condition(), isTrue);
}
