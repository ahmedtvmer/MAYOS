import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/app_failure.dart';
import 'package:mayos_mobile/src/core/chat_models.dart';
import 'package:mayos_mobile/src/core/connectivity_message.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_api_adapter.dart';

ApiClient _client(FakeApiAdapter adapter, {String language = 'en'}) =>
    ApiClient(
      tokens: InMemoryTokenStore(),
      baseUrl: 'http://test.local',
      adapter: adapter,
      displayLanguageLoader: () => language,
    );

Future<ApiException> _expectApiException(Future<void> Function() action) async {
  try {
    await action();
  } on ApiException catch (error) {
    return error;
  }
  fail('Expected ApiException.');
}

void main() {
  test('ordinary HTTP failures retain structured metadata and send language',
      () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(422, <String, dynamic>{
        'detail': <Object>[
          <String, Object>{'type': 'string_too_long'},
        ],
        'message_code': 'http.input_too_long.v1',
        'message_params': <String, int>{'limit': 400},
        'message_fallback': 'The request contains invalid fields.',
      }),
    );
    final ApiClient api = _client(adapter, language: 'ar');

    final ApiException error = await _expectApiException(api.clearChatHistory);

    expect(adapter.requests.single.headers['Accept-Language'], 'ar');
    expect(error.statusCode, 422);
    expect(error.messageCode, 'http.input_too_long.v1');
    expect(error.messageParams, <String, int>{'limit': 400});
    expect(error.serverDetails?['pydantic_errors'], isA<List<dynamic>>());
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(error)),
      'يجب ألا يتجاوز هذا الحقل \u2066400\u2069 حرفًا',
    );
  });

  test('Arabic wrong-password errors keep their specific meaning', () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(401, <String, dynamic>{
        'detail': 'Invalid credentials.',
        'message_code': 'auth.invalid_credentials.v1',
        'message_params': <String, Object>{},
        'message_fallback': 'Invalid credentials.',
      }),
    );
    final ApiClient api = _client(adapter, language: 'ar');
    final ApiException error = await _expectApiException(() async {
      await api.login(
        traineeId: 'alice',
        password: 'wrong-password',
      );
    });

    expect(error.message, 'Invalid credentials.');
    expect(error.messageCode, 'auth.invalid_credentials.v1');
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(error)),
      'بيانات تسجيل الدخول غير صحيحة.',
    );
  });

  test('unknown code and invalid params keep the safe English fallback',
      () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(400, <String, dynamic>{
        'detail': 'Safe English fallback.',
        'message_code': 'http.input_too_long.v1',
        'message_params': <String, Object>{'limit': 'untrusted'},
        'message_fallback': 'Safe English fallback.',
      }),
    );
    final ApiException error =
        await _expectApiException(_client(adapter, language: 'ar').clearChatHistory);

    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(error)),
      'Safe English fallback.',
    );
  });

  test('network and bodyless service failures use localized generic copy',
      () async {
    final ApiException network = await _expectApiException(
      _client(FakeApiAdapter((_) => const FakeResponse.networkFailure()),
              language: 'ar')
          .clearChatHistory,
    );
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(network)),
      'تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت.',
    );

    final ApiException noBody = await _expectApiException(
      _client(FakeApiAdapter((_) => const FakeResponse(503)), language: 'ar')
          .clearChatHistory,
    );
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(noBody)),
      'الخدمة غير متاحة. حاول مجددًا.',
    );
  });

  test('Google conflict keeps the machine distinction and translates',
      () async {
    final FakeApiAdapter adapter = FakeApiAdapter(
      (_) => const FakeResponse(409, <String, dynamic>{
        'detail': 'This Google account is already linked to a MAYOS account.',
        'code': 'google_account_already_linked',
        'message_code': 'google.account_already_linked.v1',
        'message_params': <String, Object>{},
        'message_fallback':
            'This Google account is already linked to a MAYOS account.',
      }),
    );
    final ApiException error =
        await _expectApiException(_client(adapter).clearChatHistory);

    expect(error.message,
        'This Google account is already linked to a MAYOS account.');
    expect(error.errorCode, 'google_account_already_linked');
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(error)),
      'حساب Google هذا مرتبط بالفعل بحساب MAYOS.',
    );
  });

  test('pre-stream refusals and SSE errors preserve structured messages',
      () async {
    final ApiClient refused = _client(FakeApiAdapter(
      (_) => const FakeResponse(429, <String, dynamic>{
        'detail': 'Daily AI limit reached.',
        'message_code': 'ai_limit.daily_usage.v1',
        'message_params': <String, Object>{},
        'message_fallback': 'Daily AI limit reached.',
      }),
    ), language: 'ar');
    final ApiException preStream = await _expectApiException(() async {
      await for (final _ in refused.streamChatMessage('Help me plan.')) {}
    });
    expect(preStream.statusCode, 429);
    expect(
      MayosCopy('ar').failureMessage(apiFailureMessage(preStream)),
      'وصلت إلى حد استخدام المساعد اليوم. أعد المحاولة غدًا.',
    );

    const String fallback = 'The assistant is temporarily unavailable.';
    final ApiClient stream = _client(FakeApiAdapter(
      (_) => const FakeResponse(200, null, <String>[
        'data: {"token":"partial"}\n\n',
        'event: error\ndata: {"detail":"$fallback",'
            '"message_code":"chat.failed.v1","message_params":{},'
            '"message_fallback":"$fallback"}\n\n',
      ]),
    ), language: 'ar');
    final List<ChatStreamEvent> events =
        await stream.streamChatMessage('Help me plan.').toList();
    expect(events, hasLength(2));
    expect(events.last, isA<ChatError>());
    final ChatError failure = events.last as ChatError;
    expect(failure.messageCode, 'chat.failed.v1');
    expect(
      MayosCopy('ar').failureMessage(ServerFailureMessage(
        failure.detail,
        messageCode: failure.messageCode,
        messageParams: failure.messageParams,
        messageFallback: failure.messageFallback,
      )),
      'تعذر على المساعد إكمال الرد. يُرجى إعادة المحاولة.',
    );
  });
}
