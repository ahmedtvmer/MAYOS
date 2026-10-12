import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/display_language/coach_copy.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/progress/checkpoint_review_screen.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_mayos_api.dart';
import 'support/fake_api_adapter.dart';

const Map<String, dynamic> _reviewRating = <String, dynamic>{
  'Consistency': <String, String>{
    'part': 'Consistency',
    'label': 'Steady',
    'part_code': 'consistency',
    'label_code': 'steady',
  },
  'Progression': <String, String>{
    'part': 'Progression',
    'label': 'Strong',
    'part_code': 'progression',
    'label_code': 'strong',
  },
  'Volume trend': <String, String>{
    'part': 'Volume trend',
    'label': 'Rising',
    'part_code': 'volume_trend',
    'label_code': 'rising',
  },
};

Future<ApiClient> _pumpReview(
  WidgetTester tester, {
  required FakeMayosApi api,
  required DisplayLanguageController language,
  required InMemoryTokenStore tokens,
  String? assignmentId,
}) async {
  final ApiClient apiClient = ApiClient(
    tokens: tokens,
    baseUrl: 'http://test.local',
    adapter: api.adapter,
    displayLanguageLoader: () => language.state,
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        displayLanguageProvider.overrideWith((ref) => language),
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWithValue(apiClient),
      ],
      child: MaterialApp(
        theme: MayosTheme.light,
        home: CheckpointReviewScreen(
          checkpoint: 10,
          assignmentId: assignmentId,
        ),
      ),
    ),
  );
  for (int attempt = 0; attempt < 40; attempt++) {
    if (find
        .byKey(const ValueKey<String>('checkpoint.review.text'))
        .evaluate()
        .isNotEmpty) {
      break;
    }
    await tester.pump(const Duration(milliseconds: 50));
  }
  return apiClient;
}

void main() {
  testWidgets('temporary template and labels follow a changed player language',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..issuedToken = 'player-token'
      ..currentUsername = 'player';
    api.checkpointReviewDetails[10] = <String, dynamic>{
      'checkpoint': 10,
      'period_start': '2026-01-01',
      'period_end': '2026-09-30',
      'facts': <String, dynamic>{'workouts_in_period': 10},
      'rating': _reviewRating.values.toList(growable: false),
      'text': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
      'text_by_language': <String, String>{
        'en': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'ar': 'محطة تقدم 10: أكملت 10 حصص تدريبية منذ بدء تسجيلك في MAYOS.',
      },
      'text_is_template': true,
      'text_language': null,
    };
    final DisplayLanguageController language = DisplayLanguageController(
      InMemoryDisplayLanguageStore(),
      systemLanguage: 'en',
    );
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('player-token');

    await _pumpReview(
      tester,
      api: api,
      language: language,
      tokens: tokens,
    );

    expect(find.text('Checkpoint review'), findsOneWidget);
    expect(find.text('Checkpoint 10'), findsOneWidget);
    expect(find.text('Consistency'), findsOneWidget);
    expect(find.text('Steady'), findsOneWidget);
    expect(
      find.text(
          'Checkpoint 10: 10 workouts since you started logging in MAYOS.'),
      findsOneWidget,
    );
    expect(
        find.byKey(
            const ValueKey<String>('checkpoint.review.original-language')),
        findsNothing);

    await language.choose('ar');
    for (int attempt = 0; attempt < 40; attempt++) {
      if (find.text('مراجعة محطة التقدم').evaluate().isNotEmpty) break;
      await tester.pump(const Duration(milliseconds: 50));
    }

    final List<FakeRequest> requests = api.adapter.requests
        .where(
            (FakeRequest request) => request.path == '/checkpoint-reviews/10')
        .toList(growable: false);
    expect(requests, hasLength(2));
    expect(requests.last.headers['Accept-Language'], 'ar');
    expect(
      tester
          .widgetList<Text>(find.byType(Text))
          .map((Text widget) => widget.data)
          .whereType<String>()
          .toList(),
      contains('مراجعة محطة التقدم'),
    );
    expect(find.text('مراجعة محطة التقدم'), findsOneWidget);
    final Text checkpointLabel = tester.widget<Text>(
      find.byKey(const ValueKey<String>('checkpoint.review.checkpoint')),
    );
    expect(checkpointLabel.data, startsWith('محطة تقدم'));
    expect(checkpointLabel.data, contains('10'));
    expect(find.text('الاتساق'), findsOneWidget);
    expect(find.text('مستقر'), findsOneWidget);
    expect(find.text('اتجاه حجم التدريب'), findsOneWidget);
    expect(find.text('متزايد'), findsOneWidget);
    expect(
      tester
          .widget<Text>(
              find.byKey(const ValueKey<String>('checkpoint.review.text')))
          .data,
      'محطة تقدم 10: أكملت 10 حصص تدريبية منذ بدء تسجيلك في MAYOS.',
    );
  });

  testWidgets('review refetch waits for the Display-language PUT',
      (WidgetTester tester) async {
    final FakeMayosApi api = FakeMayosApi()
      ..issuedToken = 'player-token'
      ..currentUsername = 'player';
    api.checkpointReviewDetails[10] = <String, dynamic>{
      'checkpoint': 10,
      'period_start': '2026-01-01',
      'period_end': '2026-09-30',
      'facts': <String, dynamic>{'workouts_in_period': 10},
      'rating': _reviewRating.values.toList(growable: false),
      'text': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
      'text_by_language': <String, String>{
        'en': 'Checkpoint 10: 10 workouts since you started logging in MAYOS.',
        'ar': 'محطة تقدم 10: أكملت 10 حصص تدريبية منذ بدء تسجيلك في MAYOS.',
      },
      'text_is_template': true,
      'text_language': null,
    };
    final Completer<void> putStarted = Completer<void>();
    final Completer<void> finishPut = Completer<void>();
    api.adapter.beforeRespond = (FakeRequest request) async {
      if (request.path.endsWith('/auth/display-language')) {
        if (!putStarted.isCompleted) putStarted.complete();
        await finishPut.future;
      }
    };
    final DisplayLanguageController language = DisplayLanguageController(
      InMemoryDisplayLanguageStore(),
      systemLanguage: 'en',
    );
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('player-token');

    final ApiClient apiClient = await _pumpReview(
      tester,
      api: api,
      language: language,
      tokens: tokens,
    );
    Future<void> saveLanguage() async {
      await apiClient.updateDisplayLanguage('ar');
      await language.useAccount('player-account', 'ar');
    }
    final Future<void> saving = saveLanguage();
    bool saved = false;
    saving.then((_) => saved = true);
    try {
      for (int attempt = 0; attempt < 20 && !putStarted.isCompleted; attempt++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(putStarted.isCompleted, isTrue);
      expect(
        api.adapter.requests
            .where((FakeRequest request) =>
                request.path == '/checkpoint-reviews/10')
            .length,
        1,
      );
    } finally {
      if (!finishPut.isCompleted) finishPut.complete();
    }
    for (int attempt = 0; attempt < 40 && !saved; attempt++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(saved, isTrue);
    for (int attempt = 0; attempt < 40; attempt++) {
      final int reviewRequestCount = api.adapter.requests
          .where((FakeRequest request) =>
              request.path == '/checkpoint-reviews/10')
          .length;
      if (reviewRequestCount == 2 &&
          find.text('مراجعة محطة التقدم').evaluate().isNotEmpty) {
        break;
      }
      await tester.pump(const Duration(milliseconds: 50));
    }
    final List<FakeRequest> reviewRequests = api.adapter.requests
        .where((FakeRequest request) =>
            request.path == '/checkpoint-reviews/10')
        .toList(growable: false);
    expect(reviewRequests, hasLength(2));
    expect(reviewRequests.last.headers['Accept-Language'], 'ar');
    expect(find.text('مراجعة محطة التقدم'), findsOneWidget);
  });

  testWidgets('coach sees original player prose and localized rating labels',
      (WidgetTester tester) async {
    const String arabicReview = 'كان تقدمك في التدريب مستقرًا.';
    final FakeMayosApi api = FakeMayosApi()
      ..issuedToken = 'coach-token'
      ..currentUsername = 'coach'
      ..coach = true;
    api.checkpointReviewDetails[10] = <String, dynamic>{
      'checkpoint': 10,
      'period_start': '2026-01-01',
      'period_end': '2026-09-30',
      'facts': <String, dynamic>{'workouts_in_period': 10},
      'rating': _reviewRating.values.toList(growable: false),
      'text': arabicReview,
      'text_is_template': false,
      'text_language': 'ar',
    };
    final DisplayLanguageController language = DisplayLanguageController(
      InMemoryDisplayLanguageStore(),
      systemLanguage: 'en',
    );
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    await tokens.save('coach-token');

    await _pumpReview(
      tester,
      api: api,
      language: language,
      tokens: tokens,
      assignmentId: 'active-assignment',
    );

    expect(find.text('Checkpoint review'), findsOneWidget);
    expect(find.text('Consistency'), findsOneWidget);
    expect(find.text('Steady'), findsOneWidget);
    expect(find.text(arabicReview), findsOneWidget);
    expect(find.text('Original text language: Arabic'), findsOneWidget);
    expect(api.adapter.requests.single.path,
        '/coach/assignments/active-assignment/player/checkpoint-reviews/10');

    await language.choose('ar');
    for (int attempt = 0; attempt < 40; attempt++) {
      if (find.text('مراجعة محطة التقدم').evaluate().isNotEmpty) break;
      await tester.pump(const Duration(milliseconds: 50));
    }

    expect(find.text('مراجعة محطة التقدم'), findsOneWidget);
    expect(find.text('الاتساق'), findsOneWidget);
    expect(find.text('مستقر'), findsOneWidget);
    expect(find.text(arabicReview), findsOneWidget);
    expect(find.text('لغة النص الأصلي: العربية'), findsNothing);
    expect(api.adapter.requests, hasLength(2));
    expect(api.adapter.requests.last.headers['Accept-Language'], 'ar');
    expect(CoachCopy('ar').checkpointNumber(10),
        MayosCopy('ar').checkpointAt(10));
  });
}
