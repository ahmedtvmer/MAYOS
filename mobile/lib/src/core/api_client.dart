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
  static const String _invalidCoachHistory =
      'The service returned invalid coach history data.';
  static const String _invalidProgram =
      'The service returned invalid program data.';
  static const String _invalidNotices =
      'The service returned invalid assignment notices.';
  static const String _invalidProgramRequests =
      'The service returned invalid program request data.';
  static const String _invalidProfile =
      'The service returned invalid profile data.';

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
    return _parseAccount(response.data);
  }

  /// Redeems an owner-issued, single-use coach invite and returns the updated account.
  Future<Account> redeemCoachInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>('/coach/invite/redeem', data: {'token': token}),
    );
    return _parseAccount(response.data);
  }

  Account _parseAccount(dynamic responseData) => _parseBody(
        responseData,
        Account.fromJson,
        'The service returned invalid account status.',
      );

  T _parseBody<T>(
    dynamic responseData,
    T Function(Map<String, dynamic>) parse,
    String invalidMessage,
  ) {
    if (responseData is! Map<String, dynamic>) {
      throw ApiException(invalidMessage);
    }
    try {
      return parse(responseData);
    } on FormatException {
      throw ApiException(invalidMessage);
    } on TypeError {
      throw ApiException(invalidMessage);
    }
  }

  List<T> _parseBodyList<T>(
    dynamic responseData,
    T Function(Map<String, dynamic>) parse,
    String invalidMessage,
  ) {
    if (responseData is! List<dynamic>) {
      throw ApiException(invalidMessage);
    }
    try {
      return responseData.map((dynamic item) {
        if (item is! Map<String, dynamic>) {
          throw const FormatException('Invalid entry.');
        }
        return parse(item);
      }).toList(growable: false);
    } on FormatException {
      throw ApiException(invalidMessage);
    } on TypeError {
      throw ApiException(invalidMessage);
    }
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

  /// Previews a coach assignment invite. The code is sent in the body and is not consumed.
  Future<AssignmentInvitePreview> previewAssignmentInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/assignments/invites/preview',
        data: {'token': token},
      ),
    );
    return AssignmentInvitePreview.fromJson(
        response.data as Map<String, dynamic>);
  }

  /// Explicitly consents to and redeems a single-use assignment invite.
  Future<Assignment> redeemAssignmentInvite(String token) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/assignments/invites/redeem',
        data: {'token': token, 'consent': true},
      ),
    );
    final Map<String, dynamic> body = response.data as Map<String, dynamic>;
    return Assignment.fromJson(body['assignment'] as Map<String, dynamic>);
  }

  /// The caller's active assignment, or null when none is active.
  Future<Assignment?> myAssignment() async {
    final response = await _send(() => _dio.get<dynamic>('/assignments/me'));
    final dynamic data = response.data;
    if (data == null || data == '') {
      return null;
    }
    return Assignment.fromJson(data as Map<String, dynamic>);
  }

  /// Ends the caller's active assignment; access is revoked immediately.
  Future<void> endMyAssignment() async {
    await _send(() => _dio.post<dynamic>('/assignments/me/end'));
  }

  /// Coach issues a single-use, capacity-bound assignment invite.
  Future<AssignmentInvite> issueAssignmentInvite() async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/assignments/invites'));
    return AssignmentInvite.fromJson(response.data as Map<String, dynamic>);
  }

  /// Lists the coach's active assignments (identity only, no training history).
  Future<List<CoachRosterEntry>> coachAssignments() async {
    final response = await _send(() => _dio.get<dynamic>('/coach/assignments'));
    final List<dynamic> data =
        (response.data as Map<String, dynamic>)['assignments'] as List<dynamic>;
    return data
        .map((dynamic item) =>
            CoachRosterEntry.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  /// Volume and recent sessions for an actively assigned player.
  Future<CoachPlayerSummary> coachPlayerSummary(String assignmentId,
      {int days = 7}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/summary',
        queryParameters: <String, dynamic>{'days': days},
      ),
    );
    return _parseBody(
        response.data, CoachPlayerSummary.fromJson, _invalidCoachHistory);
  }

  /// The assigned player's recent personal records, newest-first.
  Future<List<PersonalRecord>> coachPlayerPersonalRecords(String assignmentId,
      {int limit = 20}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/personal-records',
        queryParameters: <String, dynamic>{'limit': limit},
      ),
    );
    return _parseBodyList(
        response.data, PersonalRecord.fromJson, _invalidCoachHistory);
  }

  /// The distinct exercises the assigned player has logged.
  Future<List<CoachPlayerExercise>> coachPlayerExercises(
      String assignmentId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/exercises',
      ),
    );
    return _parseBody(
      response.data,
      (Map<String, dynamic> json) => (json['exercises'] as List<dynamic>)
          .map((dynamic item) =>
              CoachPlayerExercise.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      _invalidCoachHistory,
    );
  }

  /// Progression history, latest caption, and records for one logged exercise.
  Future<CoachExerciseHistory> coachPlayerExerciseHistory(
      String assignmentId, String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/assignments/$assignmentId/player/exercises/$exerciseId/history',
      ),
    );
    return _parseBody(
        response.data, CoachExerciseHistory.fromJson, _invalidCoachHistory);
  }

  /// Lists the coach's assignment notices, newest-first.
  Future<List<AssignmentNotice>> coachNotices() async {
    final response =
        await _send(() => _dio.get<dynamic>('/coach/assignments/notices'));
    final List<dynamic> data =
        (response.data as Map<String, dynamic>)['notices'] as List<dynamic>;
    return data
        .map((dynamic item) =>
            AssignmentNotice.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  /// Marks all of the coach's notices read.
  Future<int> markCoachNoticesRead() async {
    final response = await _send(
        () => _dio.post<dynamic>('/coach/assignments/notices/read'));
    return ((response.data as Map<String, dynamic>)['marked_read'] as num?)
            ?.toInt() ??
        0;
  }

  /// Publishes a coach-authored program for an assigned player (ADR 026).
  ///
  /// Null overrides are omitted from the body so the pipeline applies its
  /// defaults. Returns the persisted program with its stable version and
  /// provenance. A missing/foreign/ended assignment denies.
  Future<TrainingProgram> coachPublishProgram(
    String assignmentId, {
    String? splitOverride,
    String? repPreference,
    int? frequency,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      if (splitOverride != null) 'user_split_override': splitOverride,
      if (repPreference != null) 'rep_preference_override': repPreference,
      if (frequency != null) 'frequency_override': frequency,
    };
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program',
        data: body,
      ),
    );
    return _parseBody(response.data, TrainingProgram.fromJson, _invalidProgram);
  }

  /// Lists the player's assignment notices, newest-first.
  Future<List<AssignmentNotice>> playerNotices() async {
    final response =
        await _send(() => _dio.get<dynamic>('/assignments/notices'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> ||
        data['notices'] is! List<dynamic>) {
      throw const ApiException(_invalidNotices);
    }
    return _parseBodyList(
        data['notices'], AssignmentNotice.fromJson, _invalidNotices);
  }

  /// Marks all of the player's notices read, returning how many were marked.
  Future<int> markPlayerNoticesRead() async {
    final response = await _send(
        () => _dio.post<dynamic>('/assignments/notices/read'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['marked_read'] is! num) {
      throw const ApiException(_invalidNotices);
    }
    return (data['marked_read'] as num).toInt();
  }

  /// Lists the player's own program requests, newest-first (ADR 027).
  Future<List<ProgramRequest>> playerProgramRequests() async {
    final response = await _send(
        () => _dio.get<dynamic>('/assignments/me/program-requests'));
    return _parseProgramRequestList(response.data);
  }

  /// Records a pending program request against the player's coach-controlled
  /// program; the program itself is never changed by creating a request.
  Future<ProgramRequest> createPlayerProgramRequest({
    required String kind,
    String? dayName,
    String? exerciseId,
    String? replacementExerciseId,
    int? desiredWeeklyFrequency,
    String? desiredSplitPreference,
    required String reason,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'kind': kind,
      if (dayName != null) 'day_name': dayName,
      if (exerciseId != null) 'exercise_id': exerciseId,
      if (replacementExerciseId != null)
        'replacement_exercise_id': replacementExerciseId,
      if (desiredWeeklyFrequency != null)
        'desired_weekly_frequency': desiredWeeklyFrequency,
      if (desiredSplitPreference != null)
        'desired_split_preference': desiredSplitPreference,
      'reason': reason,
    };
    final response = await _send(
      () => _dio.post<dynamic>('/assignments/me/program-requests', data: body),
    );
    return _parseBody(
        response.data, ProgramRequest.fromJson, _invalidProgramRequests);
  }

  /// Cancels the player's own pending request.
  Future<ProgramRequest> cancelPlayerProgramRequest(String requestId) async {
    final response = await _send(
      () => _dio
          .post<dynamic>('/assignments/me/program-requests/$requestId/cancel'),
    );
    return _parseBody(
        response.data, ProgramRequest.fromJson, _invalidProgramRequests);
  }

  /// Lists an actively assigned player's program requests for the coach.
  Future<List<ProgramRequest>> coachProgramRequests(String assignmentId) async {
    final response = await _send(
      () => _dio
          .get<dynamic>('/coach/assignments/$assignmentId/program-requests'),
    );
    return _parseProgramRequestList(response.data);
  }

  /// Revalidates and applies a pending request, publishing a new program version.
  Future<ProgramRequest> applyCoachProgramRequest(
      String assignmentId, String requestId) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program-requests/$requestId/apply',
      ),
    );
    return _parseBody(
        response.data, ProgramRequest.fromJson, _invalidProgramRequests);
  }

  /// Declines a pending request with a short player-visible response.
  Future<ProgramRequest> declineCoachProgramRequest(
      String assignmentId, String requestId, String response) async {
    final httpResponse = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/program-requests/$requestId/decline',
        data: <String, dynamic>{'response': response},
      ),
    );
    return _parseBody(
        httpResponse.data, ProgramRequest.fromJson, _invalidProgramRequests);
  }

  List<ProgramRequest> _parseProgramRequestList(dynamic data) {
    if (data is! Map<String, dynamic> || data['requests'] is! List<dynamic>) {
      throw const ApiException(_invalidProgramRequests);
    }
    return _parseBodyList(
        data['requests'], ProgramRequest.fromJson, _invalidProgramRequests);
  }

  /// Regenerates the player's own program (self-service), refused 403 while an
  /// assigned coach's published program is active.
  Future<TrainingProgram> playerGenerateProgram() async {
    final response = await _send(
        () => _dio.post<dynamic>('/programs/generate', data: const <String, dynamic>{}));
    return _parseBody(response.data, TrainingProgram.fromJson, _invalidProgram);
  }

  /// Coach revokes an assignment; access is revoked immediately.
  Future<void> revokeAssignment(String assignmentId) async {
    await _send(
        () => _dio.post<dynamic>('/coach/assignments/$assignmentId/revoke'));
  }

  /// Ends every assignment and disables the coach capability, preserving player data.
  Future<int> disableCoachCapability() async {
    final response = await _send(
        () => _dio.post<dynamic>('/coach/capability/disable'));
    return ((response.data as Map<String, dynamic>)['ended_assignments']
                as num?)
            ?.toInt() ??
        0;
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

  /// The player's stored training profile.
  Future<PlayerProfile> profile() async {
    final response = await _send(() => _dio.get<dynamic>('/profile'));
    return _parseBody(response.data, PlayerProfile.fromJson, _invalidProfile);
  }

  /// Updates the player's profile. A profile-triggered rebuild is a player
  /// write path, so the response reports when a coach-controlled program left
  /// it unchanged instead of refusing the profile update itself.
  Future<ProfileUpdateResult> updateProfile({
    int? weeklyFrequency,
    String? repPreference,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      if (weeklyFrequency != null) 'weekly_frequency': weeklyFrequency,
      if (repPreference != null) 'rep_preference': repPreference,
    };
    final response = await _send(
      () => _dio.put<dynamic>('/profile', data: body),
    );
    return _parseBody(
        response.data, ProfileUpdateResult.fromJson, _invalidProfile);
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
