import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';

import 'support/fake_mayos_api.dart';

FakeMayosApi _signedInFake() {
  final FakeMayosApi fake = FakeMayosApi();
  fake.issuedToken = 'token-alice';
  fake.currentUsername = 'alice';
  fake.tokenValid = true;
  fake.profileExists = false;
  return fake;
}

Future<ApiClient> _client(FakeMayosApi fake) async {
  final InMemoryTokenStore tokens = InMemoryTokenStore();
  await tokens.save('token-alice');
  return ApiClient(
    tokens: tokens,
    baseUrl: 'http://test.local',
    adapter: fake.adapter,
  );
}

const Map<String, Object> _answers = <String, Object>{
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

void main() {
  test('program generation explanation resolves from confirmation metadata', () {
    const String fallback =
        'Your assigned coach controls your program. Ask your coach for changes.';
    final IntakeConfirmation confirmation = IntakeConfirmation.fromJson(
      <String, dynamic>{
        'status': 'confirmed',
        'program_message': fallback,
        'program_message_metadata': <String, dynamic>{
          'message_code': 'intake.program_generation_unavailable.v1',
          'message_params': <String, dynamic>{},
          'message_fallback': fallback,
        },
      },
    );

    expect(confirmation.programMessage!.resolve('en'), fallback);
    expect(
      confirmation.programMessage!.resolve('ar'),
      'يتحكم مدربك المعيّن في برنامجك التدريبي. اطلب من مدربك إجراء التغييرات.',
    );
  });

  test('intake contract, disclosure, answers, and confirmation round-trip',
      () async {
    final FakeMayosApi fake = _signedInFake();
    final ApiClient client = await _client(fake);

    final OnboardingIntake initial = await client.onboardingIntake();
    expect(initial.status, 'in_progress');
    expect(initial.disclosureAcknowledged, isFalse);
    expect(initial.field('gender')!.allowedValues, <String>['male', 'female']);
    expect(initial.field('gender')!.isRequired, isTrue);
    expect(
      initial.field('gender')!.optionDescriptions.keys,
      containsAll(<String>['male', 'female']),
    );
    expect(initial.field('gender')!.explanation!.metadata!.messageCode,
        'intake.gender.explanation.v1');
    expect(initial.field('gender')!.explanation!.metadata!.messageFallback,
        initial.field('gender')!.explanation!.text);
    expect(
      initial.field('gender')!
          .optionDescriptions['female']!.metadata!.messageCode,
      'intake.gender.option.female.v1',
    );
    expect(
      initial.field('proportions')!.optionDescriptions['balanced']!.text,
      isNotEmpty,
    );
    expect(initial.progress.requiredTotal, 12);
    expect(initial.progress.nextUnanswered, 'gender');
    expect(
      initial.field('injuries_or_limitations')!.hint!.text,
      contains('None'),
    );
    expect(initial.field('current_goal')!.examples, isNotEmpty);
    expect(
      initial.field('current_goal')!.examples.first.metadata!.messageCode,
      'intake.current_goal.example.1.v1',
    );

    // Answers are refused until the hosted-processing disclosure is accepted.
    await expectLater(
      client.saveIntakeAnswer('gender', 'female'),
      throwsA(isA<ApiException>()),
    );

    final OnboardingIntake acknowledged =
        await client.acknowledgeIntakeDisclosure();
    expect(acknowledged.disclosureAcknowledged, isTrue);

    OnboardingIntake view = acknowledged;
    for (final MapEntry<String, Object> entry in _answers.entries) {
      view = await client.saveIntakeAnswer(entry.key, entry.value);
    }
    expect(view.progress.isComplete, isTrue);
    expect(view.field('proportions')!.answer, 'long_legs');

    final IntakeConfirmation confirmed = await client.confirmIntake();
    expect(confirmed.status, 'confirmed');
    expect(confirmed.programName, 'Upper/Lower 4x');

    // Confirmation is idempotent and the confirmed view exposes the program.
    final IntakeConfirmation again = await client.confirmIntake();
    expect(again.programName, 'Upper/Lower 4x');
    final OnboardingIntake confirmedView = await client.onboardingIntake();
    expect(confirmedView.isConfirmed, isTrue);
    expect(confirmedView.program!.hasProgram, isTrue);

    // Post-confirm edits are refused.
    await expectLater(
      client.saveIntakeAnswer('gender', 'male'),
      throwsA(isA<ApiException>()),
    );
  });

  test('invalid answers surface the server field message', () async {
    final FakeMayosApi fake = _signedInFake();
    final ApiClient client = await _client(fake);
    await client.acknowledgeIntakeDisclosure();

    await expectLater(
      client.saveIntakeAnswer('gender', 'other'),
      throwsA(
        isA<ApiException>()
            .having((ApiException e) => e.statusCode, 'statusCode', 400),
      ),
    );
    await expectLater(
      client.saveIntakeAnswer('age', 5),
      throwsA(
        isA<ApiException>()
            .having((ApiException e) => e.statusCode, 'statusCode', 400),
      ),
    );
  });

  test('required intake keys fail parsing instead of defaulting', () async {
    final FakeMayosApi fake = _signedInFake();
    fake.intakeMalformed = true;
    final ApiClient client = await _client(fake);

    await expectLater(
      client.onboardingIntake(),
      throwsA(isA<ApiException>()),
    );
  });

  test('answer field name is URL-encoded in the PUT path', () async {
    final FakeMayosApi fake = _signedInFake();
    final ApiClient client = await _client(fake);
    await client.acknowledgeIntakeDisclosure();

    await expectLater(
      client.saveIntakeAnswer('a b', 1),
      throwsA(isA<ApiException>()),
    );
    expect(
      fake.adapter.requests.last.path,
      contains('/onboarding/intake/answers/a%20b'),
    );
  });

  test('confirm requires every required answer', () async {
    final FakeMayosApi fake = _signedInFake();
    final ApiClient client = await _client(fake);
    await client.acknowledgeIntakeDisclosure();
    await client.saveIntakeAnswer('gender', 'female');

    await expectLater(
      client.confirmIntake(),
      throwsA(
        isA<ApiException>()
            .having((ApiException e) => e.statusCode, 'statusCode', 400),
      ),
    );
  });
}
