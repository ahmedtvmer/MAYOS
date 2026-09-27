import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'chat_models.dart';
import 'models.dart';
import 'sse.dart';
import 'token_store.dart';

/// Raised for any failed service call, carrying the HTTP status when there was
/// a response and a human-readable message from the service `detail` field.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode, this.errorCode});

  final String message;
  final int? statusCode;

  /// A machine-readable `error` code from the service, when it sent one.
  final String? errorCode;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// The result of `POST /workouts/sessions`, carrying whether this call created
/// the session (201) or replayed an already-committed one (200).
class WorkoutCommitResult {
  const WorkoutCommitResult({required this.statusCode, required this.body});

  final int statusCode;
  final Map<String, dynamic> body;

  bool get created => statusCode == 201;
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
  static const String _invalidAlerts =
      'The service returned invalid alert data.';
  static const String _invalidCheckIns =
      'The service returned invalid check-in data.';
  static const String _invalidProgram =
      'The service returned invalid program data.';
  static const String _invalidNotices =
      'The service returned invalid assignment notices.';
  static const String _invalidProgramRequests =
      'The service returned invalid program request data.';
  static const String _invalidProfile =
      'The service returned invalid profile data.';
  static const String _invalidSchedule =
      'The service returned invalid training schedule data.';
  static const String _invalidChat = 'The service returned invalid chat data.';

  final TokenStore _tokens;
  late final Dio _dio;

  /// Invoked when an authenticated request fails with 401.
  void Function()? onUnauthorized;

  /// Invoked when an authenticated request fails with 401 carrying the
  /// `account_deleted` signal, so the app can erase that account's protected
  /// local data without the logout keep/discard prompt (ADR 039).
  void Function()? onAccountDeleted;

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
      final dynamic data = error.response?.data;
      if (data is Map && data['error'] == 'account_deleted') {
        onAccountDeleted?.call();
      } else {
        onUnauthorized?.call();
      }
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
    if (data is Map) {
      final Map<String, dynamic> body = Map<String, dynamic>.from(data);
      if (body['detail'] is String) {
        return ApiException(body['detail'] as String, statusCode: status);
      }
      if (body['error'] is String) {
        return ApiException(
          _messageForError(body['error'] as String),
          statusCode: status,
          errorCode: body['error'] as String,
        );
      }
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

  static String _messageForError(String code) => switch (code) {
        'program_version_mismatch' =>
          'This workout was logged against an older program version.',
        _ => 'The service rejected this request.',
      };

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

  /// Lists the coach's missed-day alerts (ADR 030); defaults to new + acknowledged.
  Future<List<CoachAlert>> coachAlerts({List<String>? states}) async {
    final response = await _send(
      () => _dio.get<dynamic>(
        '/coach/alerts',
        queryParameters: (states == null || states.isEmpty)
            ? null
            : <String, dynamic>{'state': states},
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['alerts'] is! List<dynamic>) {
      throw const ApiException(_invalidAlerts);
    }
    return _parseBodyList(data['alerts'], CoachAlert.fromJson, _invalidAlerts);
  }

  /// Acknowledges one missed-day alert; already acknowledged is idempotent.
  Future<CoachAlert> acknowledgeCoachAlert(String alertId) async {
    final response = await _send(
        () => _dio.post<dynamic>('/coach/alerts/$alertId/acknowledge'));
    return _parseBody(response.data, CoachAlert.fromJson, _invalidAlerts);
  }

  /// Resolves one missed-day alert; already resolved is idempotent.
  Future<CoachAlert> resolveCoachAlert(String alertId) async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/alerts/$alertId/resolve'));
    return _parseBody(response.data, CoachAlert.fromJson, _invalidAlerts);
  }

  /// Lists an actively assigned player's check-ins, newest date first (ADR 031).
  Future<List<CheckIn>> coachCheckIns(String assignmentId) async {
    final response = await _send(
      () => _dio.get<dynamic>('/coach/assignments/$assignmentId/check-ins'),
    );
    return _parseCheckInList(response.data);
  }

  /// Records an immutable check-in for an actively assigned player (ADR 031).
  Future<CheckInCreation> createCoachCheckIn(
    String assignmentId, {
    required String checkedInOn,
    required String channel,
    String? note,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'checked_in_on': checkedInOn,
      'channel': channel,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
    };
    final response = await _send(
      () => _dio.post<dynamic>(
        '/coach/assignments/$assignmentId/check-ins',
        data: body,
      ),
    );
    return _parseBody(
        response.data, CheckInCreation.fromJson, _invalidCheckIns);
  }

  /// Lists the player's check-ins across all assignments, including ended ones.
  Future<List<CheckIn>> playerCheckIns() async {
    final response =
        await _send(() => _dio.get<dynamic>('/assignments/me/check-ins'));
    return _parseCheckInList(response.data);
  }

  List<CheckIn> _parseCheckInList(dynamic responseData) {
    if (responseData is! Map<String, dynamic> ||
        responseData['check_ins'] is! List<dynamic>) {
      throw const ApiException(_invalidCheckIns);
    }
    return _parseBodyList(
        responseData['check_ins'], CheckIn.fromJson, _invalidCheckIns);
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
    if (data is! Map<String, dynamic> || data['notices'] is! List<dynamic>) {
      throw const ApiException(_invalidNotices);
    }
    return _parseBodyList(
        data['notices'], AssignmentNotice.fromJson, _invalidNotices);
  }

  /// Marks all of the player's notices read, returning how many were marked.
  Future<int> markPlayerNoticesRead() async {
    final response =
        await _send(() => _dio.post<dynamic>('/assignments/notices/read'));
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
    final response = await _send(() => _dio
        .post<dynamic>('/programs/generate', data: const <String, dynamic>{}));
    return _parseBody(response.data, TrainingProgram.fromJson, _invalidProgram);
  }

  /// Coach revokes an assignment; access is revoked immediately.
  Future<void> revokeAssignment(String assignmentId) async {
    await _send(
        () => _dio.post<dynamic>('/coach/assignments/$assignmentId/revoke'));
  }

  /// Ends every assignment and disables the coach capability, preserving player data.
  Future<int> disableCoachCapability() async {
    final response =
        await _send(() => _dio.post<dynamic>('/coach/capability/disable'));
    return ((response.data as Map<String, dynamic>)['ended_assignments']
                as num?)
            ?.toInt() ??
        0;
  }

  Future<void> logout() async {
    await _send(() => _dio.post<dynamic>('/auth/logout'));
  }

  /// Password-confirmed, irreversible account deletion (`DELETE /auth/account`).
  ///
  /// A wrong password is a plain 400 refusal that changes nothing; a transport
  /// failure raises [ApiException] with a null status code. On success every
  /// server session is ended and the account's ledger removed (ADR 015/039).
  Future<void> deleteAccount(String password) async {
    await _send(
      () => _dio.delete<dynamic>(
        '/auth/account',
        data: <String, dynamic>{'password': password},
      ),
    );
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

  /// Requests a reset link for [email].
  ///
  /// Always resolves to the service's constant confirmation message
  /// (anti-enumeration): nothing is disclosed about whether the email is linked.
  Future<String> forgotPassword(String email) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/auth/forgot-password',
        data: <String, dynamic>{'email': email},
        options: Options(extra: {_skipAuth: true}),
      ),
    );
    final dynamic message = (response.data as Map<String, dynamic>)['message'];
    return message is String ? message : '';
  }

  /// Redeems a single-use reset token for a new password.
  ///
  /// An unknown, expired, or reused token surfaces the service's one generic
  /// 400 message; a success revokes every prior session server-side.
  Future<void> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    await _send(
      () => _dio.post<dynamic>(
        '/auth/reset-password',
        data: <String, dynamic>{'token': token, 'new_password': newPassword},
        options: Options(extra: {_skipAuth: true}),
      ),
    );
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

  /// The player's current expected training schedule, all versions, and active pauses.
  Future<TrainingSchedule> trainingSchedule() async {
    final response = await _send(() => _dio.get<dynamic>('/profile/schedule'));
    return _parseBody(
        response.data, TrainingSchedule.fromJson, _invalidSchedule);
  }

  /// Appends a new effective-dated schedule version; the program is never touched.
  Future<TrainingScheduleSetResult> setTrainingSchedule({
    required List<int> weekdays,
    required String timezone,
    String? effectiveFrom,
  }) async {
    final Map<String, dynamic> body = <String, dynamic>{
      'weekdays': weekdays,
      'timezone': timezone,
      if (effectiveFrom != null) 'effective_from': effectiveFrom,
    };
    final response = await _send(
      () => _dio.put<dynamic>('/profile/schedule', data: body),
    );
    return _parseBody(
        response.data, TrainingScheduleSetResult.fromJson, _invalidSchedule);
  }

  /// All pauses the player has scheduled, newest-first.
  Future<List<ScheduledPause>> trainingPauses() async {
    final response =
        await _send(() => _dio.get<dynamic>('/profile/schedule/pauses'));
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['pauses'] is! List<dynamic>) {
      throw const ApiException(_invalidSchedule);
    }
    return _parseBodyList(
        data['pauses'], ScheduledPause.fromJson, _invalidSchedule);
  }

  /// Stores a prospective pause (max 14 days, no reason); the assigned coach is
  /// best-effort notified.
  Future<TrainingPauseCreateResult> createTrainingPause({
    required String startsOn,
    required String endsOn,
  }) async {
    final response = await _send(
      () => _dio.post<dynamic>(
        '/profile/schedule/pauses',
        data: <String, dynamic>{'starts_on': startsOn, 'ends_on': endsOn},
      ),
    );
    return _parseBody(
        response.data, TrainingPauseCreateResult.fromJson, _invalidSchedule);
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

  /// The structured, resumable intake contract (`GET /onboarding/intake`, #50).
  Future<OnboardingIntake> onboardingIntake() async {
    final response = await _send(() => _dio.get<dynamic>('/onboarding/intake'));
    return _parseBody(response.data, OnboardingIntake.fromJson,
        'The service returned invalid onboarding intake data.');
  }

  /// Acknowledges the hosted-processing disclosure before any answer is saved
  /// (`POST /onboarding/intake/disclosure`, ADR 016/036).
  Future<OnboardingIntake> acknowledgeIntakeDisclosure() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/intake/disclosure'));
    return _parseBody(response.data, OnboardingIntake.fromJson,
        'The service returned invalid onboarding intake data.');
  }

  /// Validates and saves one named intake answer
  /// (`PUT /onboarding/intake/answers/{field}`, #50). Idempotent until confirmed.
  Future<OnboardingIntake> saveIntakeAnswer(String field, Object? value) async {
    final response = await _send(
      () => _dio.put<dynamic>(
          '/onboarding/intake/answers/${Uri.encodeComponent(field)}',
          data: <String, dynamic>{'value': value}),
    );
    return _parseBody(response.data, OnboardingIntake.fromJson,
        'The service returned invalid onboarding intake data.');
  }

  /// Writes the confirmed profile and creates the first program once
  /// (`POST /onboarding/intake/confirm`, #50).
  Future<IntakeConfirmation> confirmIntake() async {
    final response =
        await _send(() => _dio.post<dynamic>('/onboarding/intake/confirm'));
    return _parseBody(response.data, IntakeConfirmation.fromJson,
        'The service returned invalid onboarding confirmation data.');
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

  /// Auto-regulated targets for one training day (`GET /workouts/prescription`).
  Future<Prescription> prescription(int dayOrder) async {
    final response = await _send(
      () => _dio.get<dynamic>('/workouts/prescription',
          queryParameters: <String, dynamic>{'day_order': dayOrder}),
    );
    return _parseBody(response.data, Prescription.fromJson,
        'The service returned invalid prescription data.');
  }

  /// Catalog exercises matching [query], for picking a real unplanned
  /// exercise (`GET /workouts/exercises?query=`, ADR 020/033, #34).
  Future<List<ExerciseCatalogEntry>> searchExercises(String query) async {
    final response = await _send(
      () => _dio.get<dynamic>('/workouts/exercises',
          queryParameters: <String, dynamic>{'query': query}),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic> || data['exercises'] is! List) {
      throw const ApiException('The service returned invalid exercise data.');
    }
    return _parseBodyList(data['exercises'], ExerciseCatalogEntry.fromJson,
        'The service returned invalid exercise data.');
  }

  /// Read-only catalog detail for one exercise (`GET /workouts/exercises/{id}`, #53).
  Future<ExerciseCatalogDetail> exerciseCatalogDetail(String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
          '/workouts/exercises/${Uri.encodeComponent(exerciseId)}'),
    );
    return _parseBody(response.data, ExerciseCatalogDetail.fromJson,
        'The service returned invalid exercise data.');
  }

  /// Progression history for one exercise (`GET /dashboard/exercises/{id}/history`).
  Future<ExerciseHistory> exerciseHistory(String exerciseId) async {
    final response = await _send(
      () => _dio.get<dynamic>(
          '/dashboard/exercises/${Uri.encodeComponent(exerciseId)}/history'),
    );
    return _parseBody(response.data, ExerciseHistory.fromJson,
        'The service returned invalid exercise history data.');
  }

  /// The player's most recent committed session, or null when none (#53).
  ///
  /// Home derives the next program day from this real ledger value; a 404 means
  /// the player has no committed sessions yet, not an error.
  Future<LatestSession?> latestSession() async {
    try {
      final response = await _send(
        () => _dio.get<dynamic>('/workouts/sessions/latest'),
      );
      final dynamic data = response.data;
      if (data is! Map<String, dynamic>) {
        throw const ApiException('The service returned invalid session data.');
      }
      return LatestSession.fromJson(data);
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return null;
      }
      rethrow;
    }
  }

  /// Commits one workout, creating it (201) or replaying a stored commit (200).
  ///
  /// The body may carry the offline-sync fields; the service is idempotent on
  /// `client_session_id`.
  Future<WorkoutCommitResult> commitWorkoutSession(
      Map<String, dynamic> body) async {
    final response = await _send(
      () => _dio.post<dynamic>('/workouts/sessions', data: body),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      throw const ApiException('The service returned invalid session data.');
    }
    return WorkoutCommitResult(
      statusCode: response.statusCode ?? 201,
      body: data,
    );
  }

  /// The stored commit for a client session id, or null when never committed.
  ///
  /// Used to reconcile a lost response before retrying so a committed workout
  /// is never sent twice.
  Future<Map<String, dynamic>?> sessionByClientId(
      String clientSessionId) async {
    try {
      final response = await _send(
        () => _dio
            .get<dynamic>('/workouts/sessions/by-client-id/$clientSessionId'),
      );
      final dynamic data = response.data;
      if (data is! Map<String, dynamic>) {
        throw const ApiException('The service returned invalid session data.');
      }
      return data;
    } on ApiException catch (error) {
      if (error.statusCode == 404) {
        return null;
      }
      rethrow;
    }
  }

  /// Corrects a recent committed session's performed date (`PATCH
  /// /workouts/sessions/{id}/performed-date`, ADR 020/035).
  ///
  /// Requires connectivity and raises [ApiException] on refusal (400 out of
  /// window, 409 too old, 404 unknown) so the UI can surface a clear error.
  Future<Map<String, dynamic>> correctSessionPerformedDate(
      String sessionId, String performedDate) async {
    final response = await _send(
      () => _dio.patch<dynamic>(
        '/workouts/sessions/$sessionId/performed-date',
        data: <String, dynamic>{'performed_date': performedDate},
      ),
    );
    final dynamic data = response.data;
    if (data is! Map<String, dynamic>) {
      throw const ApiException('The service returned invalid session data.');
    }
    return data;
  }

  /// The player's persisted assistant-chat history, oldest-first
  /// (`GET /chat/history`, ADR 016).
  Future<List<ChatMessage>> chatHistory() async {
    final response = await _send(() => _dio.get<dynamic>('/chat/history'));
    final dynamic data = response.data;
    if (data is! List<dynamic>) {
      throw const ApiException(_invalidChat);
    }
    return _parseBodyList(data, ChatMessage.fromJson, _invalidChat);
  }

  /// Clears the player's assistant-chat history (`DELETE /chat/history`).
  Future<void> clearChatHistory() async {
    await _send(() => _dio.delete<dynamic>('/chat/history'));
  }

  /// Streams one assistant turn as decoded SSE events (`POST /chat/messages`).
  ///
  /// Tokens arrive incrementally via [ChatToken]; the final [ChatDone] reports
  /// the persisted reply and whether the program changed. A failed turn is a
  /// [ChatError] frame. Any transport failure while the stream is open — a
  /// dropped connection, or a non-2xx body such as a 429 rate limit — surfaces
  /// as an [ApiException] (network failures have a null status code) so the
  /// caller can show a needs-connection/refusal state and never treat a
  /// partial reply as finished.
  Stream<ChatStreamEvent> streamChatMessage(String content) async* {
    final Response<ResponseBody> response;
    try {
      response = await _dio.post<ResponseBody>(
        '/chat/messages',
        data: <String, dynamic>{'content': content},
        options: Options(responseType: ResponseType.stream),
      );
    } on DioException catch (error) {
      throw _toApiException(error);
    }

    final dynamic body = response.data;
    final Stream<Uint8List>? bytes = body is ResponseBody ? body.stream : null;
    if (bytes == null) {
      throw const ApiException(
          'The service returned no message stream. Check your connection.');
    }

    // A non-2xx response (e.g. 429 from CHAT_LIMIT) is still a stream: read it
    // as JSON to surface the server's `detail` instead of an empty SSE body.
    final int status = response.statusCode ?? 200;
    if (status < 200 || status >= 300) {
      final String raw = await _readStream(bytes);
      throw _errorFromResponse(status, raw);
    }

    final SseDecoder decoder = SseDecoder();
    try {
      await for (final String chunk in _decodeUtf8(bytes)) {
        for (final SseEvent event in decoder.addChunk(chunk)) {
          final ChatStreamEvent? parsed = _parseChatEvent(event);
          if (parsed != null) {
            yield parsed;
          }
        }
      }
      for (final SseEvent event in decoder.close()) {
        final ChatStreamEvent? parsed = _parseChatEvent(event);
        if (parsed != null) {
          yield parsed;
        }
      }
    } on DioException catch (error) {
      // The connection dropped mid-stream: treat it as a transient failure so
      // the screen enters its error/offline state and can retry.
      throw _toApiException(error);
    } on ApiException {
      rethrow;
    } on FormatException {
      throw const ApiException(
          'The service sent an unreadable chat stream. Please retry.');
    }
  }

  /// Decodes [bytes] as streaming UTF-8 so a multibyte character split across
  /// two network chunks is reassembled rather than mangled. [utf8.decoder] is
  /// a chunked converter, so it carries partial sequence state across chunks.
  Stream<String> _decodeUtf8(Stream<List<int>> bytes) =>
      utf8.decoder.bind(bytes);

  Future<String> _readStream(Stream<Uint8List> bytes) async {
    final List<int> collected = <int>[];
    await for (final Uint8List chunk in bytes) {
      collected.addAll(chunk);
    }
    return utf8.decode(collected, allowMalformed: true);
  }

  /// Builds an [ApiException] from a non-2xx streamed body, surfacing the
  /// server's `detail` (e.g. the rate-limit message) when present.
  ApiException _errorFromResponse(int status, String raw) {
    final String trimmed = raw.trim();
    if (trimmed.isNotEmpty) {
      try {
        final dynamic decoded = jsonDecode(trimmed);
        if (decoded is Map && decoded['detail'] is String) {
          return ApiException(decoded['detail'] as String, statusCode: status);
        }
      } on FormatException {
        // Fall through to the status-based message below.
      }
    }
    if (status >= 500) {
      return ApiException('The service is unavailable. Please retry.',
          statusCode: status);
    }
    return ApiException('Request failed ($status).', statusCode: status);
  }

  ChatStreamEvent? _parseChatEvent(SseEvent event) {
    final dynamic decoded = jsonDecode(event.data);
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    if (event.event == 'error') {
      final dynamic detail = decoded['detail'];
      return ChatError(detail is String && detail.isNotEmpty
          ? detail
          : 'The assistant could not answer. Please retry.');
    }
    if (decoded['done'] == true) {
      return ChatDone(
        responseContent: decoded['response_content'] is String
            ? decoded['response_content'] as String
            : '',
        programUpdated: decoded['program_updated'] == true,
      );
    }
    final dynamic token = decoded['token'];
    return token is String ? ChatToken(token) : null;
  }
}
