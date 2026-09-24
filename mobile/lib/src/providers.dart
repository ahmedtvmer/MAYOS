import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/api_client.dart';
import 'core/config.dart';
import 'core/token_store.dart';
import 'features/player/auth/auth_controller.dart';
import 'features/player/auth/auth_repository.dart';

final Provider<TokenStore> tokenStoreProvider = Provider<TokenStore>(
  (ref) => SecureTokenStore(),
);

final Provider<UnauthorizedEvents> unauthorizedEventsProvider =
    Provider<UnauthorizedEvents>((ref) {
  final UnauthorizedEvents events = UnauthorizedEvents();
  ref.onDispose(events.dispose);
  return events;
});

final Provider<ApiClient> apiClientProvider = Provider<ApiClient>((ref) {
  final TokenStore tokens = ref.watch(tokenStoreProvider);
  final ApiClient client = ApiClient(tokens: tokens, baseUrl: apiBaseUrl);
  client.onUnauthorized = ref.watch(unauthorizedEventsProvider).signal;
  return client;
});

final Provider<AuthRepository> authRepositoryProvider =
    Provider<AuthRepository>(
  (ref) => AuthRepository(
    api: ref.watch(apiClientProvider),
    tokens: ref.watch(tokenStoreProvider),
  ),
);

final StateNotifierProvider<AuthController, AuthState> authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(
    ref.watch(authRepositoryProvider),
    ref.watch(unauthorizedEventsProvider),
  );
});
