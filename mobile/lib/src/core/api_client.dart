import 'package:dio/dio.dart';

import 'models.dart';
import 'token_store.dart';

/// Raised for any failed service call, carrying the HTTP status when there was
/// a response and a human-readable message from the service `detail` field.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Thin typed wrapper over the FastAPI service.
///
/// Every request except register/login/logout carries the persisted bearer
/// token. A 401 on an authenticated request invokes [onUnauthorized] so the app
/// can clear the session and route back to login.
class ApiClient {
  ApiClient({
    required TokenStore tokens,
    required String baseUrl,
    HttpClientAdapter? adapter,
  }) : _tokens = tokens {
    _dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
      ),
    );
    _dio.httpClientAdapter = adapter ?? _dio.httpClientAdapter;
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: _attachToken,
        onError: _handleError,
      ),
    );
  }

  static const String _skipAuth = 'skipAuth';

  final TokenStore _tokens;
  late final Dio _dio;

  /// Invoked when an authenticated request fails with 401.
  void Function()? onUnauthorized;

  Dio get dio => _dio;

  Future<void> _attachToken(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (options.extra[_skipAuth] != true) {
      final String? token = await _tokens.read();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }

  void _handleError(DioException error, ErrorInterceptorHandler handler) {
    final bool skipped = error.requestOptions.extra[_skipAuth] == true;
    if (!skipped && error.response?.statusCode == 401) {
      onUnauthorized?.call();
    }
    handler.next(error);
  }

  Future<Response<dynamic>> _send(
      Future<Response<dynamic>> Function() run) async {
    try {
      return await run();
    } on DioException catch (error) {
      throw _toApiException(error);
    }
  }

  static ApiException _toApiException(DioException error) {
    final int? status = error.response?.statusCode;
    final dynamic data = error.response?.data;
    if (data is Map && data['detail'] is String) {
      return ApiException(data['detail'] as String, statusCode: status);
    }
    if (status == null) {
      return const ApiException(
          'Cannot reach the service. Check your connection.');
    }
    if (status >= 500) {
      return ApiException('The service is unavailable. Please retry.',
          statusCode: status);
    }
    return ApiException('Request failed ($status).', statusCode: status);
  }

  Future<AuthTokens> register({
    required String traineeId,
    required String password,
    bool rememberMe = false,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/register',
        data: {
          'trainee_id': traineeId,
          'password': password,
          'remember_me': rememberMe,
        },
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    return AuthTokens.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AuthTokens> login({
    required String traineeId,
    required String password,
    bool rememberMe = false,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/login',
        data: {
          'trainee_id': traineeId,
          'password': password,
          'remember_me': rememberMe,
        },
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    return AuthTokens.fromJson(response.data as Map<String, dynamic>);
  }

  Future<Account> currentAccount() async {
    final response = await _send(() => _dio.get<dynamic>('/auth/me'));
    return Account.fromJson(response.data as Map<String, dynamic>);
  }

  /// Redeems an owner-issued, single-use coach invite and returns the updated account.
  Future<Account> redeemCoachInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>('/coach/invite/redeem', data: {'token': token}),
    );
    return Account.fromJson(response.data as Map<String, dynamic>);
  }

  /// The authenticated coach's profile.
  Future<CoachProfile> coachProfile() async {
    final response = await _send(() => _dio.get<dynamic>('/coach/profile'));
    return CoachProfile.fromJson(response.data as Map<String, dynamic>);
  }

  /// Updates and returns the authenticated coach's profile.
  Future<CoachProfile> updateCoachProfile({
    required String displayName,
    required String bio,
    required String specialization,
    required int capacity,
  }) async {
    final response = await _send(
      () => _dio.put<dynamic>('/coach/profile', data: {
        'display_name': displayName,
        'bio': bio,
        'specialization': specialization,
        'capacity': capacity,
      }),
    );
    return CoachProfile.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> logout() async {
    await _send(() => _dio.post<dynamic>('/auth/logout'));
  }

  /// The account's recovery email, or null when none is set (ADR 007).
  Future<String?> recoveryEmail() async {
    final response = await _send(() => _dio.get<dynamic>('/auth/email'));
    return (response.data as Map<String, dynamic>)['email'] as String?;
  }

  /// Sets the recovery email and returns the normalized value.
  Future<String> setRecoveryEmail(String email) async {
    final response = await _send(
      () => _dio.post<dynamic>('/auth/email', data: {'email': email}),
    );
    final persistedEmail = (response.data as Map<String, dynamic>)['email'];
    if (persistedEmail is! String || persistedEmail.isEmpty) {
      throw const ApiException(
          'Could not confirm the recovery email. Please retry.');
    }
    return persistedEmail;
  }

  /// True when the account has completed onboarding (a profile exists).
  Future<bool> hasProfile() async {
    try {
      await _send(() => _dio.get<dynamic>('/profile'));
      return true;
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return false;
      }
      rethrow;
    }
  }

  Future<OnboardingState> startOnboarding() async {
    final response = await _send(() => _dio.post<dynamic>('/onboarding/start'));
    return OnboardingState.fromJson(response.data as Map<String, dynamic>);
  }

  Future<OnboardingState> submitOnboardingStep({
    String? content,
    bool reset = false,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/onboarding/step',
        data: {'content': content, 'reset': reset},
      ),
    );
    return OnboardingState.fromJson(response.data as Map<String, dynamic>);
  }

  Future<OnboardingCompletion> completeOnboarding() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/complete'));
    return OnboardingCompletion.fromJson(response.data as Map<String, dynamic>);
  }

  Future<TrainingProgram?> activeProgram() async {
    final response = await _send(() => _dio.get<dynamic>('/programs/active'));
    final dynamic data = response.data;
    if (data == null || data == '') {
      return null;
    }
    return TrainingProgram.fromJson(data as Map<String, dynamic>);
  }

  Future<Map<String, double>> volume({int days = 7}) async {
    final response = await _send(
      () => _dio
          .get<dynamic>('/dashboard/volume', queryParameters: {'days': days}),
    );
    final Map<String, dynamic> data = response.data as Map<String, dynamic>;
    return data.map(
      (String key, dynamic value) =>
          MapEntry<String, double>(key, (value as num).toDouble()),
    );
  }

  Future<List<PersonalRecord>> personalRecords({int limit = 20}) async {
    final response = await _send(
      () => _dio.get<dynamic>('/dashboard/personal-records',
          queryParameters: {'limit': limit}),
    );
    final List<dynamic> data = response.data as List<dynamic>;
    return data
        .map((dynamic item) =>
            PersonalRecord.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }
}
