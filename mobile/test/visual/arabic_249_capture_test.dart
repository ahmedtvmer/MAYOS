@Tags(<String>['capture'])
library;

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/app.dart';
import 'package:mayos_mobile/src/core/active_workout.dart';
import 'package:mayos_mobile/src/core/analytics_client.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_mode.dart';
import 'package:mayos_mobile/src/core/baselines.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/chat_storage.dart';
import 'package:mayos_mobile/src/core/device_timezone.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_typography.dart';
import 'package:mayos_mobile/src/core/theme/theme_mode_store.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/core/workout_start_notice_store.dart';
import 'package:mayos_mobile/src/core/workout_storage.dart';
import 'package:mayos_mobile/src/features/player/exercise/exercise_detail_screen.dart';
import 'package:mayos_mobile/src/features/player/workout/workout_logger_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import '../support/fake_mayos_api.dart';

final bool _captureEnabled = Platform.environment['CAPTURE_249'] == '1';
bool _brandImagesPrecached = false;
const Key _captureBoundaryKey = Key('mayos.249.capture');
const String _accountId = 'account-alice';
const String _dayName = 'الجزء العلوي: الظهر والكتف والذراع';
const String _input =
    'عملت \u20663 × 10\u2069 في \u2066Wide-Grip Lat Pulldown\u2069 بوزن '
    '\u206627.5\u00a0kg\u2069. أرتاح قد إيه؟';
const String _reply = '## الراحة بين المجموعات\n'
    'استرح لمدة \u206602:00\u2069 قبل المجموعة التالية. '
    'سجّل الوزن والتكرارات كما أديتها.\n\n'
    '> التكرارات المتبقية \u2066RIR\u00a02\u2069 تعني أنك تستطيع أداء '
    'تكرارين إضافيين.\n\n'
    '**آخر مجموعة:** \u206627.5\u00a0kg · 10\u00a0reps · RIR\u00a02\u2069';
const String _englishQuestion =
    'Should I log bench press as 3 × 10 at 27.5\u00a0kg?';
const String _answer =
    'نعم، سجّل كل مجموعة على حدة. اكتب \u206627.5\u00a0kg\u2069 و'
    '\u206610\u2069 تكرارات، ثم اختر قيمة \u2066RIR\u2069.';
final DateTime _fixedNow = DateTime.utc(2026, 10, 1, 10);

class _CaptureConfiguration {
  const _CaptureConfiguration({
    required this.language,
    required this.themeMode,
    required this.logicalSize,
  });

  final String language;
  final ThemeMode themeMode;
  final Size logicalSize;
}

class _CaptureFixture {
  _CaptureFixture(this.configuration) {
    api.issuedToken = 'token-alice';
    api.currentUsername = 'alice';
    api.tokenValid = true;
    api.profileExists = true;
    api.recoveryEmail = 'alice@example.com';
    api.coachDisplayName = 'Coach Alice';
    api.displayLanguage = configuration.language;
    api.programVersion = 1;
    api.scheduleEmpty = true;
    api.volumeByDays = <int, Map<String, dynamic>>{
      7: <String, dynamic>{'الصدر': 12.5, 'الظهر والكتف الخلفي': 9.0},
    };
    api.programDaysOverride = <Map<String, dynamic>>[
      <String, dynamic>{
        'day_name': _dayName,
        'day_order': 1,
        'warmup_exercises': <Map<String, dynamic>>[],
        'exercises': <Map<String, dynamic>>[
          for (final (String id, String name) in <(String, String)>[
            ('lat_pulldown', 'Wide-Grip Lat Pulldown'),
            ('bench_press', 'Bench Press'),
          ])
            <String, dynamic>{
              'exercise_id': id,
              'exercise_name': name,
              'warmup_sets': 0,
              'target_sets': 3,
              'target_reps_min': 10,
              'target_reps_max': 10,
              'target_rpe': 8.0,
              'rest_seconds': 120,
              'notes': null,
            },
        ],
      },
    ];
  }

  final _CaptureConfiguration configuration;
  final FakeMayosApi api = FakeMayosApi();
  final InMemoryActiveWorkoutStore activeWorkouts =
      InMemoryActiveWorkoutStore();
  final InMemoryChatCacheStore chatCache = InMemoryChatCacheStore();

  Future<void> seedWorkout() => activeWorkouts.write(
        _accountId,
        ActiveWorkout.fromJson(<String, dynamic>{
          'id': 'capture-active-workout',
          'account_id': _accountId,
          'started_at': '2026-10-01T10:00:00.000Z',
          'day_order': 1,
          'day_name': _dayName,
          'program_version': 1,
          'exercises': <Map<String, dynamic>>[
            for (final (String id, String name) in <(String, String)>[
              ('lat_pulldown', 'Wide-Grip Lat Pulldown'),
              ('bench_press', 'Bench Press'),
            ])
              <String, dynamic>{
                'exercise': <String, dynamic>{
                  'exercise_id': id,
                  'exercise_name': name,
                  'target_sets': 3,
                  'target_reps_min': 10,
                  'target_reps_max': 10,
                  'target_rpe': 8,
                  'rest_seconds': 120,
                  'equipment': id == 'bench_press' ? 'barbell' : 'cable',
                },
                'sets': <Map<String, dynamic>>[
                  <String, dynamic>{},
                  <String, dynamic>{},
                  <String, dynamic>{},
                ],
                'effective_sets': 3,
              },
          ],
          'baselines': <String, dynamic>{},
        }),
      );

  Future<void> seedChat() async {
    api.chatHistory.addAll(<Map<String, dynamic>>[
      <String, dynamic>{
        'id': 'fixture-user-1',
        'role': 'user',
        'content': _input,
        'created_at': '2026-10-01T10:00:01Z',
      },
      <String, dynamic>{
        'id': 'fixture-assistant-1',
        'role': 'assistant',
        'content': _reply,
        'created_at': '2026-10-01T10:00:02Z',
      },
      <String, dynamic>{
        'id': 'fixture-user-2',
        'role': 'user',
        'content': _englishQuestion,
        'created_at': '2026-10-01T10:00:03Z',
      },
      <String, dynamic>{
        'id': 'fixture-assistant-2',
        'role': 'assistant',
        'content': _answer,
        'created_at': '2026-10-01T10:00:04Z',
      },
      <String, dynamic>{
        'id': 'fixture-assistant-detail',
        'role': 'assistant',
        'content': '$_reply\n\n$_answer\n\n'
            '### نقاط المتابعة\n\n'
            '- سجّل Wide-Grip Lat Pulldown باسم التمرين كما يظهر في البرنامج.\n'
            '- سجّل 27.5 kg مع 10 تكرارات عند تكرار النتيجة.\n'
            '- اختر RIR بعد إنهاء المجموعة.\n'
            '- قارن المجموعات مع الحصة السابقة.\n'
            '- زد الوزن فقط عندما تسمح جودة الحركة بذلك.\n'
            '- استرح 120 ثانية قبل المجموعة التالية.\n'
            '- أبقِ التكرارات عند 10.\n'
            '- استخدم الأزرار الرقمية بالترتيب المعتاد.',
        'created_at': '2026-10-01T10:00:05Z',
      },
    ]);
    await chatCache.writeDisclosureAccepted(_accountId);
    await chatCache.writeHistory(_accountId, <ChatMessage>[
      for (final Map<String, dynamic> message in api.chatHistory)
        ChatMessage.fromJson(message),
    ]);
  }
}

Future<void> _loadCaptureFonts() async {
  final FontLoader playfair = FontLoader('PlayfairDisplay')
    ..addFont(rootBundle.load('assets/fonts/PlayfairDisplay-Variable.ttf'));
  final FontLoader inter = FontLoader('Inter')
    ..addFont(rootBundle.load('assets/fonts/Inter-Variable.ttf'));
  final FontLoader arabic = FontLoader(MayosTypography.arabicFamily)
    ..addFont(rootBundle.load(
        'assets/fonts/arabic/IBMPlexSansArabic-Regular.ttf'))
    ..addFont(rootBundle.load(
        'assets/fonts/arabic/IBMPlexSansArabic-Medium.ttf'))
    ..addFont(rootBundle.load(
        'assets/fonts/arabic/IBMPlexSansArabic-SemiBold.ttf'))
    ..addFont(rootBundle.load('assets/fonts/arabic/IBMPlexSansArabic-Bold.ttf'));
  final FontLoader icons = FontLoader('MaterialIcons')
    ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await Future.wait<void>(
      <Future<void>>[playfair.load(), inter.load(), arabic.load(), icons.load()]);
}

Future<void> _startApp(
  WidgetTester tester,
  _CaptureFixture fixture,
) async {
  final _CaptureConfiguration configuration = fixture.configuration;
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
  tester.view.physicalSize = configuration.logicalSize * 2;
  tester.view.devicePixelRatio = 2;
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');

  await tester.pumpWidget(
    ProviderScope(
      key: UniqueKey(),
      overrides: <Override>[
        tokenStoreProvider.overrideWithValue(tokens),
        appModeStoreProvider.overrideWithValue(InMemoryAppModeStore()),
        themeModeStoreProvider.overrideWithValue(
          InMemoryThemeModeStore(configuration.themeMode),
        ),
        systemDisplayLanguageProvider.overrideWithValue(configuration.language),
        displayLanguageStoreProvider.overrideWithValue(
          InMemoryDisplayLanguageStore(),
        ),
        activeWorkoutStoreProvider.overrideWithValue(fixture.activeWorkouts),
        chatCacheStoreProvider.overrideWithValue(fixture.chatCache),
        draftStoreProvider.overrideWithValue(InMemoryDraftStore()),
        workoutCacheStoreProvider.overrideWithValue(InMemoryWorkoutCacheStore()),
        baselineCacheStoreProvider.overrideWithValue(InMemoryBaselineCacheStore()),
        workoutStartNoticeStoreProvider.overrideWithValue(
          InMemoryWorkoutStartNoticeStore(),
        ),
        analyticsClientProvider.overrideWithValue(const NoOpAnalyticsClient()),
        clockProvider.overrideWithValue(() => _fixedNow),
        deviceTimezoneProvider.overrideWithValue(Future<String>.value('UTC')),
        deviceTimezoneOrNullProvider
            .overrideWithValue(Future<String?>.value('UTC')),
        apiClientProvider.overrideWith((ref) {
          final ApiClient client = ApiClient(
            tokens: ref.watch(tokenStoreProvider),
            baseUrl: 'http://test.local',
            adapter: fixture.api.adapter,
          );
          client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
          return client;
        }),
      ],
      child: RepaintBoundary(
        key: _captureBoundaryKey,
        child: const MayosApp(),
      ),
    ),
  );
  await _pumpUntilFound(
    tester,
    find.text(configuration.language == 'ar' ? 'الرئيسية' : 'Home'),
  );
  if (!_brandImagesPrecached) {
    await _precacheBrandImages(tester);
    _brandImagesPrecached = true;
  }
}

Future<void> _pumpUntilFound(
  WidgetTester tester,
  Finder finder, {
  int attempts = 50,
}) async {
  for (int attempt = 0; attempt < attempts; attempt++) {
    if (finder.evaluate().isNotEmpty) {
      for (int frame = 0; frame < 4; frame++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      return;
    }
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(finder, findsWidgets);
}

Future<Uint8List> _writeCapture(WidgetTester tester, String filename) async {
  final RenderRepaintBoundary boundary = tester.renderObject(
    find.byKey(_captureBoundaryKey),
  );
  final Uint8List bytes = (await tester.runAsync(() async {
    final ui.Image image = await boundary.toImage(pixelRatio: 2);
    final ByteData? encoded = await image.toByteData(
      format: ui.ImageByteFormat.png,
    );
    image.dispose();
    return encoded!.buffer.asUint8List();
  }))!;
  final Directory output = Directory(
    '${Directory.current.parent.path}/docs/design-review/249/production/screens',
  );
  await tester.runAsync(() async {
    await output.create(recursive: true);
    await File('${output.path}/$filename.png').writeAsBytes(bytes);
  });
  return bytes;
}

Future<void> _openLogger(WidgetTester tester) async {
  await _pumpUntilFound(tester, find.text('استئناف'));
  await tester.tap(find.text('استئناف'));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
}

Future<void> _typeWeight275(WidgetTester tester) async {
  expect(find.byKey(const ValueKey<String>('logger.key.2')), findsOneWidget);
  for (final String key in <String>['2', '7']) {
    await tester.tap(find.byKey(ValueKey<String>('logger.key.$key')));
  }
  await tester.tap(find.byKey(const ValueKey<String>('logger.key.dot')));
  await tester.tap(find.byKey(const ValueKey<String>('logger.key.5')));
  await tester.pump(const Duration(milliseconds: 100));
  expect(
    find.descendant(
      of: find.byKey(const ValueKey<String>('logger.cell.0.0.kg')),
      matching: find.text('27.5'),
    ),
    findsOneWidget,
  );
}

Future<void> _captureHomeAndChat(
  WidgetTester tester,
  _CaptureConfiguration configuration,
) async {
  final String sizeLabel =
      '${configuration.logicalSize.width.toInt()}x${configuration.logicalSize.height.toInt()}';
  final String themeLabel = configuration.themeMode == ThemeMode.dark
      ? 'dark'
      : 'light';
  final _CaptureFixture homeFixture = _CaptureFixture(configuration);
  await _startApp(tester, homeFixture);
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'C-home-$themeLabel-$sizeLabel');

  final Finder exercise = find.text('Bench Press').first;
  await tester.ensureVisible(exercise);
  await tester.tap(exercise);
  await _pumpUntilFound(tester, find.byType(ExerciseDetailScreen));
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'C-home-detail-$themeLabel-$sizeLabel');

  final _CaptureFixture chatFixture = _CaptureFixture(configuration);
  await chatFixture.seedChat();
  await _startApp(tester, chatFixture);
  await tester.tap(find.byTooltip('المساعد'));
  await _pumpUntilFound(tester, find.byKey(const Key('chat_composer')));
  expect(tester.takeException(), isNull);
  final Uint8List chatImage =
      await _writeCapture(tester, 'C-chat-$themeLabel-$sizeLabel');
  final Uint8List detailImage = await _scrollAndCaptureChatDetail(
    tester,
    themeLabel,
    sizeLabel,
  );
  expect(detailImage, isNot(equals(chatImage)));
}

Future<Uint8List> _scrollAndCaptureChatDetail(
  WidgetTester tester,
  String themeLabel,
  String sizeLabel,
) async {
  final Finder detailReply =
      find.byKey(const ValueKey<String>('fixture-assistant-detail'));
  final Finder scroll = find.byType(CustomScrollView).first;
  for (int attempt = 0; attempt < 5 && detailReply.evaluate().isEmpty; attempt++) {
    await tester.drag(scroll, const Offset(0, -420));
    await tester.pumpAndSettle();
  }
  expect(detailReply, findsOneWidget);
  await tester.ensureVisible(detailReply);
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
  return _writeCapture(tester, 'C-chat-detail-$themeLabel-$sizeLabel');
}

Future<void> _captureLogger(
  WidgetTester tester,
  _CaptureConfiguration configuration,
) async {
  final String sizeLabel =
      '${configuration.logicalSize.width.toInt()}x${configuration.logicalSize.height.toInt()}';
  final String themeLabel = configuration.themeMode == ThemeMode.dark
      ? 'dark'
      : 'light';
  final _CaptureFixture fixture = _CaptureFixture(configuration);
  await fixture.seedWorkout();
  await _startApp(tester, fixture);
  await _openLogger(tester);
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'C-logger-$themeLabel-$sizeLabel');

  await tester.tap(find.byKey(const ValueKey<String>('logger.cell.0.0.kg')));
  await tester.pump(const Duration(milliseconds: 100));
  await _typeWeight275(tester);
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'C-logger-keypad-$themeLabel-$sizeLabel');
}

Future<void> _captureLoggerStress(WidgetTester tester) async {
  const _CaptureConfiguration configuration = _CaptureConfiguration(
    language: 'ar',
    themeMode: ThemeMode.dark,
    logicalSize: Size(412, 915),
  );
  final _CaptureFixture rirFixture = _CaptureFixture(configuration);
  await rirFixture.seedWorkout();
  await _startApp(tester, rirFixture);
  await _openLogger(tester);
  await tester.tap(find.byKey(const ValueKey<String>('logger.cell.0.0.rir')));
  await tester.pump(const Duration(milliseconds: 100));
  expect(find.byKey(const ValueKey<String>('logger.rir.0')), findsOneWidget);
  expect(find.byKey(const ValueKey<String>('logger.rir.5')), findsOneWidget);
  await _writeCapture(tester, 'C-logger-rir-dark-412x915');

  final _CaptureFixture swipeFixture = _CaptureFixture(configuration);
  await swipeFixture.seedWorkout();
  await _startApp(tester, swipeFixture);
  await _openLogger(tester);
  final Finder row = find.byType(Dismissible).first;
  await tester.ensureVisible(row);
  final ActiveWorkout beforeSwipe =
      (await swipeFixture.activeWorkouts.read(_accountId))!;
  final String removedSetId = beforeSwipe.exercises.first.sets.first.id;
  await tester.drag(row, const Offset(700, 0));
  await tester.pumpAndSettle();
  expect(tester.takeException(), isNull);
  final ActiveWorkout afterSwipe =
      (await swipeFixture.activeWorkouts.read(_accountId))!;
  expect(afterSwipe.exercises.first.sets, hasLength(2));
  expect(
    afterSwipe.exercises.first.sets
        .any((ActiveWorkoutSet set) => set.id == removedSetId),
    isFalse,
  );
  await _writeCapture(tester, 'C-logger-swipe-dark-412x915');
}

Future<void> _captureEnglishScreens(WidgetTester tester) async {
  const _CaptureConfiguration configuration = _CaptureConfiguration(
    language: 'en',
    themeMode: ThemeMode.light,
    logicalSize: Size(412, 915),
  );
  final _CaptureFixture homeFixture = _CaptureFixture(configuration);
  await _startApp(tester, homeFixture);
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'EN-home-light-412x915');

  final _CaptureFixture loggerFixture = _CaptureFixture(configuration);
  await loggerFixture.seedWorkout();
  await _startApp(tester, loggerFixture);
  await _pumpUntilFound(tester, find.text('Resume'));
  await tester.tap(find.text('Resume'));
  await _pumpUntilFound(tester, find.byType(WorkoutLoggerScreen));
  expect(tester.takeException(), isNull);
  await _writeCapture(tester, 'EN-logger-light-412x915');
}

Future<void> _precacheBrandImages(WidgetTester tester) async {
  final BuildContext context = tester.element(find.byType(MaterialApp));
  const List<String> assets = <String>[
    'assets/brand/mayos-lockup-white.png',
    'assets/brand/mayos-lockup-black.png',
    'assets/brand/mayos-mark-white.png',
    'assets/brand/mayos-mark-black.png',
    'assets/images/gym-wallpaper.jpg',
  ];
  await tester.runAsync(() async {
    for (final String asset in assets) {
      await precacheImage(AssetImage(asset), context);
    }
  });
  await tester.pump();
}

void main() {
  testWidgets(
    'captures actual selected-family Arabic screens and English comparison',
    (WidgetTester tester) async {
      await _loadCaptureFonts();
      tester.platformDispatcher.textScaleFactorTestValue = 1;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      const List<Size> sizes = <Size>[Size(360, 640), Size(412, 915)];
      for (final ThemeMode theme in <ThemeMode>[ThemeMode.light, ThemeMode.dark]) {
        for (final Size size in sizes) {
          final _CaptureConfiguration configuration = _CaptureConfiguration(
            language: 'ar',
            themeMode: theme,
            logicalSize: size,
          );
          await _captureHomeAndChat(tester, configuration);
          await _captureLogger(tester, configuration);
        }
      }
      await _captureLoggerStress(tester);
      await _captureEnglishScreens(tester);
    },
    skip: !_captureEnabled,
  );
}
