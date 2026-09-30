import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/ui/mayos_button.dart';
import 'package:mayos_mobile/src/core/ui/mayos_player_column.dart';
import 'package:mayos_mobile/src/core/ui/mayos_choice_card.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_screen.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_widgets.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';

const Map<String, Object> _requiredAnswers = <String, Object>{
  'gender': 'female',
  'proportions': 'long_legs',
  'age': 29,
  'height_cm': 168.0,
  'weight_kg': 64.5,
  'training_age_years': 3.0,
  'current_goal': 'build glutes and legs',
  'long_term_goal': 'stronger and more muscular',
  'weekly_frequency': 4,
  'equipment_access': 'Commercial gym',
  'injuries_or_limitations': 'None',
  'stress_and_sleep': 'moderate stress, 7 hours sleep',
};

FakeMayosApi _fake({bool acknowledged = false}) {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = false;
  fake.intakeDisclosureAcknowledged = acknowledged;
  return fake;
}

typedef _OnboardingViewport = ({
  Size size,
  ThemeMode mode,
  double textScale,
});

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

Override _apiOverride(FakeMayosApi fake) {
  return apiClientProvider.overrideWith((ref) {
    final ApiClient client = ApiClient(
      tokens: ref.watch(tokenStoreProvider),
      baseUrl: 'http://test.local',
      adapter: fake.adapter,
    );
    client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
    client.onAccountDeleted = ref.watch(accountDeletedEventsProvider).signal;
    return client;
  });
}

Future<InMemoryTokenStore> _signedInTokens() async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  return tokens;
}

Future<void> _pumpOnboarding(
  WidgetTester tester,
  FakeMayosApi fake, {
  Size size = const Size(393, 852),
  ThemeMode mode = ThemeMode.light,
  double textScale = 1.0,
}) async {
  await _mountOnboarding(
    tester,
    fake,
    viewport: (size: size, mode: mode, textScale: textScale),
  );
  await _pumpUntilFound(tester, find.byType(OnboardingScaffold));
}

Future<void> _mountOnboarding(
  WidgetTester tester,
  FakeMayosApi fake, {
  _OnboardingViewport? viewport,
}) async {
  final _OnboardingViewport view = viewport ??
      (
        size: const Size(393, 852),
        mode: ThemeMode.light,
        textScale: 1.0,
      );
  final Size size = view.size;
  final double textScale = view.textScale;
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  if (textScale != 1.0) {
    tester.platformDispatcher.textScaleFactorTestValue = textScale;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  }
  final InMemoryTokenStore tokens = await _signedInTokens();
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        _apiOverride(fake),
      ],
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: MayosTheme.light,
        darkTheme: MayosTheme.dark,
        themeMode: view.mode,
        home: const OnboardingScreen(),
      ),
    ),
  );
}

void _expectDesktopPlayerColumn(WidgetTester tester) {
  final Rect column = tester.getRect(
    find.byKey(MayosPlayerColumn.contentKey),
  );
  expect(column.width, 480);
  expect(column.center.dx, 640);
}

Future<void> _tapAndFind(WidgetTester tester, Finder tap, Finder next) async {
  await tester.tap(tap);
  await tester.pump(const Duration(milliseconds: 50));
  await _pumpUntilFound(tester, next);
  // Let the shared step transition (220ms) finish before asserting on the
  // settled screen, so the outgoing step is disposed.
  await tester.pump(const Duration(milliseconds: 260));
}

bool _continueEnabled(WidgetTester tester) {
  final MayosButton button = tester.widget<MayosButton>(
    find.byKey(const Key('onboarding_continue')),
  );
  return button.onPressed != null;
}

/// Walks every field from the gender step through to the review screen.
Future<void> _answerAll(WidgetTester tester,
    {bool skipRepPreference = false}) async {
  await _tapAndFind(tester, find.byKey(const Key('gender_option_female')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('proportions_option_long_legs')));
  await _tapAndFind(
      tester,
      find.byKey(const Key('proportions_option_long_legs')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('age_increment')));
  await _tapAndFind(tester, find.byKey(const Key('age_increment')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('height_cm_increment')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('weight_kg_increment')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('training_age_years_increment')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('current_goal_input')));
  await _tapAndFind(tester, find.byKey(const Key('current_goal_example_0')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('long_term_goal_input')));
  await _tapAndFind(tester, find.byKey(const Key('long_term_goal_example_0')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('weekly_frequency_option_4')));
  await _tapAndFind(tester, find.byKey(const Key('weekly_frequency_option_4')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('equipment_access_option_Commercial gym')));
  await _tapAndFind(
      tester,
      find.byKey(const Key('equipment_access_option_Commercial gym')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('injuries_or_limitations_input')));
  await _tapAndFind(
      tester,
      find.byKey(const Key('injuries_or_limitations_example_0')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('stress_and_sleep_input')));
  await _tapAndFind(tester, find.byKey(const Key('stress_and_sleep_example_0')),
      find.byKey(const Key('onboarding_continue')));
  await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
      find.byKey(const Key('rep_preference_option_balanced')));
  if (skipRepPreference) {
    await _tapAndFind(tester, find.byKey(const Key('onboarding_skip')),
        find.byKey(const Key('onboarding_confirm')));
  } else {
    await _tapAndFind(
        tester,
        find.byKey(const Key('rep_preference_option_balanced')),
        find.byKey(const Key('onboarding_continue')));
    await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
        find.byKey(const Key('onboarding_confirm')));
  }
}

void main() {
  testWidgets('the disclosure gates every answer', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    await _pumpOnboarding(tester, fake);

    expect(find.byKey(const Key('onboarding_disclosure_continue')),
        findsOneWidget);
    expect(find.text('Hosted AI processing'), findsOneWidget);
    expect(find.byKey(const Key('onboarding_continue')), findsNothing);
    expect(fake.intakeAnswers, isEmpty);
    expect(fake.intakeDisclosureAcknowledged, isFalse);

    await _tapAndFind(
        tester,
        find.byKey(const Key('onboarding_disclosure_continue')),
        find.byKey(const Key('gender_option_female')));
    expect(fake.intakeDisclosureAcknowledged, isTrue);
    expect(find.text(questionFor('gender')), findsOneWidget);
  });

  testWidgets('raw onboarding loading state uses the desktop player column',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake();
    final Completer<void> pending = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.method == 'GET' && request.path == '/onboarding/intake') {
        await pending.future;
      }
    };
    await _mountOnboarding(
      tester,
      fake,
      viewport: (
        size: const Size(1280, 800),
        mode: ThemeMode.light,
        textScale: 1.0,
      ),
    );
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    _expectDesktopPlayerColumn(tester);
    pending.complete();
    await _pumpUntilFound(tester, find.byType(OnboardingScaffold));
  });

  testWidgets('raw onboarding error state uses the desktop player column',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake()
      ..failOffline('GET', '/onboarding/intake');
    await _mountOnboarding(
      tester,
      fake,
      viewport: (
        size: const Size(1280, 800),
        mode: ThemeMode.light,
        textScale: 1.0,
      ),
    );
    await _pumpUntilFound(tester, find.text('Could not load your setup'));

    _expectDesktopPlayerColumn(tester);
    expect(tester.takeException(), isNull);
  });

  testWidgets('program-building state uses the desktop player column',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..intakeAnswers.addAll(_requiredAnswers);
    await _pumpOnboarding(
      tester,
      fake,
      size: const Size(1280, 800),
    );
    await _pumpUntilFound(tester, find.byKey(const Key('onboarding_confirm')));

    final Completer<void> pending = Completer<void>();
    fake.adapter.beforeRespond = (request) async {
      if (request.method == 'POST' &&
          request.path == '/onboarding/intake/confirm') {
        await pending.future;
      }
    };
    fake.failOffline('POST', '/onboarding/intake/confirm');
    await tester.tap(find.byKey(const Key('onboarding_confirm')));
    await _pumpUntilFound(tester, find.text('Building your program'));

    _expectDesktopPlayerColumn(tester);
    expect(tester.takeException(), isNull);
    pending.complete();
    await _pumpUntilFound(tester, find.byType(OnboardingScaffold));
  });

  testWidgets('each field type selects and saves its answer',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true);
    await _pumpOnboarding(tester, fake);

    await _answerAll(tester);

    expect(fake.intakeAnswers['gender'], 'female');
    expect(fake.intakeAnswers['proportions'], 'long_legs');
    expect(fake.intakeAnswers['age'], 31);
    expect(fake.intakeAnswers['current_goal'], 'build glutes and legs');
    expect(fake.intakeAnswers['weekly_frequency'], 4);
    expect(fake.intakeAnswers['injuries_or_limitations'], 'None');
    expect(fake.intakeAnswers['rep_preference'], 'balanced');
    expect(find.byKey(const Key('onboarding_confirm')), findsOneWidget);
  });

  testWidgets('enum option descriptions come from the API, not widgets',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true);
    await _pumpOnboarding(tester, fake);

    // Gender cards carry the per-value training effect from the schema.
    expect(
      find.text('Glute- and lower-body-focused by frequency: '
          'glute-specialised full body at 1-3 days, lower-body (glute bias) '
          'and upper body + core at 4-5 days.'),
      findsOneWidget,
    );

    await _tapAndFind(tester, find.byKey(const Key('gender_option_female')),
        find.byKey(const Key('onboarding_continue')));
    await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
        find.byKey(const Key('proportions_option_long_legs')));
    expect(find.text('Proportional upper and lower body'), findsOneWidget);
  });

  testWidgets('an optional field can be skipped', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true);
    await _pumpOnboarding(tester, fake);
    await _answerAll(tester, skipRepPreference: true);
    expect(fake.intakeAnswers.containsKey('rep_preference'), isFalse);
    expect(find.byKey(const Key('onboarding_confirm')), findsOneWidget);
  });

  testWidgets(
      'numeric validation blocks Continue and server errors show inline',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..intakeAnswers.addAll(
          <String, Object>{'gender': 'female', 'proportions': 'balanced'});
    await _pumpOnboarding(tester, fake);

    // Resume lands on the first unanswered required field: age.
    expect(find.text(questionFor('age')), findsOneWidget);
    expect(_continueEnabled(tester), isTrue);

    await _tapAndFind(tester, find.byKey(const Key('age_direct_toggle')),
        find.byKey(const Key('age_input')));
    await tester.enterText(find.byKey(const Key('age_input')), '5');
    await tester.pump();
    expect(_continueEnabled(tester), isFalse);

    // A value the server refuses shows its message and keeps the step.
    fake.intakeRejectField = 'age';
    await tester.enterText(find.byKey(const Key('age_input')), '29');
    await tester.pump();
    expect(_continueEnabled(tester), isTrue);
    await tester.tap(find.byKey(const Key('onboarding_continue')));
    await _pumpUntilFound(tester, find.text(fake.intakeRejectMessage));
    expect(find.text(fake.intakeRejectMessage), findsOneWidget);
    expect(fake.intakeAnswers.containsKey('age'), isFalse);
  });

  testWidgets('Back keeps saved answers', (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true);
    await _pumpOnboarding(tester, fake);

    await _tapAndFind(tester, find.byKey(const Key('gender_option_female')),
        find.byKey(const Key('onboarding_continue')));
    await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
        find.byKey(const Key('proportions_option_long_legs')));
    expect(fake.intakeAnswers['gender'], 'female');

    await _tapAndFind(tester, find.byKey(const Key('onboarding_back')),
        find.byKey(const Key('gender_option_female')));
    final MayosChoiceCard card = tester
        .widget<MayosChoiceCard>(find.byKey(const Key('gender_option_female')));
    expect(card.selected, isTrue);
    expect(_continueEnabled(tester), isTrue);
  });

  testWidgets('resume opens at the first unanswered required field',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..intakeAnswers.addAll(<String, Object>{
        'gender': 'female',
        'proportions': 'balanced',
      });
    await _pumpOnboarding(tester, fake);

    expect(find.text(questionFor('age')), findsOneWidget);
    await _tapAndFind(tester, find.byKey(const Key('onboarding_back')),
        find.byKey(const Key('proportions_option_balanced')));
    expect(
      tester.getSemantics(find.byKey(const Key('proportions_option_balanced'))),
      isSemantics(isSelected: true, isButton: true),
    );
  });

  testWidgets('an answer can be edited from review and returns to review',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..intakeAnswers.addAll(_requiredAnswers);
    await _pumpOnboarding(tester, fake);

    expect(find.byKey(const Key('onboarding_confirm')), findsOneWidget);
    await _tapAndFind(tester, find.byKey(const Key('review_edit_gender')),
        find.byKey(const Key('gender_option_male')));
    expect(find.byKey(const Key('gender_option_male')), findsOneWidget);

    await _tapAndFind(tester, find.byKey(const Key('gender_option_male')),
        find.byKey(const Key('onboarding_continue')));
    await _tapAndFind(tester, find.byKey(const Key('onboarding_continue')),
        find.byKey(const Key('onboarding_confirm')));
    expect(fake.intakeAnswers['gender'], 'male');
    expect(find.text('Male'), findsOneWidget);
  });

  testWidgets('an offline failure keeps the answer on the step',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..intakeAnswers.addAll(<String, Object>{
        'gender': 'female',
        'proportions': 'balanced',
        'age': 30,
        'height_cm': 175.0,
        'weight_kg': 75.0,
        'training_age_years': 2.0,
      });
    await _pumpOnboarding(tester, fake);

    expect(find.byKey(const Key('current_goal_input')), findsOneWidget);
    fake.failOffline('PUT', '/onboarding/intake/answers/current_goal');
    await _tapAndFind(tester, find.byKey(const Key('current_goal_example_0')),
        find.byKey(const Key('onboarding_continue')));
    await tester.tap(find.byKey(const Key('onboarding_continue')));
    await _pumpUntilFound(tester, find.text(needsConnectionMessage));

    expect(find.text(needsConnectionMessage), findsOneWidget);
    expect(find.text('build glutes and legs'), findsWidgets);
    expect(fake.intakeAnswers.containsKey('current_goal'), isFalse);
  });

  testWidgets('confirm only acts from review and lands on Home',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _fake(acknowledged: true)
      ..recoveryEmail = 'alice@example.com'
      ..intakeAnswers.addAll(_requiredAnswers);
    tester.view.physicalSize = const Size(393, 852);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final InMemoryTokenStore tokens = await _signedInTokens();

    await tester.pumpWidget(
      ProviderScope(
        overrides: <Override>[
          tokenStoreProvider.overrideWithValue(tokens),
          appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
          themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore()),
          draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
          workoutCacheStoreProvider
              .overrideWithValue(InMemoryWorkoutCacheStore()),
          chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
          _apiOverride(fake),
        ],
        child: const MayosApp(),
      ),
    );

    await _pumpUntilFound(tester, find.byKey(const Key('onboarding_confirm')));
    await tester.tap(find.byKey(const Key('onboarding_confirm')));
    await _pumpUntilFound(tester, find.textContaining('Next session'));

    expect(find.textContaining('Next session'), findsOneWidget);
    expect(fake.intakeStatus, 'confirmed');
    expect(fake.profileExists, isTrue);
  });

  for (final Size size in const <Size>[
    Size(360, 640),
    Size(393, 852),
    Size(412, 915),
  ]) {
    testWidgets(
        'proportions and a numeric step do not overflow at '
        '${size.width.toInt()}x${size.height.toInt()} with 2.0x text',
        (WidgetTester tester) async {
      final FakeMayosApi fake = _fake(acknowledged: true)
        ..intakeAnswers['gender'] = 'female';
      await _pumpOnboarding(tester, fake, size: size, textScale: 2.0);

      expect(find.text(questionFor('proportions')), findsOneWidget);
      expect(tester.takeException(), isNull);

      await tester
          .ensureVisible(find.byKey(const Key('proportions_option_balanced')));
      await tester.tap(find.byKey(const Key('proportions_option_balanced')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('onboarding_continue')));
      await _pumpUntilFound(tester, find.text(questionFor('age')));
      expect(tester.takeException(), isNull);
    });
  }
}
