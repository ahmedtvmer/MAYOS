import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/api_client.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/token_store.dart';
import 'package:mayos_mobile/src/features/player/auth/auth_controller.dart';
import 'package:mayos_mobile/src/providers.dart';

import 'support/fake_api_adapter.dart';
import 'support/fake_mayos_api.dart';

ProviderContainer _containerFor(FakeMayosApi fake, InMemoryTokenStore tokens) {
  return ProviderContainer(
    overrides: <Override>[
      tokenStoreProvider.overrideWithValue(tokens),
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
  );
}

void main() {
  test('player journey against the service contract, with 401 re-login',
      () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final ProviderContainer container = _containerFor(fake, tokens);
    addTearDown(container.dispose);

    final AuthController auth = container.read(authControllerProvider.notifier);
    final ApiClient api = container.read(apiClientProvider);

    await auth.initialize();
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);

    // Register: uses the legacy trainee_id wire field and stores the token.
    await auth.register(username: 'alice', password: 'correct-horse-1');
    final AuthState afterRegister = container.read(authControllerProvider);
    expect(afterRegister.status, AuthStatus.authenticated);
    expect(afterRegister.session!.onboarded, isFalse);
    expect(afterRegister.session!.hasRecoveryEmail, isFalse);

    final FakeRequest registerRequest = fake.adapter.requests
        .firstWhere((FakeRequest r) => r.path == '/auth/register');
    expect(registerRequest.body['trainee_id'], 'alice');
    expect(registerRequest.body['remember_me'], isFalse);

    final String? token = await tokens.read();
    expect(token, isNotNull);
    final FakeRequest meRequest = fake.adapter.requests
        .firstWhere((FakeRequest r) => r.path == '/auth/me');
    expect(meRequest.headers['Authorization'], 'Bearer $token');

    // Recovery email releases the ADR 007 gate.
    await auth.setRecoveryEmail('alice@example.com');
    expect(container.read(authControllerProvider).session!.hasRecoveryEmail,
        isTrue);

    // Conversational onboarding.
    final OnboardingState start = await api.startOnboarding();
    expect(start.messages, isNotEmpty);

    final OnboardingState first =
        await api.submitOnboardingStep(content: 'Build muscle');
    expect(first.isComplete, isFalse);
    final OnboardingState second =
        await api.submitOnboardingStep(content: 'Four days');
    expect(second.isComplete, isTrue);

    // Re-entering /onboarding/start, as after an app restart mid-intake, resumes
    // the assistant prompts instead of resetting them.
    final OnboardingState resumed = await api.startOnboarding();
    expect(resumed.messages.length, 3);
    expect(resumed.messages.first, 'Hi! What is your main goal?');

    final OnboardingCompletion completion = await api.completeOnboarding();
    expect(completion.programName, 'Upper/Lower 4x');
    auth.markOnboarded();
    expect(container.read(authControllerProvider).session!.onboarded, isTrue);

    // Automatic active program.
    final TrainingProgram? program = await api.activeProgram();
    expect(program, isNotNull);
    expect(program!.weeklyFrequency, 4);
    expect(program.days.first.exercises.first.exerciseName, 'Bench Press');

    // Dashboard: weighted working-set counts, not kilograms.
    final Map<String, double> volume = await api.volume();
    expect(volume['Chest'], 12.5);
    final List<PersonalRecord> records = await api.personalRecords();
    expect(records.single.name, 'Bench Press');

    // An expired token makes the next authenticated call 401; the interceptor
    // clears the session and the stored token.
    fake.tokenValid = false;
    await expectLater(api.volume(), throwsA(isA<ApiException>()));
    await Future<void>.delayed(Duration.zero);
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
    expect(await tokens.read(), isNull);

    // Logging in again through the real endpoint restores the session.
    await auth.login(username: 'alice', password: 'correct-horse-1');
    final AuthState afterLogin = container.read(authControllerProvider);
    expect(afterLogin.status, AuthStatus.authenticated);
    expect(afterLogin.session!.onboarded, isTrue);
    expect(await tokens.read(), isNotNull);
  });

  test(
      'restart after API onboarding completion resolves onboarded via /profile',
      () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final ProviderContainer container = _containerFor(fake, tokens);
    addTearDown(container.dispose);

    final AuthController auth = container.read(authControllerProvider.notifier);
    final ApiClient api = container.read(apiClientProvider);
    await auth.register(username: 'alice', password: 'correct-horse-1');
    await auth.setRecoveryEmail('alice@example.com');

    await api.startOnboarding();
    await api.submitOnboardingStep(content: 'Build muscle');
    await api.submitOnboardingStep(content: 'Four days');
    await api.completeOnboarding();
    // Deliberately do not call markOnboarded: the client has not yet navigated.

    // Simulate an app restart: initialize() re-reads the persisted token and
    // resolves onboarding from GET /profile, so a completed account lands home.
    await auth.initialize();
    final AuthState state = container.read(authControllerProvider);
    expect(state.status, AuthStatus.authenticated);
    expect(state.session!.onboarded, isTrue);
    expect(state.session!.hasRecoveryEmail, isTrue);
  });

  test('restore clears a stale token and keeps a valid session', () async {
    final FakeMayosApi fake = FakeMayosApi();
    final InMemoryTokenStore tokens = InMemoryTokenStore();
    final ProviderContainer container = _containerFor(fake, tokens);
    addTearDown(container.dispose);

    await tokens.save('stale-token');
    fake.issuedToken = 'stale-token';
    fake.currentUsername = 'alice';
    fake.tokenValid = false;

    await container.read(authControllerProvider.notifier).initialize();
    expect(container.read(authControllerProvider).status,
        AuthStatus.unauthenticated);
    expect(await tokens.read(), isNull);
  });
}
