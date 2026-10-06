import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/providers.dart';
import 'package:mayos_mobile/src/features/player/workout/active_workout_controller.dart';

import 'support/fake_mayos_api.dart';

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

Future<T> _waitWithPumps<T>(WidgetTester tester, Future<T> operation) async {
  bool completed = false;
  operation.then((_) => completed = true, onError: (Object error) {
    completed = true;
  });
  for (int attempt = 0; attempt < 80 && !completed; attempt++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  return operation;
}

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = true;
  fake.recoveryEmail = 'alice@example.com';
  return fake;
}

Future<void> _pumpProgram(
  WidgetTester tester,
  FakeMayosApi fake, {
  ThemeMode mode = ThemeMode.light,
  Size size = const Size(1080, 2400),
  ActiveWorkoutStore? activeWorkoutStore,
  WorkoutCacheStore? workoutCacheStore,
  String languageCode = 'en',
}) async {
  fake.displayLanguage = languageCode;
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        systemDisplayLanguageProvider.overrideWithValue(languageCode),
        themeModeStoreProvider.overrideWithValue(InMemoryThemeModeStore(mode)),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        if (activeWorkoutStore != null)
          activeWorkoutStoreProvider.overrideWithValue(activeWorkoutStore),
        workoutCacheStoreProvider.overrideWithValue(
          workoutCacheStore ?? InMemoryWorkoutCacheStore(),
        ),
        baselineCacheStoreProvider
            .overrideWithValue(InMemoryBaselineCacheStore()),
        chatCacheStoreProvider.overrideWithValue(InMemoryChatCacheStore()),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fake.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: const MayosApp(),
    ),
  );
  await _pumpUntilFound(
      tester, find.text(languageCode == 'ar' ? 'الرئيسية' : 'Home'));
  await tester.pump(const Duration(milliseconds: 400));
  await tester
      .tap(find.text(languageCode == 'ar' ? 'البرنامج التدريبي' : 'Program'));
  await _pumpUntilFound(
    tester,
    find.text(fake.noActiveProgram
        ? languageCode == 'ar'
            ? 'لا يوجد برنامج تدريبي نشط بعد. أكمل إعدادك لإنشاء برنامج.'
            : 'No active program yet. Complete onboarding to build one.'
        : languageCode == 'ar'
            ? 'اليوم 1: Upper 1'
            : 'Day 1: Upper 1'),
  );

  // Resize after navigating so the layout is exercised at the target size
  // without depending on bottom-bar hit-testing at the small viewport.
  if (size != const Size(1080, 2400)) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _expectProgramChangeSummary(
  WidgetTester tester,
  String languageCode, {
  bool unchanged = false,
}) async {
  final FakeMayosApi fake = _signedInFake();
  fake.playerNotices.add(<String, dynamic>{
    'notice_id': 'published-1',
    'kind': 'program_published',
    'message': 'Your coach published program version 2.',
    'created_at': '2026-10-05T10:00:00Z',
    'read_at': '2026-10-05T10:01:00Z',
    'summary_dismissed_at': null,
    'program_change_summary': <String, dynamic>{
      'version': 1,
      'unchanged': unchanged,
      'changes': unchanged
          ? <dynamic>[]
          : <Map<String, dynamic>>[
              <String, dynamic>{
                'type': 'exercise_replaced',
                'day': 'Lower 1',
                'before': 'Back Squat',
                'after': 'Safety Bar Squat',
              },
              for (int index = 1; index <= 11; index++)
                <String, dynamic>{
                  'type': 'exercise_added',
                  'day': 'Upper 1',
                  'exercise': 'Exercise $index',
                },
            ],
    },
  });
  await _pumpProgram(tester, fake, languageCode: languageCode);
  if (unchanged) {
    final Finder approval = find.text(languageCode == 'ar'
        ? 'وافق مدربك على برنامجك التدريبي الحالي.'
        : 'Your coach approved your current program.');
    await _pumpUntilFound(tester, approval);
    expect(approval, findsOneWidget);
    expect(find.text(languageCode == 'ar' ? 'إخفاء' : 'Dismiss'), findsOneWidget);
    return;
  }
  final Finder replacement = find.textContaining(languageCode == 'ar'
      ? 'استبدال Back Squat بـ Safety Bar Squat في Lower 1'
      : 'Back Squat → Safety Bar Squat on Lower 1');
  await _pumpUntilFound(tester, replacement);
  expect(replacement, findsOneWidget);
  expect(
    find.text(languageCode == 'ar' ? 'والمزيد من التغييرات: 2' : 'and 2 more'),
    findsOneWidget,
  );
  expect(find.textContaining('Exercise 10'), findsNothing);

  await tester.tap(find.text(languageCode == 'ar' ? 'إخفاء' : 'Dismiss'));
  await tester.pumpAndSettle();
  expect(replacement, findsNothing);
  expect(fake.dismissedPlayerNoticeIds, <String>['published-1']);
  expect(fake.playerNotices.first['summary_dismissed_at'], isNotNull);
  expect(fake.playerNotices.first['read_at'], '2026-10-05T10:01:00Z');
  expect(fake.markPlayerNoticesReadRequests, 0);
}

Future<void> _expectOtherDetailsSummary(
  WidgetTester tester,
  String languageCode,
) async {
  final FakeMayosApi fake = _signedInFake();
  fake.playerNotices.add(<String, dynamic>{
    'notice_id': 'other-details-1',
    'kind': 'program_published',
    'message': 'Your coach published program version 3.',
    'created_at': '2026-10-05T10:00:00Z',
    'read_at': null,
    'summary_dismissed_at': null,
    'program_change_summary': <String, dynamic>{
      'version': 1,
      'unchanged': false,
      'changes': <Map<String, dynamic>>[
        <String, dynamic>{'type': 'other_details_changed'},
      ],
    },
  });
  await _pumpProgram(tester, fake, languageCode: languageCode);
  final Finder generic = find.textContaining(languageCode == 'ar'
      ? 'حدّث مدربك أيضًا تفاصيل أخرى في البرنامج التدريبي.'
      : 'Your coach also updated other program details.');
  await _pumpUntilFound(tester, generic);
  expect(generic, findsOneWidget);
  expect(
    find.text(languageCode == 'ar'
        ? 'وافق مدربك على برنامجك التدريبي الحالي.'
        : 'Your coach approved your current program.'),
    findsNothing,
  );
}

Future<void> _expectPrescriptionFormatting(
  WidgetTester tester,
  String languageCode,
) async {
  final FakeMayosApi fake = _signedInFake();
  fake.playerNotices.add(<String, dynamic>{
    'notice_id': 'prescription-1',
    'kind': 'program_published',
    'message': 'Your coach published program version 3.',
    'created_at': '2026-10-05T10:00:00Z',
    'read_at': null,
    'summary_dismissed_at': null,
    'program_change_summary': <String, dynamic>{
      'version': 1,
      'unchanged': false,
      'changes': <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'prescription_changed',
          'day': 'Upper 1',
          'exercise': 'Bench Press',
          'fields': <String, dynamic>{
            'reps': <String, dynamic>{'before': '8', 'after': '10'},
            'rir': <String, dynamic>{'before': 1.5, 'after': 2},
          },
        },
      ],
    },
  });
  await _pumpProgram(tester, fake, languageCode: languageCode);
  final Finder prescription = find.textContaining(languageCode == 'ar'
      ? 'Bench Press (Upper 1): التكرارات 8 → 10، RIR 1.5 → 2'
      : 'Bench Press (Upper 1): reps 8 → 10, RIR 1.5 → 2');
  await _pumpUntilFound(tester, prescription);
  expect(prescription, findsOneWidget);
}

Future<void> _openSubstitutePicker(WidgetTester tester) async {
  await tester.drag(find.byType(ListView).first, const Offset(0, -180));
  await tester.pumpAndSettle();
  final Finder moreActions = find.byTooltip('More actions for Bench Press');
  await tester.ensureVisible(moreActions);
  await tester.tap(moreActions);
  await tester.pumpAndSettle();
  await tester.tap(find.text('Substitute exercise'));
  await tester.pumpAndSettle();
  await _pumpUntilFound(tester, find.text('Cable Fly'));
  expect(
    find.byKey(const Key('exercise_primary_muscle_filter')),
    findsOneWidget,
  );
  expect(find.text('Muscle: Chest'), findsOneWidget);
  expect(
    find.descendant(
      of: find.byType(AlertDialog),
      matching: find.text('Bench Press'),
    ),
    findsNothing,
  );
}

Future<void> _chooseCableFly(WidgetTester tester) async {
  await _openSubstitutePicker(tester);
  await tester.tap(find.text('Cable Fly'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Player sees Coach exercise details without offering it as a substitute',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.coachExerciseRows.add(<String, dynamic>{
      'id': 'coach:pin-squat',
      'name': 'Pin Squat',
      'body_part': 'Quads',
      'equipment': 'barbell',
      'note': 'Pause on the pins.',
      'video_url': 'https://example.com/pin-squat',
      'image_path': null,
      'gif_path': null,
      'is_coach_exercise': true,
    });
    fake.programDaysOverride = <Map<String, dynamic>>[
      <String, dynamic>{
        'day_name': 'Lower 1',
        'day_order': 1,
        'warmup_exercises': <dynamic>[],
        'exercises': <Map<String, dynamic>>[
          <String, dynamic>{
            'exercise_id': 'coach:pin-squat',
            'exercise_name': 'Pin Squat',
            'body_part': 'Quads',
            'equipment': 'barbell',
            'note': 'Pause on the pins.',
            'video_url': 'https://example.com/pin-squat',
            'is_coach_exercise': true,
            'target_sets': 2,
            'target_reps_min': 5,
            'target_reps_max': 8,
            'target_rpe': 8.0,
            'rest_seconds': 180,
            'suggested_substitutes': <dynamic>[],
          },
        ],
      },
    ];

    await _pumpProgram(tester, fake);
    expect(find.text('Pause on the pins.'), findsOneWidget);
    expect(find.text('Watch exercise video'), findsOneWidget);

    final Finder actions = find.byTooltip('More actions for Pin Squat');
    await tester.ensureVisible(actions);
    await tester.tap(actions);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Substitute exercise'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Replace exercise'));
    await tester.enterText(find.byType(TextField).last, 'Pin Squat');
    await tester.tap(find.text('Search').last);
    await _pumpUntilFound(tester, find.text('No matching exercise found.'));
    final request = fake.adapter.requests.lastWhere(
      (candidateRequest) => candidateRequest.path == '/workouts/exercises',
    );
    expect(request.query['replacing_exercise_id'], 'coach:pin-squat');
    expect(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byIcon(Icons.fitness_center),
      ),
      findsNothing,
    );
  });

  testWidgets(
      'Arabic program labels translate while split and exercise names remain',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake, languageCode: 'ar');
    expect(find.text('اليوم 1: Upper 1'), findsOneWidget);
    expect(find.text('مجموعات التدريب'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(find.textContaining('4 أيام في الأسبوع'), findsOneWidget);
    final Finder warmupPrescription =
        find.text('\u20662 × 15\u2069 · راحة \u206645\u2069 ثانية');
    expect(warmupPrescription, findsOneWidget);
    expect(
      Directionality.of(tester.element(warmupPrescription)),
      TextDirection.rtl,
    );
    expect(find.text('2 × 15 · rest 45s'), findsNothing);
    expect(Directionality.of(tester.element(find.text('مجموعات التدريب'))),
        TextDirection.rtl);
    expect(
      find.text('هل تريد برنامجًا تدريبيًا مختلفًا؟ اسأل المساعد.'),
      findsOneWidget,
    );
    expect(find.text('إنشاء البرنامج التدريبي من جديد'), findsNothing);
  });

  testWidgets('without a coach, player authority points to the assistant chat',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    expect(find.textContaining('preparing your program'), findsNothing);
    expect(
      find.text('Want a different program? Ask the assistant.'),
      findsOneWidget,
    );
    expect(find.text('Ask the assistant'), findsOneWidget);
    expect(find.text('Regenerate program'), findsNothing);

    await tester.tap(find.text('Ask the assistant'));
    await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
    expect(find.byKey(const Key('chat_composer')), findsOneWidget);
  });

  testWidgets('assigned player sees the named coach preparing the program',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);

    expect(
      find.text(
        "Your coach, Coach Alice, is preparing your program. You're on a starting program until then.",
      ),
      findsOneWidget,
    );
  });

  testWidgets('published program hides the preparing banner', (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..coachPreparingProgram = false
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake);

    expect(find.textContaining('preparing your program'), findsNothing);
  });

  testWidgets('ending the assignment removes the preparing banner',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);
    expect(find.textContaining('preparing your program'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));
    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('My coach'));
    await tester.tap(find.widgetWithText(OutlinedButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('Leave coach?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('Invite code from your coach'));

    await tester.binding.handlePopRoute();
    await _pumpUntilFound(tester, find.text('Appearance'));
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));

    expect(find.textContaining('preparing your program'), findsNothing);
  });

  testWidgets('Home removes the preparing banner after the player ends assignment',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);
    await tester.tap(find.text('Home'));
    await _pumpUntilFound(tester, find.text('Coach Alice'));
    expect(find.textContaining('preparing your program'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await _pumpUntilFound(tester, find.text('Appearance'));
    await tester.tap(find.byIcon(Icons.badge_outlined));
    await _pumpUntilFound(tester, find.text('My coach'));
    await tester.tap(find.widgetWithText(OutlinedButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('Leave coach?'));
    await tester.tap(find.widgetWithText(FilledButton, 'Leave coach'));
    await _pumpUntilFound(tester, find.text('Invite code from your coach'));

    await tester.binding.handlePopRoute();
    await _pumpUntilFound(tester, find.text('Appearance'));
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    expect(find.textContaining('preparing your program'), findsNothing);
  });

  testWidgets('Home shows the preparing banner above its program card',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);
    await tester.tap(find.text('Home'));
    await _pumpUntilFound(tester, find.text('Coach Alice'));

    expect(
      find.text(
        "Your coach, Coach Alice, is preparing your program. You're on a starting program until then.",
      ),
      findsOneWidget,
    );
  });

  testWidgets('Home hides the preparing banner after coach publication',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..coachPreparingProgram = false
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake);
    await tester.tap(find.text('Home'));
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));

    expect(find.textContaining('preparing your program'), findsNothing);
  });

  testWidgets('Home tab switch refreshes only the assignment', (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);
    final int assignmentRequests = fake.myAssignmentRequests;
    final int programRequests = fake.activeProgramRequests;

    await tester.tap(find.text('Home'));
    await _pumpUntilFound(tester, find.text('Coach Alice'));

    expect(fake.myAssignmentRequests, assignmentRequests + 1);
    expect(fake.activeProgramRequests, programRequests);
  });

  testWidgets('Program tab refresh hides the banner after coach ends assignment',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);
    expect(find.textContaining('preparing your program'), findsOneWidget);

    await tester.tap(find.text('Home'));
    await _pumpUntilFound(tester, find.text('Coach Alice'));
    fake.activeAssignmentId = null;
    final int assignmentRequests = fake.myAssignmentRequests;
    final int programRequests = fake.activeProgramRequests;

    await tester.tap(find.text('Program'));
    await _pumpUntilFound(tester, find.text('Day 1: Upper 1'));

    expect(fake.myAssignmentRequests, assignmentRequests + 1);
    expect(fake.activeProgramRequests, programRequests);
    expect(find.textContaining('preparing your program'), findsNothing);
  });

  testWidgets('Arabic preparing banner names the coach in Display language',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake, languageCode: 'ar');

    expect(
      find.text(
        'مدربك Coach Alice يُعدّ برنامجك التدريبي. ستتدرب على برنامج مبدئي حتى ذلك الحين.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('an unpublished assignment still leaves program authority with the player',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice';
    await _pumpProgram(tester, fake);

    expect(
      find.text('Want a different program? Ask the assistant.'),
      findsOneWidget,
    );
    expect(find.text('Your coach manages this program.'), findsNothing);
    expect(find.text('Ask the assistant'), findsOneWidget);
  });

  testWidgets('coach authority opens the program change request flow',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake);

    expect(find.text('Your coach manages this program.'), findsOneWidget);
    expect(find.text('Want a different program? Ask the assistant.'), findsNothing);
    expect(find.text('Published by your coach'), findsOneWidget);
    expect(find.text('Regenerate program'), findsNothing);

    await tester.tap(find.text('Request a change'));
    await tester.pumpAndSettle();
    expect(find.text('Request a program change'), findsOneWidget);

    await tester.tap(find.byKey(const Key('program_request_kind_field')));
    await tester.pumpAndSettle();
    expect(find.text('Split change'), findsOneWidget);
    await tester.tap(find.text('Split change'));
    await tester.enterText(
      find.byKey(const Key('program_request_reason_field')),
      'I would prefer a different split.',
    );
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pumpAndSettle();
    await _pumpUntilFound(
      tester,
      find.text('Your program change request was sent to your coach.'),
    );

    expect(fake.programRequests, hasLength(1));
    expect(fake.programRequests.single, containsPair('kind', 'split_change'));
    expect(fake.programRequests.single,
        containsPair('desired_weekly_frequency', 4));
  });

  testWidgets('Arabic coach authority message uses the coaching vocabulary',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake, languageCode: 'ar');

    expect(find.text('يدير مدربك هذا البرنامج التدريبي.'), findsOneWidget);
    expect(find.text('طلب تغيير'), findsOneWidget);
    expect(find.text('إنشاء البرنامج التدريبي من جديد'), findsNothing);
  });

  testWidgets('empty Program state opens the assistant in English and Arabic',
      (tester) async {
    for (final String languageCode in <String>['en', 'ar']) {
      final FakeMayosApi fake = _signedInFake()..noActiveProgram = true;
      await _pumpProgram(
        tester,
        fake,
        languageCode: languageCode,
      );

      final String openAssistant =
          languageCode == 'ar' ? 'فتح المساعد' : 'Open assistant';
      expect(find.text(openAssistant), findsOneWidget);
      expect(find.text('Regenerate program'), findsNothing);
      expect(find.text('إنشاء البرنامج التدريبي من جديد'), findsNothing);

      await tester.tap(find.text(openAssistant));
      await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
      expect(find.byKey(const Key('chat_composer')), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('Arabic Program translates app-composed deload labels',
      (WidgetTester tester) async {
    final FakeMayosApi fake = _signedInFake()..prescriptionOffline = true;
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writePrescription(
      'account-alice',
      1,
      const Prescription(
        deload: DeloadDecision(
          state: DeloadState.suggested,
          reason: 'Acute readiness floor (1/5 logged).',
          volumeMultiplier: 0.5,
          intensityCapRpe: 7.0,
        ),
        targets: <PrescriptionTarget>[],
      ),
    );
    await _pumpProgram(
      tester,
      fake,
      languageCode: 'ar',
      workoutCacheStore: cache,
    );
    await _pumpUntilFound(tester, find.text('اقتُرح تخفيف التدريب'));

    expect(find.text('اقتُرح تخفيف التدريب'), findsOneWidget);
    expect(find.text('Acute readiness floor (1/5 logged).'), findsOneWidget);
    final Finder deloadSummary = find.text(
      'عند التطبيق: خُفضت المجموعات إلى \u206650%\u2069 من البرنامج · '
      'ضُبط الجهد عند RIR \u2066≥ 3\u2069. أُبلغ مدربك.',
    );
    expect(deloadSummary, findsOneWidget);
    expect(tester.widget<Text>(deloadSummary).textDirection, isNull);
    expect(
      Directionality.of(tester.element(deloadSummary)),
      TextDirection.rtl,
    );
    expect(find.text('اسأل المساعد'), findsNWidgets(2));
  });

  testWidgets('program shows a suggested deload and opens the assistant',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()..prescriptionOffline = true;
    final InMemoryWorkoutCacheStore cache = InMemoryWorkoutCacheStore();
    await cache.writePrescription(
      'account-alice',
      1,
      const Prescription(
        deload: DeloadDecision(
          state: DeloadState.suggested,
          reason: 'Acute readiness floor (1/5 logged).',
          volumeMultiplier: 0.5,
          intensityCapRpe: 7.0,
        ),
        targets: <PrescriptionTarget>[],
      ),
    );
    await _pumpProgram(tester, fake, workoutCacheStore: cache);
    await _pumpUntilFound(tester, find.text('Deload suggested'));

    expect(find.text('Acute readiness floor (1/5 logged).'), findsOneWidget);
    expect(
      find.text(
        'If applied: sets scaled to 50% of plan · RPE capped at 7. '
        'Your coach has been told.',
      ),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('deload_banner.chat')));
    await _pumpUntilFound(tester, find.text('Assistant'));

    expect(find.byKey(const Key('chat_composer')), findsOneWidget);
  });

  testWidgets('program overview shows real days, prescriptions, and provenance',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.programVersion = 6;
    fake.programPublishedByCoachAccountId = 'account-coach-1';
    await _pumpProgram(tester, fake);

    expect(find.text('Upper/Lower 4x'), findsOneWidget);
    expect(find.text('Upper/Lower · 4 days/week'), findsOneWidget);
    expect(find.text('Version 6'), findsNothing);
    expect(find.text('Former coach'), findsOneWidget);

    // The expanded first day sections warm-up, working sets, and cardio.
    expect(find.text('Warm-up'), findsOneWidget);
    expect(find.text('Working sets'), findsOneWidget);
    expect(find.text('Bench Press'), findsOneWidget);
    expect(
        find.text('Suggested substitutes: Incline DB Press'), findsOneWidget);
    expect(find.textContaining('3 × 5–8'), findsOneWidget);
    expect(find.textContaining('2 warm-up sets · rest 180s'), findsOneWidget);
    expect(find.text('Band Pull-Apart'), findsOneWidget);
    expect(find.text('2 × 15 · rest 45s'), findsOneWidget);
    expect(find.text('Pause on the chest.'), findsOneWidget);
    expect(find.text('Tempo: 3-1-1'), findsOneWidget);
    expect(find.text('Squeeze at the top.'), findsOneWidget);
    expect(find.text('Cardio'), findsOneWidget);
  });

  testWidgets('exercise detail keeps notes and technique available',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    expect(find.text('Pause on the chest.'), findsNothing);
    await tester.tap(find.text('Bench Press'));
    await _pumpUntilFound(tester, find.text('Pause on the chest.'));

    expect(find.text('Notes'), findsOneWidget);
    expect(find.text('Pause on the chest.'), findsOneWidget);
    expect(find.text('Technique'), findsOneWidget);

    await tester.tap(find.text('Technique'));
    await _pumpUntilFound(tester, find.textContaining('Lie on a flat bench'));
    expect(find.textContaining('Lie on a flat bench'), findsOneWidget);
  });

  testWidgets('program change summary is localized, capped, and dismissible in English',
      (tester) async {
    await _expectProgramChangeSummary(tester, 'en');
  });

  testWidgets('program change summary is localized, capped, and dismissible in Arabic',
      (tester) async {
    await _expectProgramChangeSummary(tester, 'ar');
  });

  testWidgets('approval without changes uses its English confirmation', (tester) async {
    await _expectProgramChangeSummary(tester, 'en', unchanged: true);
  });

  testWidgets('approval without changes uses its Arabic confirmation', (tester) async {
    await _expectProgramChangeSummary(tester, 'ar', unchanged: true);
  });

  testWidgets('unitemized program details are stated in English', (tester) async {
    await _expectOtherDetailsSummary(tester, 'en');
  });

  testWidgets('unitemized program details are stated in Arabic', (tester) async {
    await _expectOtherDetailsSummary(tester, 'ar');
  });

  testWidgets('fixed reps and fractional RIR render in English', (tester) async {
    await _expectPrescriptionFormatting(tester, 'en');
  });

  testWidgets('fixed reps and fractional RIR render in Arabic', (tester) async {
    await _expectPrescriptionFormatting(tester, 'ar');
  });

  testWidgets('a dismissed newest summary supersedes older unread summaries',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    fake.playerNotices.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'notice_id': 'newest-summary',
        'kind': 'program_published',
        'message': 'Your coach published program version 3.',
        'created_at': '2026-10-05T10:03:00Z',
        'read_at': null,
        'summary_dismissed_at': '2026-10-05T10:04:00Z',
        'program_change_summary': <String, dynamic>{
          'version': 1,
          'unchanged': false,
          'changes': <Map<String, dynamic>>[
            <String, dynamic>{
              'type': 'exercise_added',
              'day': 'Upper 1',
              'exercise': 'Newest summary exercise',
            },
          ],
        },
      },
      <String, dynamic>{
        'notice_id': 'older-summary',
        'kind': 'program_published',
        'message': 'Your coach published program version 2.',
        'created_at': '2026-10-05T10:02:00Z',
        'read_at': null,
        'summary_dismissed_at': null,
        'program_change_summary': <String, dynamic>{
          'version': 1,
          'unchanged': false,
          'changes': <Map<String, dynamic>>[
            <String, dynamic>{
              'type': 'exercise_added',
              'day': 'Upper 1',
              'exercise': 'Older summary exercise',
            },
          ],
        },
      },
    ]);

    await _pumpProgram(tester, fake);

    expect(find.textContaining('Newest summary exercise'), findsNothing);
    expect(find.textContaining('Older summary exercise'), findsNothing);
    expect(find.text('Program changes'), findsNothing);
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets('program renders in ${mode.name} theme without overflow',
        (tester) async {
      final FakeMayosApi fake = _signedInFake();
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      expect(
        Theme.of(tester.element(find.text('Upper/Lower 4x'))).brightness,
        mode == ThemeMode.dark ? Brightness.dark : Brightness.light,
      );

      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pump(const Duration(milliseconds: 200));
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'substitution picker and other-day option fit 360dp in ${mode.name} theme',
        (tester) async {
      final FakeMayosApi fake = _signedInFake()
        ..repeatBenchPressOnOtherDays = true;
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      await _chooseCableFly(tester);
      expect(find.text('Also replace on 2 other days'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('Also replace on 2 other days'));
      await tester.pump();
      await tester.tap(find.text('Substitute'));
      await tester.pumpAndSettle();
      await _pumpUntilFound(tester, find.text('Undo'));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'issue 170: previous coach publication leaves the new assignment in direct control',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-former-coach';
    await _pumpProgram(tester, fake);

    await _chooseCableFly(tester);
    await _pumpUntilFound(tester, find.text('Cable Fly'));
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(fake.programRequests, isEmpty);
    expect(fake.programSubstitutionRequests.single, <String, dynamic>{
      'day_name': 'Upper 1',
      'exercise_id': 'bench_press',
      'replacement_exercise_id': 'cable_fly',
      'all_occurrences': false,
    });
    expect(find.text('Undo'), findsOneWidget);

    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Bench Press'));
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(fake.programSubstitutionUndoRequests, hasLength(1));
    expect(fake.programSubstitutionUndoRequests.single, <String, dynamic>{
      'restore_version': 1,
      'expected_active_version': 2,
    });
  });

  for (final ThemeMode mode in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
    testWidgets(
        'coach substitution requests are prefilled and fit 360dp in ${mode.name} theme',
        (tester) async {
      final FakeMayosApi fake = _signedInFake()
        ..activeAssignmentId = 'assignment-1'
        ..activeCoachDisplayName = 'Coach Alice'
        ..programPublishedByCoachAccountId = 'account-coach-1'
        ..coachControlsProgram = true;
      await _pumpProgram(
        tester,
        fake,
        mode: mode,
        size: const Size(360, 640),
      );

      await _openSubstitutePicker(tester);
      await tester.tap(find.text('Cable Fly'));
      await tester.pumpAndSettle();

      final Finder requestDialog = find.byType(AlertDialog);
      expect(
        find.descendant(of: requestDialog, matching: find.text('Upper 1')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: requestDialog, matching: find.text('Bench Press')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: requestDialog, matching: find.text('Cable Fly')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('program_request_day_field')), findsNothing);
      expect(find.byKey(const Key('program_request_exercise_field')),
          findsNothing);
      expect(find.byKey(const Key('program_request_replacement_field')),
          findsNothing);
      expect(
        find.descendant(of: requestDialog, matching: find.text('bench_press')),
        findsNothing,
      );

      await tester.tap(find.byKey(const Key('program_request_submit_button')));
      await tester.pumpAndSettle();
      expect(find.text('A reason is required.'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('program_request_reason_field')),
        'The current movement hurts my shoulder.',
      );
      await tester.tap(find.byKey(const Key('program_request_submit_button')));
      await tester.pumpAndSettle();
      await _pumpUntilFound(
        tester,
        find.textContaining('Your coach has been asked to replace'),
      );

      expect(fake.programRequests, hasLength(1));
      expect(fake.programRequests.single,
          containsPair('kind', 'exercise_substitution'));
      expect(fake.programRequests.single, containsPair('day_name', 'Upper 1'));
      expect(fake.programRequests.single,
          containsPair('exercise_id', 'bench_press'));
      expect(fake.programRequests.single,
          containsPair('replacement_exercise_id', 'cable_fly'));
      expect(fake.programRequests.single,
          containsPair('reason', 'The current movement hurts my shoulder.'));
      expect(fake.programSubstitutionRequests, isEmpty);
      expect(find.text('Bench Press'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('stale request authority refreshes into direct substitution',
      (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..activeAssignmentId = 'assignment-1'
      ..activeCoachDisplayName = 'Coach Alice'
      ..programPublishedByCoachAccountId = 'account-coach-1'
      ..coachControlsProgram = true;
    await _pumpProgram(tester, fake);

    await _openSubstitutePicker(tester);
    await tester.tap(find.text('Cable Fly'));
    await tester.pumpAndSettle();
    fake.coachControlsProgram = false;
    await tester.enterText(
      find.byKey(const Key('program_request_reason_field')),
      'The current movement hurts my shoulder.',
    );
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Undo'));

    expect(fake.programRequests, isEmpty);
    expect(fake.programSubstitutionRequests, hasLength(1));
    expect(
      find.textContaining(
          'Program authority changed. Continuing with direct substitution.'),
      findsOneWidget,
    );
    expect(find.text('Cable Fly'), findsOneWidget);
  });

  testWidgets('stale direct authority refreshes into a coach request',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    await _pumpProgram(tester, fake);

    await _openSubstitutePicker(tester);
    fake.coachControlsProgram = true;
    await tester.tap(find.text('Cable Fly'));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('program_request_reason_field')), findsOneWidget);
    expect(fake.programSubstitutionRequests, isEmpty);
    await tester.enterText(
      find.byKey(const Key('program_request_reason_field')),
      'The current movement hurts my shoulder.',
    );
    await tester.tap(find.byKey(const Key('program_request_submit_button')));
    await tester.pumpAndSettle();

    expect(fake.programRequests, hasLength(1));
    expect(fake.programRequests.single['replacement_exercise_id'], 'cable_fly');
    expect(fake.programSubstitutionRequests, isEmpty);
  });

  testWidgets(
      'substitution leaves an active workout frozen and seeds the next one',
      (tester) async {
    final FakeMayosApi fake = _signedInFake();
    final InMemoryActiveWorkoutStore activeWorkouts =
        InMemoryActiveWorkoutStore();
    await _pumpProgram(tester, fake, activeWorkoutStore: activeWorkouts);
    final ProviderContainer container = ProviderScope.containerOf(
      tester.element(find.text('Day 1: Upper 1')),
      listen: false,
    );
    final ApiClient api = container.read(apiClientProvider);
    final TrainingProgram initialProgram =
        (await _waitWithPumps(tester, api.activeProgram()))!;
    final ActiveWorkoutController controller =
        container.read(activeWorkoutControllerProvider.notifier);
    expect(
      await _waitWithPumps(
        tester,
        controller.startFromDay(
          accountId: 'account-alice',
          day: initialProgram.days.first,
          programVersion: initialProgram.version,
        ),
      ),
      StartWorkoutOutcome.started,
    );
    ActiveWorkout? frozenWorkout = await activeWorkouts.read('account-alice');
    expect(frozenWorkout, isNotNull);
    expect(frozenWorkout!.exercises.map((e) => e.exerciseId),
        contains('bench_press'));
    await _chooseCableFly(tester);
    await _pumpUntilFound(tester, find.text('Cable Fly'));

    frozenWorkout = await activeWorkouts.read('account-alice');
    expect(frozenWorkout!.exercises.map((e) => e.exerciseId),
        contains('bench_press'));
    expect(frozenWorkout.exercises.map((e) => e.exerciseId),
        isNot(contains('cable_fly')));

    await _waitWithPumps(
      tester,
      controller.discard(
        accountId: 'account-alice',
        workoutId: frozenWorkout.id,
      ),
    );
    final TrainingProgram updatedProgram =
        (await _waitWithPumps(tester, api.activeProgram()))!;
    expect(
      await _waitWithPumps(
        tester,
        controller.startFromDay(
          accountId: 'account-alice',
          day: updatedProgram.days.first,
          programVersion: updatedProgram.version,
        ),
      ),
      StartWorkoutOutcome.started,
    );
    final ActiveWorkout? nextWorkout =
        await activeWorkouts.read('account-alice');
    expect(nextWorkout, isNotNull);
    expect(
        nextWorkout!.exercises.map((e) => e.exerciseId), contains('cable_fly'));
    expect(nextWorkout.exercises.map((e) => e.exerciseId),
        isNot(contains('bench_press')));
  });

  testWidgets('other-day choice substitutes all occurrences', (tester) async {
    final FakeMayosApi fake = _signedInFake()
      ..repeatBenchPressOnOtherDays = true;
    await _pumpProgram(tester, fake);

    await _chooseCableFly(tester);
    expect(find.text('Also replace on 2 other days'), findsOneWidget);
    await tester.tap(find.text('Also replace on 2 other days'));
    await tester.pump();
    await tester.tap(find.text('Substitute'));
    await tester.pumpAndSettle();
    await _pumpUntilFound(tester, find.text('Cable Fly'));

    expect(fake.programSubstitutionRequests.single['all_occurrences'], isTrue);
    expect(
      (fake.programDaysOverride ?? <Map<String, dynamic>>[])
          .expand(
              (Map<String, dynamic> day) => day['exercises'] as List<dynamic>)
          .where((dynamic row) =>
              (row as Map<String, dynamic>)['exercise_id'] == 'bench_press'),
      isEmpty,
    );
  });
}
