/// Wire models mirroring the FastAPI service contracts in `svc/schemas.py` and
/// `agent/ProgramState.py`.
library;

import 'config.dart';
import 'effort.dart';
import 'rest_length.dart';

const String equipmentAccessCommercialGym = 'Commercial gym';
const String equipmentAccessHomeGym = 'Home gym';
const String equipmentAccessBodyweightOnly = 'Bodyweight only';
const List<String> equipmentAccessValues = <String>[
  equipmentAccessCommercialGym,
  equipmentAccessHomeGym,
  equipmentAccessBodyweightOnly,
];
const String defaultAssistantStyle = 'direct';
const int maxAssistantStyleInstructions = 500;
const String deloadChoiceUndo = 'undo';
const String deloadChoiceApply = 'apply';

class Capabilities {
  const Capabilities({required this.player, required this.coach});

  factory Capabilities.fromJson(Map<String, dynamic> json) => Capabilities(
        player: json['player'] as bool? ?? false,
        coach: json['coach'] as bool? ?? false,
      );

  final bool player;
  final bool coach;
}

/// One capability's server-owned plan state. The client only displays it; it
/// never infers an entitlement from the user or the device.
class PlanState {
  const PlanState({required this.plan, required this.status});

  factory PlanState.fromJson(Map<String, dynamic> json) {
    final dynamic rawPlan = json['plan'];
    final dynamic rawStatus = json['status'];
    if (rawPlan is! String || rawStatus is! String) {
      throw const FormatException('Invalid plan state.');
    }
    final String plan = rawPlan;
    if (plan != 'free' && plan != 'pro') {
      throw FormatException('Unknown plan: $plan');
    }
    return PlanState(plan: plan, status: rawStatus);
  }

  final String plan;
  final String status;

  bool get isPro => plan == 'pro';

  bool get isFree => plan == 'free';

  String get label => isPro ? 'Pro' : 'Free';
}

/// Independent Lifter and Coach plan states. A null entry means the account
/// does not hold that capability, so it has no plan for it.
class AccountPlans {
  const AccountPlans({this.lifter, this.coach});

  factory AccountPlans.fromJson(Map<String, dynamic> json) => AccountPlans(
        lifter: _state(json['lifter']),
        coach: _state(json['coach']),
      );

  final PlanState? lifter;
  final PlanState? coach;

  static PlanState? _state(dynamic value) {
    if (value == null) return null;
    if (value is! Map<String, dynamic>) {
      throw const FormatException('Invalid plan state.');
    }
    return PlanState.fromJson(value);
  }

  AccountPlans withoutCoach() => AccountPlans(lifter: lifter);
}

/// Current account identity, capabilities, independent plan states, the
/// coach-AI feature state, and the sign-in methods from `GET /auth/me` (#116).
class Account {
  const Account({
    required this.accountId,
    required this.traineeId,
    required this.capabilities,
    this.plans = const AccountPlans(),
    this.coachAiEnabled = false,
    this.hasPassword = false,
    this.linkedSignIns = const <String>[],
  });

  factory Account.fromJson(Map<String, dynamic> json) {
    final Capabilities capabilities = Capabilities.fromJson(
      json['capabilities'] as Map<String, dynamic>,
    );
    final dynamic rawPlans = json['plans'];
    if (rawPlans is! Map<String, dynamic>) {
      throw const FormatException('Missing account plan states.');
    }
    final dynamic rawLinked = json['linked_sign_ins'];
    return Account(
      accountId: json['account_id'] as String,
      traineeId: json['trainee_id'] as String,
      capabilities: capabilities,
      plans: AccountPlans.fromJson(rawPlans),
      coachAiEnabled: json['coach_ai_enabled'] as bool? ?? false,
      hasPassword: json['has_password'] as bool? ?? false,
      linkedSignIns: rawLinked is List<dynamic>
          ? rawLinked.whereType<String>().toList(growable: false)
          : const <String>[],
    );
  }

  final String accountId;

  /// The legacy wire field for the reusable username.
  final String traineeId;
  final Capabilities capabilities;
  final AccountPlans plans;

  /// The service's effective coach-assistant feature state (ADR 049). When
  /// false the coach assistant entry point is hidden; the assistant endpoint
  /// itself answers 404 so a stale entry fails closed.
  final bool coachAiEnabled;

  /// Whether the account can sign in with a password (`/auth/me`, #114).
  final bool hasPassword;

  /// The connected providers by name — never a subject (`/auth/me`, #114).
  final List<String> linkedSignIns;

  bool get isCoach => capabilities.coach;

  bool get hasGoogleLink => linkedSignIns.contains('google');
}

/// `GET`/`PUT /coach/profile`: coach-authored fields keyed by immutable account id.
class CoachProfile {
  const CoachProfile({
    required this.accountId,
    required this.displayName,
    required this.bio,
    required this.specialization,
    required this.capacity,
  });

  factory CoachProfile.fromJson(Map<String, dynamic> json) => CoachProfile(
        accountId: json['account_id'] as String,
        displayName: json['display_name'] as String? ?? '',
        bio: json['bio'] as String? ?? '',
        specialization: json['specialization'] as String? ?? '',
        capacity: (json['capacity'] as num?)?.toInt() ?? 1,
      );

  final String accountId;
  final String displayName;
  final String bio;
  final String specialization;
  final int capacity;
}

/// The coach's current, product-facing identity shown before consent.
class CoachIdentity {
  const CoachIdentity({
    required this.displayName,
    required this.bio,
    required this.specialization,
  });

  factory CoachIdentity.fromJson(Map<String, dynamic> json) => CoachIdentity(
        displayName: json['display_name'] as String? ?? '',
        bio: json['bio'] as String? ?? '',
        specialization: json['specialization'] as String? ?? '',
      );

  final String displayName;
  final String bio;
  final String specialization;
}

/// The exact training-data access an active assignment grants (ADR 014).
class AssignmentAccess {
  const AssignmentAccess({
    required this.scope,
    required this.includesCurrentHistory,
    required this.includesHistoricalHistory,
    required this.activeWhileAssigned,
    required this.description,
  });

  factory AssignmentAccess.fromJson(Map<String, dynamic> json) =>
      AssignmentAccess(
        scope: json['scope'] as String? ?? '',
        includesCurrentHistory:
            json['includes_current_history'] as bool? ?? false,
        includesHistoricalHistory:
            json['includes_historical_history'] as bool? ?? false,
        activeWhileAssigned: json['active_while_assigned'] as bool? ?? false,
        description: json['description'] as String? ?? '',
      );

  final String scope;
  final bool includesCurrentHistory;
  final bool includesHistoricalHistory;
  final bool activeWhileAssigned;
  final String description;
}

/// `POST /assignments/invites/preview`: identity and access, code not consumed.
class AssignmentInvitePreview {
  const AssignmentInvitePreview({
    required this.coach,
    required this.access,
    required this.expiresAt,
  });

  factory AssignmentInvitePreview.fromJson(Map<String, dynamic> json) =>
      AssignmentInvitePreview(
        coach: CoachIdentity.fromJson(json['coach'] as Map<String, dynamic>),
        access:
            AssignmentAccess.fromJson(json['access'] as Map<String, dynamic>),
        expiresAt: json['expires_at'] as String? ?? '',
      );

  final CoachIdentity coach;
  final AssignmentAccess access;
  final String expiresAt;
}

/// `GET /assignments/me`: a mutually consented coaching assignment.
class Assignment {
  const Assignment({
    required this.assignmentId,
    required this.coach,
    required this.startedAt,
    required this.status,
  });

  factory Assignment.fromJson(Map<String, dynamic> json) => Assignment(
        assignmentId: json['assignment_id'] as String,
        coach: CoachIdentity.fromJson(json['coach'] as Map<String, dynamic>),
        startedAt: json['started_at'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
      );

  final String assignmentId;
  final CoachIdentity coach;
  final String startedAt;
  final String status;
}

/// `POST /coach/assignments/invites`: the one-time code and remaining capacity.
class AssignmentInvite {
  const AssignmentInvite({
    required this.token,
    required this.expiresAt,
    required this.activeAssignments,
    required this.capacity,
  });

  factory AssignmentInvite.fromJson(Map<String, dynamic> json) =>
      AssignmentInvite(
        token: json['token'] as String,
        expiresAt: json['expires_at'] as String? ?? '',
        activeAssignments: (json['active_assignments'] as num?)?.toInt() ?? 0,
        capacity: (json['capacity'] as num?)?.toInt() ?? 0,
      );

  final String token;
  final String expiresAt;
  final int activeAssignments;
  final int capacity;

  int get remaining => capacity - activeAssignments;
}

/// An in-app assignment notice for the coach.
class AssignmentNotice {
  const AssignmentNotice({
    required this.noticeId,
    required this.kind,
    required this.message,
    required this.createdAt,
    this.readAt,
  });

  factory AssignmentNotice.fromJson(Map<String, dynamic> json) =>
      AssignmentNotice(
        noticeId: json['notice_id'] as String,
        kind: json['kind'] as String? ?? '',
        message: json['message'] as String? ?? '',
        createdAt: json['created_at'] as String? ?? '',
        readAt: json['read_at'] as String?,
      );

  final String noticeId;
  final String kind;
  final String message;
  final String createdAt;
  final String? readAt;

  bool get isUnread => readAt == null || readAt!.isEmpty;
}

/// A player's request against a coach-controlled program and its resolution
/// state (ADR 027). It pins the exact program version, day, and slot it targets;
/// creating one never changes the program.
class ProgramRequest {
  const ProgramRequest({
    required this.requestId,
    required this.assignmentId,
    required this.kind,
    required this.programVersion,
    required this.reason,
    required this.status,
    required this.createdAt,
    this.dayName,
    this.exerciseId,
    this.replacementExerciseId,
    this.desiredWeeklyFrequency,
    this.desiredSplitPreference,
    this.response,
    this.resolvedAt,
    this.resolvedBy,
    this.playerUsername,
  });

  factory ProgramRequest.fromJson(Map<String, dynamic> json) => ProgramRequest(
        requestId: json['request_id'] as String,
        assignmentId: json['assignment_id'] as String,
        playerUsername: json['player_username'] as String?,
        kind: json['kind'] as String,
        programVersion: (json['program_version'] as num).toInt(),
        dayName: json['day_name'] as String?,
        exerciseId: json['exercise_id'] as String?,
        replacementExerciseId: json['replacement_exercise_id'] as String?,
        desiredWeeklyFrequency:
            (json['desired_weekly_frequency'] as num?)?.toInt(),
        desiredSplitPreference: json['desired_split_preference'] as String?,
        reason: json['reason'] as String,
        status: json['status'] as String,
        response: json['response'] as String?,
        createdAt: json['created_at'] as String,
        resolvedAt: json['resolved_at'] as String?,
        resolvedBy: json['resolved_by'] as String?,
      );

  final String requestId;
  final String assignmentId;
  final String kind;
  final int programVersion;
  final String? dayName;
  final String? exerciseId;
  final String? replacementExerciseId;
  final int? desiredWeeklyFrequency;
  final String? desiredSplitPreference;
  final String reason;
  final String status;
  final String? response;
  final String createdAt;
  final String? resolvedAt;
  final String? resolvedBy;

  /// The requesting player, carried only by the cross-roster list
  /// (`GET /coach/program-requests`, #118); the per-assignment payloads omit
  /// it, so callers that know the player pass it beside the request instead.
  final String? playerUsername;

  bool get isPending => status == 'pending';

  /// Once applied the request is answered: the program carries a new version
  /// and no further coaching action is possible (#121).
  bool get isApplied => status == 'applied';

  bool get isExerciseSubstitution => kind == 'exercise_substitution';

  bool get hasResponse => response != null && response!.isNotEmpty;

  String get description {
    if (isExerciseSubstitution) {
      return 'Substitute $exerciseId on $dayName with $replacementExerciseId';
    }
    final String preference =
        desiredSplitPreference == null || desiredSplitPreference!.isEmpty
            ? ''
            : ' ($desiredSplitPreference)';
    return 'Change to $desiredWeeklyFrequency days/week$preference';
  }

  String get statusLabel => switch (status) {
        'pending' => 'Pending',
        'applied' => 'Applied',
        'declined' => 'Declined',
        'cancelled' => 'Cancelled',
        _ => status,
      };
}

/// `GET /coach/assignments`: active assignment identity for the coach console.
class CoachRosterEntry {
  const CoachRosterEntry({
    required this.assignmentId,
    required this.playerUsername,
    required this.startedAt,
    required this.status,
    this.alertsNew = 0,
    this.alertsAcknowledged = 0,
    this.currentMissedStreak = 0,
    this.stallLength = 0,
    this.nextFollowUpOn,
    this.pendingRequests = 0,
    this.lastWorkoutOn,
    this.programName,
  });

  factory CoachRosterEntry.fromJson(Map<String, dynamic> json) =>
      CoachRosterEntry(
        assignmentId: json['assignment_id'] as String,
        playerUsername: json['player_username'] as String? ?? '',
        startedAt: json['started_at'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
        alertsNew: (json['alerts_new'] as num?)?.toInt() ?? 0,
        alertsAcknowledged: (json['alerts_acknowledged'] as num?)?.toInt() ?? 0,
        currentMissedStreak:
            (json['current_missed_streak'] as num?)?.toInt() ?? 0,
        stallLength: (json['stall_length'] as num?)?.toInt() ?? 0,
        nextFollowUpOn: json['next_follow_up_on'] as String?,
        pendingRequests: (json['pending_requests'] as num?)?.toInt() ?? 0,
        lastWorkoutOn: json['last_workout_on'] as String?,
        programName: json['program_name'] as String?,
      );

  final String assignmentId;
  final String playerUsername;
  final String startedAt;
  final String status;
  final int alertsNew;
  final int alertsAcknowledged;
  final int currentMissedStreak;

  /// Consecutive committing sessions without a personal record in the current
  /// program, cached on the catalog-side roster summary (#203).
  final int stallLength;

  /// The next weekly follow-up due date (`YYYY-MM-DD`), computed catalog-side.
  final String? nextFollowUpOn;

  /// The player's pending program requests on this assignment (#118).
  final int pendingRequests;

  /// The date of the player's latest committed workout (`YYYY-MM-DD`), or
  /// `null` while the player has never trained (#118).
  final String? lastWorkoutOn;

  /// The player's current program name, when the roster payload carries it.
  final String? programName;

  int get alertsOpen => alertsNew + alertsAcknowledged;

  /// The roster row's second line: the last workout with the program, or the
  /// never-trained wording when `lastWorkoutOn` is null (#120).
  String get rosterSubtitle {
    final String? lastWorkoutOn = this.lastWorkoutOn;
    if (lastWorkoutOn == null) {
      return 'No workouts yet';
    }
    final String? programName = this.programName;
    return programName == null || programName.isEmpty
        ? 'Last workout $lastWorkoutOn'
        : 'Last workout $lastWorkoutOn · $programName';
  }

  /// Whether the follow-up chip is due on [today] (`YYYY-MM-DD`): overdue
  /// before it, today on it, and no chip once the date is in the future.
  ///
  /// Returns `null` when no follow-up is scheduled.
  String? followUpChipLabel(String today) {
    final String? nextFollowUpOn = this.nextFollowUpOn;
    if (nextFollowUpOn == null) {
      return null;
    }
    if (nextFollowUpOn == today) {
      return 'Follow-up today';
    }
    if (nextFollowUpOn.compareTo(today) < 0) {
      return 'Follow-up overdue';
    }
    return null;
  }
}

/// One turn of the coach-assistant transcript sent with
/// `POST /coach/assignments/{assignment_id}/assistant` (issue #45).
///
/// The client holds the transcript in memory for one selected player and sends
/// the last turns with every call; neither the service nor this app persists it.
class CoachAssistantTurn {
  const CoachAssistantTurn({required this.role, required this.content});

  /// `coach` for the coach's question, `assistant` for the answer.
  final String role;
  final String content;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'role': role,
        'content': content,
      };

  @override
  String toString() => 'CoachAssistantTurn($role)';
}

/// `GET /coach/alerts`: one catalog-side alert (ADR 030/031/032).
///
/// `kind` is `missed_expected_days`, `follow_up_due`, `deload_recommended`,
/// `performance_regression`, `stall`, or `profile_change`; kind-specific fields are
/// flattened beside the common fields.
class CoachAlert {
  const CoachAlert({
    required this.alertId,
    required this.assignmentId,
    required this.playerUsername,
    required this.kind,
    required this.state,
    required this.createdAt,
    this.streakStartDate,
    this.lastMissedDate,
    this.missedCount = 0,
    this.stallLength = 0,
    this.windowStartDate,
    this.dueOn,
    this.lastCheckInOn,
    this.reason,
    this.severity,
    this.recentReadinessAvg,
    this.exerciseName,
    this.statusBadge,
    this.e1rmDelta,
    this.acknowledgedAt,
    this.resolvedAt,
    this.resolvedBy,
    this.playerDeloadChoice,
    this.profileChanges,
  });

  factory CoachAlert.fromJson(Map<String, dynamic> json) => CoachAlert(
        alertId: json['alert_id'] as String,
        assignmentId: json['assignment_id'] as String? ?? '',
        playerUsername: json['player_username'] as String? ?? '',
        kind: json['kind'] as String? ?? '',
        state: json['state'] as String? ?? 'new',
        createdAt: json['created_at'] as String? ?? '',
        streakStartDate: json['streak_start_date'] as String?,
        lastMissedDate: json['last_missed_date'] as String?,
        missedCount: (json['missed_count'] as num?)?.toInt() ?? 0,
        stallLength: (json['stall_length'] as num?)?.toInt() ?? 0,
        windowStartDate: json['window_start_date'] as String?,
        dueOn: json['due_on'] as String?,
        lastCheckInOn: json['last_check_in_on'] as String?,
        reason: json['reason'] as String?,
        severity: json['severity'] as String?,
        recentReadinessAvg: (json['recent_readiness_avg'] as num?)?.toDouble(),
        exerciseName: json['exercise_name'] as String?,
        statusBadge: json['status_badge'] as String?,
        e1rmDelta: (json['e1rm_delta'] as num?)?.toDouble(),
        acknowledgedAt: json['acknowledged_at'] as String?,
        resolvedAt: json['resolved_at'] as String?,
        resolvedBy: json['resolved_by'] as String?,
        playerDeloadChoice: json['player_deload_choice'] is Map<String, dynamic>
            ? Map<String, dynamic>.from(
                json['player_deload_choice'] as Map<String, dynamic>)
            : null,
        profileChanges: json['profile_changes'] is Map<String, dynamic>
            ? (json['profile_changes'] as Map<String, dynamic>).map(
                (String key, dynamic value) => MapEntry<String, Map<String, String>>(
                  key,
                    (value as Map<String, dynamic>).map(
                    (String part, dynamic text) => MapEntry<String, String>(
                      part,
                      text == null || '$text'.isEmpty ? 'Not set' : '$text',
                    ),
                  ),
                ),
              )
            : null,
      );

  final String alertId;
  final String assignmentId;
  final String playerUsername;
  final String kind;
  final String state;
  final String createdAt;
  final String? streakStartDate;
  final String? lastMissedDate;
  final int missedCount;
  final int stallLength;
  final String? windowStartDate;
  final String? dueOn;
  final String? lastCheckInOn;
  final String? reason;
  final String? severity;
  final double? recentReadinessAvg;
  final String? exerciseName;
  final String? statusBadge;
  final double? e1rmDelta;
  final String? acknowledgedAt;
  final String? resolvedAt;
  final String? resolvedBy;
  final Map<String, dynamic>? playerDeloadChoice;
  final Map<String, Map<String, String>>? profileChanges;

  static const String followUpDueKind = 'follow_up_due';
  static const String deloadRecommendedKind = 'deload_recommended';
  static const String performanceRegressionKind = 'performance_regression';
  static const String stallKind = 'stall';
  static const String profileChangeKind = 'profile_change';

  bool get isNew => state == 'new';
  bool get isAcknowledged => state == 'acknowledged';
  bool get isResolved => state == 'resolved';

  bool get isFollowUpDue => kind == followUpDueKind;
  bool get isDeloadRecommended => kind == deloadRecommendedKind;
  bool get isPerformanceRegression => kind == performanceRegressionKind;
  bool get isStall => kind == stallKind;
  bool get isProfileChange => kind == profileChangeKind;

  /// The alert-centre description, rendered per kind.
  String get description {
    if (isStall) {
      return 'Stalling — $stallLength sessions without a personal record '
          '(since ${windowStartDate ?? 'an earlier date'})';
    }
    if (isDeloadRecommended) {
      final String base = 'Deload recommended — ${reason ?? 'Systemic fatigue'}';
      final String? choice = playerDeloadChoice?['choice'] as String?;
      if (choice == deloadChoiceUndo || choice == deloadChoiceApply) {
        return '$base · Player chose to $choice it for the next workout only';
      }
      return base;
    }
    if (isPerformanceRegression) {
      final String badge = statusBadge ?? 'regression';
      return 'Performance regression — ${exerciseName ?? 'Exercise'}: '
          'e1RM ${_signedE1rm(e1rmDelta)} kg ($badge)';
    }
    if (isFollowUpDue) {
      return 'Follow-up due since ${dueOn ?? 'an earlier date'}';
    }
    if (isProfileChange) {
      const Map<String, String> labels = <String, String>{
        'injuries_or_limitations': 'Injuries or limitations',
        'equipment_access': 'Equipment access',
      };
      final Map<String, Map<String, String>> changes = profileChanges ?? const {};
      return changes.entries.map((MapEntry<String, Map<String, String>> entry) {
        final String label = labels[entry.key] ?? entry.key;
        return '$label: ${entry.value['before'] ?? ''} → ${entry.value['after'] ?? ''}';
      }).join('\n');
    }
    return 'Missed $missedCount expected training '
        '${missedCount == 1 ? 'day' : 'days'} '
        '(${streakStartDate ?? '?'} to ${lastMissedDate ?? '?'})';
  }

  String get stateLabel => switch (state) {
        'new' => 'New',
        'acknowledged' => 'Acknowledged',
        'resolved' => 'Resolved',
        _ => state,
      };
}

/// Formats an e1RM delta with a true minus sign, e.g. `−6.2` or `+1.0`.
String _signedE1rm(double? value) {
  if (value == null) {
    return '?';
  }
  final String sign = value < 0 ? '−' : '+';
  return '$sign${value.abs().toStringAsFixed(1)}';
}

/// One coach-recorded check-in fact (`GET /coach/assignments/{id}/check-ins`,
/// `GET /assignments/me/check-ins`). Immutable and visible to the player for
/// the life of the account, including after unassignment (ADR 031).
class CheckIn {
  const CheckIn({
    required this.checkInId,
    required this.assignmentId,
    required this.checkedInOn,
    required this.channel,
    required this.createdAt,
    this.note,
    this.coachUsername,
    this.assignmentStatus,
  });

  factory CheckIn.fromJson(Map<String, dynamic> json) => CheckIn(
        checkInId: json['check_in_id'] as String,
        assignmentId: json['assignment_id'] as String? ?? '',
        checkedInOn: json['checked_in_on'] as String? ?? '',
        channel: json['channel'] as String? ?? 'other',
        createdAt: json['created_at'] as String? ?? '',
        note: json['note'] as String?,
        coachUsername: json['coach_username'] as String?,
        assignmentStatus: json['assignment_status'] as String?,
      );

  final String checkInId;
  final String assignmentId;
  final String checkedInOn;
  final String channel;
  final String createdAt;
  final String? note;

  /// The coach's current username; present on the player's cross-assignment list.
  final String? coachUsername;

  /// `active` or `ended`; present on the player's cross-assignment list.
  final String? assignmentStatus;

  static const List<String> channels = <String>[
    'in_app',
    'in_person',
    'phone',
    'video',
    'message',
    'email',
    'other',
  ];

  /// The display label for one wire channel value (#120).
  static String labelFor(String channel) => switch (channel) {
        'in_app' => 'In app',
        'in_person' => 'In person',
        'phone' => 'Phone',
        'video' => 'Video',
        'message' => 'Message',
        'email' => 'Email',
        _ => 'Other',
      };

  String get channelLabel => labelFor(channel);
}

/// The check-ins ordered newest `checked_in_on` first (ties keep input order).
///
/// Shared so the coach drill-down stays sorted after appending a new check-in
/// rather than relying on server order or a bare prepend.
List<CheckIn> sortCheckInsNewestFirst(Iterable<CheckIn> checkIns) {
  final List<CheckIn> sorted = List<CheckIn>.of(checkIns);
  sorted.sort((CheckIn a, CheckIn b) => b.checkedInOn.compareTo(a.checkedInOn));
  return sorted;
}

/// `YYYY-MM-DD` for [date]: the wire date format check-ins send and the
/// format `YYYY-MM-DD` roster fields are compared against (#120).
String isoDateOf(DateTime date) => '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

/// `POST /coach/assignments/{id}/check-ins`: the recorded check-in and the
/// next follow-up date a full weekly cadence past it.
class CheckInCreation {
  const CheckInCreation({required this.checkIn, this.nextFollowUpOn});

  factory CheckInCreation.fromJson(Map<String, dynamic> json) =>
      CheckInCreation(
        checkIn: CheckIn.fromJson(json['check_in'] as Map<String, dynamic>),
        nextFollowUpOn: json['next_follow_up_on'] as String?,
      );

  final CheckIn checkIn;
  final String? nextFollowUpOn;
}

/// One exercise's working-set totals within an assigned player's session.
class CoachPlayerSessionExercise {
  const CoachPlayerSessionExercise({
    required this.name,
    required this.sets,
    required this.reps,
    required this.volumeKg,
  });

  factory CoachPlayerSessionExercise.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSessionExercise(
        name: json['name'] as String,
        sets: (json['sets'] as num).toInt(),
        reps: (json['reps'] as num).toInt(),
        volumeKg: (json['volume_kg'] as num).toDouble(),
      );

  final String name;
  final int sets;
  final int reps;
  final double volumeKg;
}

/// A factual skipped or unplanned exercise recorded in a player's session.
class CoachPlayerDivergence {
  const CoachPlayerDivergence({
    required this.kind,
    required this.exerciseId,
    required this.exerciseName,
  });

  factory CoachPlayerDivergence.fromJson(Map<String, dynamic> json) =>
      CoachPlayerDivergence(
        kind: json['kind'] as String,
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String,
      );

  final String kind;
  final String exerciseId;
  final String exerciseName;
}

/// The assigned player's current expected training weekdays and timezone.
class CoachPlayerSchedule {
  const CoachPlayerSchedule({required this.weekdays, required this.timezone});

  factory CoachPlayerSchedule.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSchedule(
        weekdays: _weekdays(json['weekdays']),
        timezone: json['timezone'] as String,
      );

  final List<int> weekdays;
  final String timezone;
}

/// An upcoming or active training pause the assigned player scheduled. No
/// reason is ever stored or returned.
class CoachPlayerPause {
  const CoachPlayerPause({required this.startsOn, required this.endsOn});

  factory CoachPlayerPause.fromJson(Map<String, dynamic> json) =>
      CoachPlayerPause(
        startsOn: json['starts_on'] as String,
        endsOn: json['ends_on'] as String,
      );

  final String startsOn;
  final String endsOn;
}

/// One immutable performed-date correction on a committed session (ADR 035).
class PerformedDateCorrection {
  const PerformedDateCorrection({
    required this.previousDate,
    required this.correctedDate,
    required this.correctedAt,
  });

  factory PerformedDateCorrection.fromJson(Map<String, dynamic> json) =>
      PerformedDateCorrection(
        previousDate: json['previous_date'] as String,
        correctedDate: json['corrected_date'] as String,
        correctedAt: json['corrected_at'] as String,
      );

  final String previousDate;
  final String correctedDate;
  final String correctedAt;

  /// The coach-facing note for one correction.
  String get label => 'Date corrected from $previousDate to $correctedDate';
}

List<PerformedDateCorrection> _correctionsFromJson(dynamic raw) =>
    (raw as List<dynamic>? ?? const <dynamic>[])
        .map((dynamic item) =>
            PerformedDateCorrection.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);

/// The assigned player's most recent committed session.
class CoachPlayerLatestSession {
  const CoachPlayerLatestSession({
    required this.sessionDate,
    required this.splitName,
    required this.setsCount,
    required this.totalVolumeKg,
    this.sessionId,
    this.readinessScore,
    this.programVersion,
    this.activeProgramVersionAtSync,
    this.isHistoricalProgram = false,
    this.uploadedAt,
    this.editedAt,
    this.corrections = const <PerformedDateCorrection>[],
    this.exercises = const <CoachPlayerSessionExercise>[],
    this.divergences = const <CoachPlayerDivergence>[],
    this.warmupMovements = const <WarmupMovementLog>[],
    this.cardio,
  });

  factory CoachPlayerLatestSession.fromJson(Map<String, dynamic> json) =>
      CoachPlayerLatestSession(
        sessionId: json['session_id'] as String?,
        sessionDate: json['session_date'] as String,
        splitName: json['split_name'] as String,
        readinessScore: (json['readiness_score'] as num?)?.toInt(),
        programVersion: (json['program_version'] as num?)?.toInt(),
        activeProgramVersionAtSync:
            (json['active_program_version_at_sync'] as num?)?.toInt(),
        isHistoricalProgram: json['is_historical_program'] == true,
        uploadedAt: json['uploaded_at'] as String?,
        editedAt: json['edited_at'] as String?,
        corrections: _correctionsFromJson(json['corrections']),
        setsCount: (json['sets_count'] as num).toInt(),
        totalVolumeKg: (json['total_volume_kg'] as num).toDouble(),
        exercises: (json['exercises'] as List<dynamic>? ?? const [])
            .map((dynamic e) =>
                CoachPlayerSessionExercise.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        divergences: (json['divergences'] as List<dynamic>? ?? const [])
            .map((dynamic d) =>
                CoachPlayerDivergence.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
        warmupMovements: (json['warmup_movements'] as List<dynamic>? ?? const [])
            .map((dynamic movement) => WarmupMovementLog.fromJson(
                movement as Map<String, dynamic>))
            .toList(growable: false),
        cardio: json['cardio'] is Map<String, dynamic>
            ? WorkoutCardio.fromJson(json['cardio'] as Map<String, dynamic>)
            : null,
      );

  final String? sessionId;
  final String sessionDate;
  final String splitName;
  final int? readinessScore;
  final int? programVersion;
  final int? activeProgramVersionAtSync;
  final bool isHistoricalProgram;
  final String? uploadedAt;
  final String? editedAt;
  final List<PerformedDateCorrection> corrections;
  final int setsCount;
  final double totalVolumeKg;
  final List<CoachPlayerSessionExercise> exercises;
  final List<CoachPlayerDivergence> divergences;
  final List<WarmupMovementLog> warmupMovements;
  final WorkoutCardio? cardio;
}

/// A compact entry in the assigned player's recent session history.
class CoachPlayerRecentSession {
  const CoachPlayerRecentSession({
    required this.sessionId,
    required this.sessionDate,
    required this.splitName,
    required this.setsCount,
    required this.totalVolumeKg,
    this.readinessScore,
    this.programVersion,
    this.activeProgramVersionAtSync,
    this.isHistoricalProgram = false,
    this.uploadedAt,
    this.editedAt,
    this.corrections = const <PerformedDateCorrection>[],
    this.divergences = const <CoachPlayerDivergence>[],
    this.warmupMovements = const <WarmupMovementLog>[],
    this.cardio,
  });

  factory CoachPlayerRecentSession.fromJson(Map<String, dynamic> json) =>
      CoachPlayerRecentSession(
        sessionId: json['session_id'] as String,
        sessionDate: json['session_date'] as String,
        splitName: json['split_name'] as String,
        readinessScore: (json['readiness_score'] as num?)?.toInt(),
        programVersion: (json['program_version'] as num?)?.toInt(),
        activeProgramVersionAtSync:
            (json['active_program_version_at_sync'] as num?)?.toInt(),
        isHistoricalProgram: json['is_historical_program'] == true,
        uploadedAt: json['uploaded_at'] as String?,
        editedAt: json['edited_at'] as String?,
        corrections: _correctionsFromJson(json['corrections']),
        setsCount: (json['sets_count'] as num).toInt(),
        totalVolumeKg: (json['total_volume_kg'] as num).toDouble(),
        divergences: (json['divergences'] as List<dynamic>? ?? const [])
            .map((dynamic d) =>
                CoachPlayerDivergence.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
        warmupMovements: (json['warmup_movements'] as List<dynamic>? ?? const [])
            .map((dynamic movement) => WarmupMovementLog.fromJson(
                movement as Map<String, dynamic>))
            .toList(growable: false),
        cardio: json['cardio'] is Map<String, dynamic>
            ? WorkoutCardio.fromJson(json['cardio'] as Map<String, dynamic>)
            : null,
      );

  final String sessionId;
  final String sessionDate;
  final String splitName;
  final int? readinessScore;
  final int? programVersion;
  final int? activeProgramVersionAtSync;
  final bool isHistoricalProgram;
  final String? uploadedAt;
  final String? editedAt;
  final List<PerformedDateCorrection> corrections;
  final int setsCount;
  final double totalVolumeKg;
  final List<CoachPlayerDivergence> divergences;
  final List<WarmupMovementLog> warmupMovements;
  final WorkoutCardio? cardio;
}

/// "Logged against program vN (current vM)" for a session captured against an
/// older program, or null when it was logged against the then-current program
/// (ADR 034).
String? historicalProgramLabel(
  int? programVersion,
  int? activeProgramVersionAtSync,
  bool isHistorical,
) {
  if (!isHistorical ||
      programVersion == null ||
      activeProgramVersionAtSync == null) {
    return null;
  }
  return 'Logged against program v$programVersion (current v$activeProgramVersionAtSync)';
}

/// `GET /coach/assignments/{id}/player/summary` for an actively assigned player.
class CoachPlayerSummary {
  const CoachPlayerSummary({
    required this.playerUsername,
    required this.startedAt,
    required this.status,
    required this.volume,
    this.latestSession,
    this.recentSessions = const <CoachPlayerRecentSession>[],
    this.schedule,
    this.pauses = const <CoachPlayerPause>[],
  });

  factory CoachPlayerSummary.fromJson(Map<String, dynamic> json) =>
      CoachPlayerSummary(
        playerUsername: json['player_username'] as String,
        startedAt: json['started_at'] as String,
        status: json['status'] as String,
        volume: (json['volume'] as Map<String, dynamic>? ?? const {}).map(
            (String key, dynamic value) =>
                MapEntry<String, double>(key, (value as num).toDouble())),
        latestSession: json['latest_session'] == null
            ? null
            : CoachPlayerLatestSession.fromJson(
                json['latest_session'] as Map<String, dynamic>),
        recentSessions: (json['recent_sessions'] as List<dynamic>? ?? const [])
            .map((dynamic s) =>
                CoachPlayerRecentSession.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
        schedule: json['schedule'] == null
            ? null
            : CoachPlayerSchedule.fromJson(
                json['schedule'] as Map<String, dynamic>),
        pauses: (json['pauses'] as List<dynamic>? ?? const [])
            .map((dynamic p) =>
                CoachPlayerPause.fromJson(p as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String playerUsername;
  final String startedAt;
  final String status;
  final Map<String, double> volume;
  final CoachPlayerLatestSession? latestSession;
  final List<CoachPlayerRecentSession> recentSessions;
  final CoachPlayerSchedule? schedule;
  final List<CoachPlayerPause> pauses;
}

/// One exercise the assigned player has logged.
class CoachPlayerExercise {
  const CoachPlayerExercise({required this.id, required this.name});

  factory CoachPlayerExercise.fromJson(Map<String, dynamic> json) =>
      CoachPlayerExercise(
        id: json['id'] as String,
        name: json['name'] as String,
      );

  final String id;
  final String name;
}

/// One progression point in an exercise's history.
class CoachExerciseHistoryPoint {
  const CoachExerciseHistoryPoint({
    required this.date,
    required this.weightKg,
    required this.reps,
    required this.e1rm,
    this.rpe,
  });

  factory CoachExerciseHistoryPoint.fromJson(Map<String, dynamic> json) =>
      CoachExerciseHistoryPoint(
        date: json['date'] as String,
        weightKg: (json['weight_kg'] as num).toDouble(),
        reps: (json['reps'] as num).toInt(),
        rpe: (json['rpe'] as num?)?.toDouble(),
        e1rm: (json['e1rm'] as num).toDouble(),
      );

  final String date;
  final double weightKg;
  final int reps;
  final double? rpe;
  final double e1rm;
}

/// One recorded personal record for a single exercise.
class CoachExerciseRecord {
  const CoachExerciseRecord({
    required this.recordType,
    required this.reps,
    required this.value,
    required this.achievedAt,
    this.prevValue,
  });

  factory CoachExerciseRecord.fromJson(Map<String, dynamic> json) =>
      CoachExerciseRecord(
        recordType: json['record_type'] as String,
        reps: (json['reps'] as num).toInt(),
        value: (json['value'] as num).toDouble(),
        prevValue: (json['prev_value'] as num?)?.toDouble(),
        achievedAt: json['achieved_at'] as String,
      );

  final String recordType;
  final int reps;
  final double value;
  final double? prevValue;
  final String achievedAt;
}

/// `GET /coach/assignments/{id}/player/exercises/{exercise_id}/history`.
class CoachExerciseHistory {
  const CoachExerciseHistory({
    required this.history,
    required this.records,
    this.caption,
  });

  factory CoachExerciseHistory.fromJson(Map<String, dynamic> json) =>
      CoachExerciseHistory(
        history: (json['history'] as List<dynamic>? ?? const [])
            .map((dynamic point) => CoachExerciseHistoryPoint.fromJson(
                point as Map<String, dynamic>))
            .toList(growable: false),
        caption: json['caption'] as String?,
        records: (json['records'] as List<dynamic>? ?? const [])
            .map((dynamic record) =>
                CoachExerciseRecord.fromJson(record as Map<String, dynamic>))
            .toList(growable: false),
      );

  final List<CoachExerciseHistoryPoint> history;
  final String? caption;
  final List<CoachExerciseRecord> records;
}

/// An authenticated account plus onboarding and recovery-email state.
class AccountSession {
  const AccountSession({
    required this.account,
    required this.onboarded,
    required this.hasRecoveryEmail,
  });

  final Account account;
  final bool onboarded;

  /// ADR 007: a recovery email is mandatory before dashboard or onboarding.
  final bool hasRecoveryEmail;
}

/// `POST /auth/register` and `POST /auth/login` response body.
class AuthTokens {
  const AuthTokens({required this.accessToken, required this.traineeId});

  factory AuthTokens.fromJson(Map<String, dynamic> json) => AuthTokens(
        accessToken: json['access_token'] as String,
        traineeId: json['trainee_id'] as String,
      );

  final String accessToken;
  final String traineeId;
}

/// `POST /onboarding/start` and `POST /onboarding/step` response body.
class OnboardingState {
  const OnboardingState({
    required this.intakeStep,
    required this.isComplete,
    required this.messages,
  });

  factory OnboardingState.fromJson(Map<String, dynamic> json) =>
      OnboardingState(
        intakeStep: (json['intake_step'] as num?)?.toInt() ?? 1,
        isComplete: json['is_complete'] as bool? ?? false,
        messages: (json['messages'] as List<dynamic>? ?? const [])
            .map((dynamic m) => m.toString())
            .toList(growable: false),
      );

  final int intakeStep;
  final bool isComplete;
  final List<String> messages;
}

/// `POST /onboarding/complete` response body.
///
/// Both program fields are null when no program could be produced (a
/// coach-controlled completion with nothing saved), and [programMessage] carries
/// the service's explanation so the client must not announce a routine.
class OnboardingCompletion {
  const OnboardingCompletion({
    required this.programName,
    required this.weeklyFrequency,
    this.programMessage,
  });

  factory OnboardingCompletion.fromJson(Map<String, dynamic> json) =>
      OnboardingCompletion(
        programName: json['program_name'] as String?,
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt(),
        programMessage: json['program_message'] as String?,
      );

  final String? programName;
  final int? weeklyFrequency;
  final String? programMessage;

  bool get hasProgram => programName != null && weeklyFrequency != null;
}

/// One named decision in the structured onboarding intake (`GET /onboarding/intake`).
///
/// [type] is the domain kind (`enum`/`int`/`float`/`text`); [allowedValues],
/// [minimum], and [maximum] describe the same validation the server enforces.
/// [prefilled] marks a value mapped from an incomplete legacy three-step intake.
class IntakeField {
  const IntakeField({
    required this.name,
    required this.type,
    required this.isRequired,
    required this.profileField,
    this.allowedValues = const <String>[],
    this.minimum,
    this.maximum,
    this.minimumLength,
    this.maximumLength,
    this.explanation,
    this.hint,
    this.examples = const <String>[],
    this.optionDescriptions = const <String, String>{},
    this.answer,
    this.prefilled = false,
    this.answered = false,
    this.updatedAt,
  });

  factory IntakeField.fromJson(Map<String, dynamic> json) {
    final Object? name = json['name'];
    if (name is! String || name.isEmpty) {
      throw const FormatException(
          'Onboarding intake field is missing its name.');
    }
    final Object? allowedValues = json['allowed_values'] ?? const <String>[];
    if (allowedValues is! List ||
        allowedValues.any((dynamic value) => value is! String)) {
      throw const FormatException('Onboarding intake choices must be strings.');
    }
    return IntakeField(
      name: name,
      type: json['type'] as String? ?? 'text',
      isRequired: json['required'] as bool? ?? false,
      profileField: json['profile_field'] as String? ?? '',
      allowedValues: List<String>.from(allowedValues),
      minimum: (json['minimum'] as num?)?.toDouble(),
      maximum: (json['maximum'] as num?)?.toDouble(),
      minimumLength: (json['minimum_length'] as num?)?.toInt(),
      maximumLength: (json['maximum_length'] as num?)?.toInt(),
      explanation: json['explanation'] as String?,
      hint: json['hint'] as String?,
      examples: (json['examples'] as List<dynamic>? ?? const [])
          .map((dynamic v) => v.toString())
          .toList(growable: false),
      optionDescriptions:
          (json['option_descriptions'] as Map<String, dynamic>? ??
                  const <String, dynamic>{})
              .map((String key, dynamic v) =>
                  MapEntry<String, String>(key, v.toString())),
      answer: json['answer'],
      prefilled: json['prefilled'] as bool? ?? false,
      answered: json['answered'] as bool? ?? false,
      updatedAt: json['updated_at'] as String?,
    );
  }

  final String name;
  final String type;
  final bool isRequired;
  final String profileField;
  final List<String> allowedValues;
  final double? minimum;
  final double? maximum;
  final int? minimumLength;
  final int? maximumLength;
  final String? explanation;
  final String? hint;
  final List<String> examples;

  /// Player-facing description per allowed value, written from the generation
  /// rule for that value. Empty for fields without enum values.
  final Map<String, String> optionDescriptions;
  final Object? answer;
  final bool prefilled;
  final bool answered;
  final String? updatedAt;
}

/// Resume progress over the named intake decisions.
class IntakeProgress {
  const IntakeProgress({
    required this.answeredRequired,
    required this.requiredTotal,
    required this.answered,
    required this.totalFields,
    this.nextUnanswered,
  });

  factory IntakeProgress.fromJson(Map<String, dynamic> json) => IntakeProgress(
        answeredRequired: (json['answered_required'] as num?)?.toInt() ?? 0,
        requiredTotal: (json['required_total'] as num?)?.toInt() ?? 0,
        answered: (json['answered'] as num?)?.toInt() ?? 0,
        totalFields: (json['total_fields'] as num?)?.toInt() ?? 0,
        nextUnanswered: json['next_unanswered'] as String?,
      );

  final int answeredRequired;
  final int requiredTotal;
  final int answered;
  final int totalFields;
  final String? nextUnanswered;

  bool get isComplete => answeredRequired >= requiredTotal;
}

/// The stored first-program result, present once the intake is confirmed.
class IntakeProgram {
  const IntakeProgram(
      {this.programName, this.weeklyFrequency, this.programMessage});

  factory IntakeProgram.fromJson(Map<String, dynamic> json) => IntakeProgram(
        programName: json['program_name'] as String?,
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt(),
        programMessage: json['program_message'] as String?,
      );

  final String? programName;
  final int? weeklyFrequency;
  final String? programMessage;

  bool get hasProgram => programName != null && weeklyFrequency != null;
}

/// `GET /onboarding/intake`: the contract, saved answers, progress, and status.
class OnboardingIntake {
  const OnboardingIntake({
    required this.status,
    required this.disclosureAcknowledged,
    required this.fields,
    required this.profileRebuildFields,
    required this.progress,
    this.program,
  });

  factory OnboardingIntake.fromJson(Map<String, dynamic> json) {
    final Object? status = json['status'];
    if (status is! String || status.isEmpty) {
      throw const FormatException('Onboarding intake is missing its status.');
    }
    final Object? rawFields = json['fields'];
    if (rawFields is! List) {
      throw const FormatException('Onboarding intake is missing its fields.');
    }
    return OnboardingIntake(
      status: status,
      disclosureAcknowledged: json['disclosure_acknowledged'] as bool? ?? false,
      fields: rawFields
          .map((dynamic f) => IntakeField.fromJson(f as Map<String, dynamic>))
          .toList(growable: false),
      profileRebuildFields:
          (json['profile_rebuild_fields'] as List<dynamic>? ?? const [])
              .map((dynamic field) => field.toString())
              .toList(growable: false),
      progress: IntakeProgress.fromJson(
          json['progress'] as Map<String, dynamic>? ?? const {}),
      program: json['program'] == null
          ? null
          : IntakeProgram.fromJson(json['program'] as Map<String, dynamic>),
    );
  }

  final String status;
  final bool disclosureAcknowledged;
  final List<IntakeField> fields;
  final List<String> profileRebuildFields;
  final IntakeProgress progress;
  final IntakeProgram? program;

  bool get isConfirmed => status == 'confirmed';

  IntakeField? field(String name) {
    for (final IntakeField field in fields) {
      if (field.name == name) {
        return field;
      }
    }
    return null;
  }
}

/// `POST /onboarding/intake/confirm`: the confirmed first-program result.
class IntakeConfirmation {
  const IntakeConfirmation({
    required this.status,
    this.programName,
    this.weeklyFrequency,
    this.programMessage,
  });

  factory IntakeConfirmation.fromJson(Map<String, dynamic> json) =>
      IntakeConfirmation(
        status: json['status'] as String? ?? 'confirmed',
        programName: json['program_name'] as String?,
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt(),
        programMessage: json['program_message'] as String?,
      );

  final String status;
  final String? programName;
  final int? weeklyFrequency;
  final String? programMessage;

  bool get hasProgram => programName != null && weeklyFrequency != null;
}

/// `GET /profile`: the player's stored training profile. Only the fields the
/// profile editor writes are modeled; unknown keys are ignored.
class PlayerProfile {
  const PlayerProfile({
    this.repPreference = 'balanced',
    this.weeklyFrequency = 4,
    this.equipmentAccess = equipmentAccessCommercialGym,
    this.currentGoal = '',
    this.injuriesOrLimitations = 'None',
    this.weightKg = 75,
    this.assistantStyle = defaultAssistantStyle,
    this.assistantInstructions = '',
    this.playerControlsProgram = true,
  });

  factory PlayerProfile.fromJson(Map<String, dynamic> json) => PlayerProfile(
        repPreference: json['rep_preference'] as String? ?? 'balanced',
        weeklyFrequency: (json['weekly_frequency'] as num?)?.toInt() ?? 4,
        equipmentAccess:
            json['equipment_access'] as String? ?? equipmentAccessCommercialGym,
        currentGoal: json['current_goal'] as String? ?? '',
        injuriesOrLimitations:
            json['injuries_or_limitations'] as String? ?? 'None',
        weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 75,
        assistantStyle:
            json['coach_tone'] as String? ?? defaultAssistantStyle,
        assistantInstructions: json['custom_instructions'] as String? ?? '',
        playerControlsProgram: json['player_controls_program'] as bool? ?? true,
      );

  final String repPreference;
  final int weeklyFrequency;
  final String equipmentAccess;
  final String currentGoal;
  final String injuriesOrLimitations;
  final double weightKg;
  final String assistantStyle;
  final String assistantInstructions;
  final bool playerControlsProgram;
}

/// `PUT /profile` response body.
///
/// [programBlocked] is true when a rebuild was warranted but the assigned coach
/// owns the active program, so nothing was regenerated and [programMessage]
/// explains that a coach request is needed.
class ProfileUpdateResult {
  const ProfileUpdateResult({
    required this.programRebuilt,
    this.programBlocked = false,
    this.programMessage,
    this.profile,
  });

  factory ProfileUpdateResult.fromJson(Map<String, dynamic> json) =>
      ProfileUpdateResult(
        programRebuilt: json['program_rebuilt'] as bool? ?? false,
        programBlocked: json['program_blocked'] as bool? ?? false,
        programMessage: json['program_message'] as String?,
        profile: json['profile'] is Map<String, dynamic>
            ? PlayerProfile.fromJson(json['profile'] as Map<String, dynamic>)
            : null,
      );

  final bool programRebuilt;
  final bool programBlocked;
  final String? programMessage;
  final PlayerProfile? profile;
}

const List<String> weekdayLabels = <String>[
  'Mon',
  'Tue',
  'Wed',
  'Thu',
  'Fri',
  'Sat',
  'Sun',
];

List<int> _weekdays(dynamic raw) {
  if (raw is! List<dynamic>) {
    throw const FormatException('Invalid training weekdays.');
  }
  return raw.map((dynamic day) {
    if (day is! num) {
      throw const FormatException('Invalid training weekday.');
    }
    final int value = day.toInt();
    if (value < 1 || value > 7) {
      throw const FormatException('Invalid training weekday.');
    }
    return value;
  }).toList(growable: false);
}

/// One effective-dated version of the player's expected training weekdays
/// (`GET`/`PUT /profile/schedule`, ADR 029). Setting a schedule never touches
/// the program's weekly frequency or ordered training days.
class TrainingScheduleVersion {
  const TrainingScheduleVersion({
    required this.scheduleId,
    required this.weekdays,
    required this.timezone,
    required this.effectiveFrom,
    required this.createdAt,
  });

  factory TrainingScheduleVersion.fromJson(Map<String, dynamic> json) =>
      TrainingScheduleVersion(
        scheduleId: json['schedule_id'] as String,
        weekdays: _weekdays(json['weekdays']),
        timezone: json['timezone'] as String,
        effectiveFrom: json['effective_from'] as String,
        createdAt: json['created_at'] as String,
      );

  final String scheduleId;
  final List<int> weekdays;
  final String timezone;
  final String effectiveFrom;
  final String createdAt;
}

/// A prospective training pause; no reason is stored or returned.
class ScheduledPause {
  const ScheduledPause({
    required this.pauseId,
    required this.startsOn,
    required this.endsOn,
    required this.createdAt,
  });

  factory ScheduledPause.fromJson(Map<String, dynamic> json) => ScheduledPause(
        pauseId: json['pause_id'] as String,
        startsOn: json['starts_on'] as String,
        endsOn: json['ends_on'] as String,
        createdAt: json['created_at'] as String,
      );

  final String pauseId;
  final String startsOn;
  final String endsOn;
  final String createdAt;
}

/// `GET /profile/schedule`: the current version, every version, and active pauses.
class TrainingSchedule {
  const TrainingSchedule({
    this.current,
    this.versions = const <TrainingScheduleVersion>[],
    this.pauses = const <ScheduledPause>[],
  });

  factory TrainingSchedule.fromJson(Map<String, dynamic> json) =>
      TrainingSchedule(
        current: json['current'] == null
            ? null
            : TrainingScheduleVersion.fromJson(
                json['current'] as Map<String, dynamic>),
        versions: (json['versions'] as List<dynamic>? ?? const [])
            .map((dynamic v) =>
                TrainingScheduleVersion.fromJson(v as Map<String, dynamic>))
            .toList(growable: false),
        pauses: (json['pauses'] as List<dynamic>? ?? const [])
            .map((dynamic p) =>
                ScheduledPause.fromJson(p as Map<String, dynamic>))
            .toList(growable: false),
      );

  final TrainingScheduleVersion? current;
  final List<TrainingScheduleVersion> versions;
  final List<ScheduledPause> pauses;
}

/// `GET /dashboard/training-status` and the status carried by a workout commit.
class TrainingStatus {
  const TrainingStatus({
    required this.weeklyStreak,
    required this.weekStart,
    required this.weekDone,
    required this.weekTarget,
    required this.mayosWorkouts,
    required this.nextCheckpoint,
    required this.workoutsToNext,
  });

  factory TrainingStatus.fromJson(Map<String, dynamic> json) {
    final dynamic weekStart = json['week_start'];
    if (weekStart is! String || DateTime.tryParse(weekStart) == null) {
      throw const FormatException('Invalid training status week start.');
    }
    return TrainingStatus(
      weeklyStreak: _requiredInt(json, 'weekly_streak'),
      weekStart: weekStart,
      weekDone: _requiredInt(json, 'week_done'),
      weekTarget: _requiredInt(json, 'week_target'),
      mayosWorkouts: _requiredInt(json, 'mayos_workouts'),
      nextCheckpoint: _requiredInt(json, 'next_checkpoint'),
      workoutsToNext: _requiredInt(json, 'workouts_to_next'),
    );
  }

  final int weeklyStreak;
  final String weekStart;
  final int weekDone;
  final int weekTarget;
  final int mayosWorkouts;
  final int nextCheckpoint;
  final int workoutsToNext;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weekly_streak': weeklyStreak,
        'week_start': weekStart,
        'week_done': weekDone,
        'week_target': weekTarget,
        'mayos_workouts': mayosWorkouts,
        'next_checkpoint': nextCheckpoint,
        'workouts_to_next': workoutsToNext,
      };

  static int _requiredInt(Map<String, dynamic> json, String key) {
    final dynamic value = json[key];
    if (value is! num) {
      throw FormatException('Invalid training status field: $key.');
    }
    return value.toInt();
  }
}

class CheckpointRatingPart {
  const CheckpointRatingPart({required this.part, required this.label});

  factory CheckpointRatingPart.fromJson(Map<String, dynamic> json) {
    final dynamic part = json['part'];
    final dynamic label = json['label'];
    if (part is! String || label is! String) {
      throw const FormatException('Invalid checkpoint rating part.');
    }
    return CheckpointRatingPart(part: part, label: label);
  }

  final String part;
  final String label;
}

/// One row from the player's or assigned coach's Checkpoints list.
class CheckpointReviewListItem {
  const CheckpointReviewListItem({
    required this.checkpoint,
    required this.periodStart,
    required this.periodEnd,
    required this.rating,
    required this.opened,
  });

  factory CheckpointReviewListItem.fromJson(Map<String, dynamic> json) {
    final dynamic rawRating = json['rating'];
    if (rawRating is! List<dynamic>) {
      throw const FormatException('Invalid checkpoint rating.');
    }
    return CheckpointReviewListItem(
      checkpoint: (json['checkpoint'] as num).toInt(),
      periodStart: json['period_start'] as String,
      periodEnd: json['period_end'] as String,
      rating: rawRating
          .map((dynamic part) => CheckpointRatingPart.fromJson(
              part as Map<String, dynamic>))
          .toList(growable: false),
      opened: json['opened'] as bool? ?? false,
    );
  }

  final int checkpoint;
  final String periodStart;
  final String periodEnd;
  final List<CheckpointRatingPart> rating;
  final bool opened;
}

/// Full Checkpoint review returned by the player and active-assignment APIs.
class CheckpointReview {
  const CheckpointReview({
    required this.checkpoint,
    required this.periodStart,
    required this.periodEnd,
    required this.facts,
    required this.rating,
    required this.text,
    required this.textIsTemplate,
  });

  factory CheckpointReview.fromJson(Map<String, dynamic> json) {
    final dynamic facts = json['facts'];
    final dynamic rawRating = json['rating'];
    if (facts is! Map<String, dynamic> || rawRating is! List<dynamic>) {
      throw const FormatException('Invalid checkpoint review.');
    }
    return CheckpointReview(
      checkpoint: (json['checkpoint'] as num).toInt(),
      periodStart: json['period_start'] as String,
      periodEnd: json['period_end'] as String,
      facts: Map<String, dynamic>.unmodifiable(facts),
      rating: rawRating
          .map((dynamic part) => CheckpointRatingPart.fromJson(
              part as Map<String, dynamic>))
          .toList(growable: false),
      text: json['text'] as String,
      textIsTemplate: json['text_is_template'] as bool? ?? false,
    );
  }

  final int checkpoint;
  final String periodStart;
  final String periodEnd;
  final Map<String, dynamic> facts;
  final List<CheckpointRatingPart> rating;
  final String text;
  final bool textIsTemplate;
}

/// `PUT /profile/schedule` response: the appended version and the current schedule.
class TrainingScheduleSetResult {
  const TrainingScheduleSetResult({required this.version, this.current});

  factory TrainingScheduleSetResult.fromJson(Map<String, dynamic> json) =>
      TrainingScheduleSetResult(
        version: TrainingScheduleVersion.fromJson(
            json['version'] as Map<String, dynamic>),
        current: json['current'] == null
            ? null
            : TrainingScheduleVersion.fromJson(
                json['current'] as Map<String, dynamic>),
      );

  final TrainingScheduleVersion version;
  final TrainingScheduleVersion? current;
}

/// `POST /profile/schedule/pauses` response: the stored pause and whether the
/// assigned coach was notified.
class TrainingPauseCreateResult {
  const TrainingPauseCreateResult({
    required this.pause,
    required this.noticeSent,
  });

  factory TrainingPauseCreateResult.fromJson(Map<String, dynamic> json) =>
      TrainingPauseCreateResult(
        pause: ScheduledPause.fromJson(json['pause'] as Map<String, dynamic>),
        noticeSent: json['notice_sent'] as bool? ?? false,
      );

  final ScheduledPause pause;
  final bool noticeSent;
}

class ProgramExercise {
  const ProgramExercise({
    required this.exerciseId,
    required this.exerciseName,
    required this.targetSets,
    required this.targetRepsMin,
    required this.targetRepsMax,
    required this.targetRpe,
    this.warmupSets = 0,
    this.restSeconds,
    this.notes,
    this.suggestedSubstitutes = const <SuggestedSubstitute>[],
    this.imagePath,
  });

  factory ProgramExercise.fromJson(Map<String, dynamic> json) =>
      ProgramExercise(
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String,
        targetSets: (json['target_sets'] as num?)?.toInt() ?? 2,
        targetRepsMin: (json['target_reps_min'] as num?)?.toInt() ?? 0,
        targetRepsMax: (json['target_reps_max'] as num?)?.toInt() ?? 0,
        targetRpe: (json['target_rpe'] as num?)?.toDouble() ?? 8.5,
        warmupSets: (json['warmup_sets'] as num?)?.toInt() ?? 0,
        // A missing `rest_seconds` is *unset*, not 180: the rest timer then
        // resolves it to the flat 2:00 instead of a phantom 3:00 (#125).
        restSeconds: (json['rest_seconds'] as num?)?.toInt(),
        notes: json['notes'] as String?,
        suggestedSubstitutes:
            (json['suggested_substitutes'] as List<dynamic>? ??
                    const <dynamic>[])
                .whereType<Map<String, dynamic>>()
                .map(SuggestedSubstitute.fromJson)
                .toList(growable: false),
        // The catalog's ExerciseDB path (`images/…`), already on the program
        // payload (`ProgramExerciseSchema.image_path`), kept so the logger can
        // build its public `/media` URL (#161). Null when the program carried
        // none, which is what an older stored program looks like.
        imagePath: json['image_path'] as String?,
      );

  final String exerciseId;
  final String exerciseName;
  final int targetSets;
  final int targetRepsMin;
  final int targetRepsMax;
  final double targetRpe;

  /// Ramped warm-up sets prescribed before the working sets (0 when none).
  final int warmupSets;

  /// The program's rest, or null when the program carried none (#125): unset
  /// is distinguishable from a value, and resolves to [kDefaultRestSeconds]
  /// wherever a length is needed. Display falls back to the same default, so
  /// a program that omits the field still reads "rest 120s".
  final int? restSeconds;
  final String? notes;

  /// Equipment access-compatible Staple exercises listed after the prescribed one.
  final List<SuggestedSubstitute> suggestedSubstitutes;

  /// The catalog picture path the program payload carried (#161), relative
  /// (`images/0001-2gPfomN.jpg`), never a served URL: the logger builds the
  /// public `/media` address from the API base.
  final String? imagePath;

  int get restSecondsOrDefault => restSeconds ?? kDefaultRestSeconds;

  bool get hasNotes => notes != null && notes!.isNotEmpty;

  bool get hasWarmupSets => warmupSets > 0;

  String get prescription =>
      '$targetSets × $targetRepsMin–$targetRepsMax @ RIR ${minRirLabel(targetRpe)}';

  String get restLabel => 'rest ${restSecondsOrDefault}s';

  Map<String, dynamic> toJson() {
    final Map<String, dynamic> json = <String, dynamic>{
      'exercise_id': exerciseId,
      'exercise_name': exerciseName,
      'target_sets': targetSets,
      'target_reps_min': targetRepsMin,
      'target_reps_max': targetRepsMax,
      'target_rpe': targetRpe,
      'warmup_sets': warmupSets,
    };
    // The key is omitted when unset, so the Active workout (and the draft
    // built from it) keeps "no rest_seconds" as-is and the timer resolves it
    // to 2:00 rather than writing a phantom 180 back (#125). Its position in
    // the map is kept, so the draft's encoded shape is unchanged when the
    // program did carry a value.
    if (restSeconds != null) {
      json['rest_seconds'] = restSeconds;
    }
    json['notes'] = notes;
    if (suggestedSubstitutes.isNotEmpty) {
      json['suggested_substitutes'] = suggestedSubstitutes
          .map((SuggestedSubstitute item) => item.toJson())
          .toList(growable: false);
    }
    // Omitted when the program carried none (#161), so a payload without a
    // picture still encodes exactly as it did before this field existed.
    if (imagePath != null) {
      json['image_path'] = imagePath;
    }
    return json;
  }
}

class SuggestedSubstitute {
  const SuggestedSubstitute({
    required this.exerciseId,
    required this.exerciseName,
  });

  factory SuggestedSubstitute.fromJson(Map<String, dynamic> json) =>
      SuggestedSubstitute(
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String,
      );

  final String exerciseId;
  final String exerciseName;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
      };
}

/// `WarmupExerciseSchema`: a general preparation movement for a training day.
class WarmupExercise {
  const WarmupExercise({
    required this.exerciseName,
    this.exerciseId,
    this.sets = 2,
    this.reps = 10,
    this.restSeconds = 45,
    this.notes,
  });

  factory WarmupExercise.fromJson(Map<String, dynamic> json) => WarmupExercise(
        exerciseName: json['exercise_name'] as String,
        exerciseId: json['exercise_id'] as String?,
        sets: (json['sets'] as num?)?.toInt() ?? 2,
        reps: (json['reps'] as num?)?.toInt() ?? 10,
        restSeconds: (json['rest_seconds'] as num?)?.toInt() ?? 45,
        notes: json['notes'] as String?,
      );

  final String? exerciseId;
  final String exerciseName;
  final int sets;
  final int reps;
  final int restSeconds;
  final String? notes;

  bool get hasNotes => notes != null && notes!.isNotEmpty;

  String get prescription => '$sets × $reps · rest ${restSeconds}s';

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'sets': sets,
        'reps': reps,
        'rest_seconds': restSeconds,
        'notes': notes,
      };
}

class ProgramDay {
  const ProgramDay({
    required this.dayName,
    required this.dayOrder,
    this.warmupExercises = const <WarmupExercise>[],
    required this.exercises,
    this.cardio,
  });

  factory ProgramDay.fromJson(Map<String, dynamic> json) => ProgramDay(
        dayName: json['day_name'] as String,
        dayOrder: (json['day_order'] as num).toInt(),
        warmupExercises:
            (json['warmup_exercises'] as List<dynamic>? ?? const [])
                .map((dynamic e) =>
                    WarmupExercise.fromJson(e as Map<String, dynamic>))
                .toList(growable: false),
        exercises: (json['exercises'] as List<dynamic>? ?? const [])
            .map((dynamic e) =>
                ProgramExercise.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        cardio: json['cardio'] as String?,
      );

  final String dayName;
  final int dayOrder;
  final List<WarmupExercise> warmupExercises;
  final List<ProgramExercise> exercises;
  final String? cardio;

  bool get hasWarmup => warmupExercises.isNotEmpty;

  bool get hasCardio => cardio != null && cardio!.isNotEmpty;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'day_name': dayName,
        'day_order': dayOrder,
        'warmup_exercises': <Map<String, dynamic>>[
          for (final WarmupExercise warmup in warmupExercises) warmup.toJson(),
        ],
        'exercises': <Map<String, dynamic>>[
          for (final ProgramExercise exercise in exercises) exercise.toJson(),
        ],
        'cardio': cardio,
      };
}

/// Cardio captured alongside a workout, outside its exercise set rows.
class WorkoutCardio {
  const WorkoutCardio({
    required this.prescription,
    this.minutes,
    this.ticked = false,
  });

  factory WorkoutCardio.fromJson(Map<String, dynamic> json) => WorkoutCardio(
        prescription: json['prescription'] as String,
        minutes: (json['minutes'] as num?)?.toInt(),
        ticked: json['ticked'] as bool? ?? false,
      );

  final String prescription;
  final int? minutes;
  final bool ticked;

  bool get hasValidMinutes {
    final int? loggedMinutes = minutes;
    return loggedMinutes != null && loggedMinutes >= 1 && loggedMinutes <= 600;
  }

  bool get isCommitted => ticked && hasValidMinutes;

  WorkoutCardio copyWith({bool? ticked}) => WorkoutCardio(
        prescription: prescription,
        minutes: minutes,
        ticked: ticked ?? this.ticked,
      );

  WorkoutCardio withMinutes(int? minutes, {bool? ticked}) => WorkoutCardio(
        prescription: prescription,
        minutes: minutes,
        ticked: ticked ?? this.ticked,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'prescription': prescription,
        'minutes': minutes,
        'ticked': ticked,
      };

  Map<String, dynamic> toCommitJson() => <String, dynamic>{
        'prescription': prescription,
        'minutes': minutes,
      };
}

/// `GeneratedProgramSchema` from `GET /programs/active`.
class TrainingProgram {
  const TrainingProgram({
    required this.programName,
    required this.splitType,
    required this.weeklyFrequency,
    required this.days,
    this.version,
    this.publishedByCoachAccountId,
    this.playerControlsProgram = false,
  });

  factory TrainingProgram.fromJson(Map<String, dynamic> json) =>
      TrainingProgram(
        programName: json['program_name'] as String,
        splitType: json['split_type'] as String? ?? 'custom',
        weeklyFrequency: (json['weekly_frequency'] as num).toInt(),
        days: (json['days'] as List<dynamic>? ?? const [])
            .map((dynamic d) => ProgramDay.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
        version: (json['version'] as num?)?.toInt(),
        publishedByCoachAccountId:
            json['published_by_coach_account_id'] as String?,
        playerControlsProgram:
            json['player_controls_program'] as bool? ?? false,
      );

  final String programName;
  final String splitType;
  final int weeklyFrequency;
  final List<ProgramDay> days;

  /// Stable ledger version recorded at publication; null for legacy payloads.
  final int? version;

  /// Publishing coach's account id, or null for player self-service.
  final String? publishedByCoachAccountId;

  /// Server-computed Program-authority decision for the active program.
  final bool playerControlsProgram;

  bool get isCoachPublished => publishedByCoachAccountId != null;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'program_name': programName,
        'split_type': splitType,
        'weekly_frequency': weeklyFrequency,
        'days': <Map<String, dynamic>>[
          for (final ProgramDay day in days) day.toJson(),
        ],
        'version': version,
        'published_by_coach_account_id': publishedByCoachAccountId,
        'player_controls_program': playerControlsProgram,
      };
}

/// Program payload plus the ledger versions needed for exact substitution undo.
class ProgramSubstitutionResult {
  const ProgramSubstitutionResult({
    required this.program,
    required this.previousVersion,
    required this.version,
  });

  factory ProgramSubstitutionResult.fromJson(Map<String, dynamic> json) =>
      ProgramSubstitutionResult(
        program: TrainingProgram.fromJson(json),
        previousVersion: (json['previous_version'] as num).toInt(),
        version: (json['version'] as num).toInt(),
      );

  final TrainingProgram program;
  final int previousVersion;
  final int version;
}

/// `GET /dashboard/personal-records` entry.
class PersonalRecord {
  const PersonalRecord({
    required this.exerciseId,
    required this.name,
    required this.recordType,
    required this.reps,
    required this.value,
    required this.achievedAt,
  });

  factory PersonalRecord.fromJson(Map<String, dynamic> json) => PersonalRecord(
        exerciseId: json['exercise_id'] as String,
        name: json['name'] as String? ?? json['exercise_id'] as String,
        recordType: json['record_type'] as String? ?? '',
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        value: (json['value'] as num?)?.toDouble() ?? 0,
        achievedAt: json['achieved_at'] as String? ?? '',
      );

  final String exerciseId;
  final String name;
  final String recordType;
  final int reps;
  final double value;
  final String achievedAt;
}

/// One entered set in the offline workout logger (ADR 020/033).
class WorkoutSetLog {
  const WorkoutSetLog({
    required this.weightKg,
    required this.reps,
    this.rpe,
    this.isWarmup = false,
  });

  factory WorkoutSetLog.fromJson(Map<String, dynamic> json) => WorkoutSetLog(
        weightKg: (json['weight_kg'] as num?)?.toDouble() ?? 0,
        reps: (json['reps'] as num?)?.toInt() ?? 0,
        rpe: (json['rpe'] as num?)?.toDouble(),
        isWarmup: json['is_warmup'] as bool? ?? false,
      );

  final double weightKg;
  final int reps;

  /// The stored effort, kept as RPE on the wire; null when the set is unrated
  /// (#111) — the service accepts an absent effort, so no default is filled in.
  final double? rpe;
  final bool isWarmup;

  WorkoutSetLog copyWith({
    double? weightKg,
    int? reps,
    double? rpe,
    bool? isWarmup,
    bool clearRpe = false,
  }) =>
      WorkoutSetLog(
        weightKg: weightKg ?? this.weightKg,
        reps: reps ?? this.reps,
        rpe: clearRpe ? null : (rpe ?? this.rpe),
        isWarmup: isWarmup ?? this.isWarmup,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
        'rpe': rpe,
        'is_warmup': isWarmup,
      };
}

/// One exercise (prescribed or unplanned) captured in a workout draft.
///
/// [exercise] is the exact `ProgramExerciseSchema` payload the service expects,
/// so an offline draft can be replayed later without the program being present.
class DraftExercise {
  const DraftExercise({
    required this.exercise,
    required this.sets,
    this.skipped = false,
  });

  factory DraftExercise.fromJson(Map<String, dynamic> json) => DraftExercise(
        exercise:
            Map<String, dynamic>.from(json['exercise'] as Map<String, dynamic>),
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) =>
                WorkoutSetLog.fromJson(s as Map<String, dynamic>))
            .toList(growable: false),
        skipped: json['skipped'] as bool? ?? false,
      );

  final Map<String, dynamic> exercise;
  final List<WorkoutSetLog> sets;
  final bool skipped;

  String get exerciseId => exercise['exercise_id'] as String;
  String get exerciseName => exercise['exercise_name'] as String;
  bool get hasWorkingSets =>
      !skipped && sets.any((WorkoutSetLog s) => !s.isWarmup);

  DraftExercise copyWith({
    List<WorkoutSetLog>? sets,
    bool? skipped,
  }) =>
      DraftExercise(
        exercise: exercise,
        sets: sets ?? this.sets,
        skipped: skipped ?? this.skipped,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise': exercise,
        'sets': <Map<String, dynamic>>[
          for (final WorkoutSetLog set in sets) set.toJson(),
        ],
        'skipped': skipped,
      };
}

/// One Warm-up movement recorded outside the working exercises.
class WarmupMovementLog {
  const WarmupMovementLog({
    required this.exerciseName,
    required this.sets,
    this.exerciseId,
  });

  factory WarmupMovementLog.fromJson(Map<String, dynamic> json) =>
      WarmupMovementLog(
        exerciseId: json['exercise_id'] as String?,
        exerciseName: json['exercise_name'] as String,
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic set) =>
                WarmupSetLog.fromJson(set as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String? exerciseId;
  final String exerciseName;
  final List<WarmupSetLog> sets;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'sets': <Map<String, dynamic>>[
          for (final WarmupSetLog set in sets) set.toJson(),
        ],
      };
}

/// One Warm-up set; null weight represents bodyweight or a band.
class WarmupSetLog {
  const WarmupSetLog({required this.reps, this.weightKg});

  factory WarmupSetLog.fromJson(Map<String, dynamic> json) => WarmupSetLog(
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        reps: (json['reps'] as num).toInt(),
      );

  final double? weightKg;
  final int reps;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
      };
}

/// One Warm-up movement as retained by an Android Workout draft.
class WarmupMovementDraft {
  const WarmupMovementDraft({
    required this.exerciseName,
    required this.sets,
    this.exerciseId,
  });

  factory WarmupMovementDraft.fromJson(Map<String, dynamic> json) =>
      WarmupMovementDraft(
        exerciseId: json['exercise_id'] as String?,
        exerciseName: json['exercise_name'] as String,
        sets: (json['sets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic set) =>
                WarmupSetDraft.fromJson(set as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String? exerciseId;
  final String exerciseName;
  final List<WarmupSetDraft> sets;

  bool get hasTickedSets => sets.any((WarmupSetDraft set) => set.ticked);

  WarmupMovementLog toCommitLog() => WarmupMovementLog(
        exerciseId: exerciseId,
        exerciseName: exerciseName,
        sets: <WarmupSetLog>[
          for (final WarmupSetDraft set in sets)
            if (set.ticked) WarmupSetLog(weightKg: set.weightKg, reps: set.reps),
        ],
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'sets': <Map<String, dynamic>>[
          for (final WarmupSetDraft set in sets) set.toJson(),
        ],
      };
}

/// A Warm-up set and its tick state retained until the draft syncs.
class WarmupSetDraft {
  const WarmupSetDraft({
    required this.reps,
    this.weightKg,
    this.ticked = false,
  });

  factory WarmupSetDraft.fromJson(Map<String, dynamic> json) => WarmupSetDraft(
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        reps: (json['reps'] as num).toInt(),
        ticked: json['ticked'] as bool? ?? false,
      );

  final double? weightKg;
  final int reps;
  final bool ticked;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'weight_kg': weightKg,
        'reps': reps,
        'ticked': ticked,
      };
}

/// Draft sync states (ADR 020/033). Wire strings match the storage contract.
abstract final class DraftStatus {
  static const String pending = 'pending';
  static const String syncing = 'syncing';
  static const String synced = 'synced';
  static const String needsReconciliation = 'needs_reconciliation';
}

/// A workout recorded on the device but not yet committed to history (ADR 020).
///
/// The [clientSessionId] is generated once at creation and never changes, so a
/// lost response can be reconciled and a retry can never create a second
/// session.
class WorkoutDraft {
  const WorkoutDraft({
    required this.clientSessionId,
    required this.accountId,
    required this.performedDate,
    required this.performedTimezone,
    required this.programVersion,
    required this.dayOrder,
    required this.dayName,
    required this.capturedAt,
    required this.exercises,
    this.warmupMovements = const <WarmupMovementDraft>[],
    this.cardio,
    required this.readiness,
    this.notes = '',
    this.status = DraftStatus.pending,
    this.lastError,
    this.serverResponse,
    required this.updatedAt,
    this.attempt = 0,
    this.nextAttemptAt,
  });

  factory WorkoutDraft.fromJson(Map<String, dynamic> json) => WorkoutDraft(
        clientSessionId: json['client_session_id'] as String,
        accountId: json['account_id'] as String,
        performedDate: json['performed_date'] as String,
        performedTimezone: json['performed_timezone'] as String,
        programVersion: (json['program_version'] as num).toInt(),
        dayOrder: (json['day_order'] as num).toInt(),
        dayName: json['day_name'] as String? ?? 'Day',
        capturedAt: json['captured_at'] as String,
        exercises: (json['exercises'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic e) =>
                DraftExercise.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        warmupMovements:
            (json['warmup_movements'] as List<dynamic>? ?? const <dynamic>[])
                .map((dynamic movement) => WarmupMovementDraft.fromJson(
                    movement as Map<String, dynamic>))
                .toList(growable: false),
        cardio: json['cardio'] is Map<String, dynamic>
            ? WorkoutCardio.fromJson(json['cardio'] as Map<String, dynamic>)
            : null,
        readiness: (json['readiness'] as num?)?.toInt() ?? 4,
        notes: json['notes'] as String? ?? '',
        status: json['status'] as String? ?? DraftStatus.pending,
        lastError: json['last_error'] as String?,
        serverResponse: json['server_response'] as Map<String, dynamic>?,
        updatedAt: json['updated_at'] as String? ?? '',
        attempt: (json['attempt'] as num?)?.toInt() ?? 0,
        nextAttemptAt: json['next_attempt_at'] as String?,
      );

  final String clientSessionId;
  final String accountId;
  final String performedDate;
  final String performedTimezone;
  final int programVersion;
  final int dayOrder;
  final String dayName;
  final String capturedAt;
  final List<DraftExercise> exercises;
  final List<WarmupMovementDraft> warmupMovements;
  final WorkoutCardio? cardio;
  final int readiness;
  final String notes;
  final String status;
  final String? lastError;
  final Map<String, dynamic>? serverResponse;
  final String updatedAt;

  /// Consecutive network/timeout/5xx failures since the last success or
  /// manual retry, driving the exponential backoff delay (ADR 020/033).
  final int attempt;

  /// The earliest instant (ISO, same clock as [capturedAt]/[updatedAt]) a
  /// backed-off draft may be retried; null when due immediately.
  final String? nextAttemptAt;

  bool get isSynced => status == DraftStatus.synced;

  bool get needsAttention => status == DraftStatus.needsReconciliation;

  bool get inFlight => status == DraftStatus.syncing;

  /// The server session id from a successful commit, or null before then.
  String? get serverSessionId => serverResponse?['session_id'] as String?;

  /// The program version active on the server when this draft synced (ADR 034),
  /// or null before a commit response is stored.
  int? get activeProgramVersionAtSync =>
      (serverResponse?['active_program_version_at_sync'] as num?)?.toInt();

  /// True when the server committed this draft against a now-superseded program.
  bool get isHistoricalProgram =>
      serverResponse?['is_historical_program'] == true;

  /// Player-facing version-difference note for a historical-program sync, else null.
  String? get versionDifferenceLabel => historicalProgramLabel(
        programVersion,
        activeProgramVersionAtSync,
        isHistoricalProgram,
      );

  /// True for a draft that is not yet committed (pending, syncing, or failed).
  bool get isUnsynced => !isSynced;

  int get workingSetCount => exercises.fold<int>(
      0,
      (int total, DraftExercise exercise) =>
          total +
          (exercise.skipped
              ? 0
              : exercise.sets.where((WorkoutSetLog s) => !s.isWarmup).length));

  String get statusLabel => switch (status) {
        DraftStatus.pending || DraftStatus.syncing => 'Pending',
        DraftStatus.synced => 'Synced',
        DraftStatus.needsReconciliation => 'Needs attention',
        _ => status,
      };

  WorkoutDraft copyWith({
    String? performedDate,
    String? status,
    String? lastError,
    Map<String, dynamic>? serverResponse,
    String? updatedAt,
    int? attempt,
    String? nextAttemptAt,
    bool clearNextAttempt = false,
    bool clearLastError = false,
  }) =>
      WorkoutDraft(
        clientSessionId: clientSessionId,
        accountId: accountId,
        performedDate: performedDate ?? this.performedDate,
        performedTimezone: performedTimezone,
        programVersion: programVersion,
        dayOrder: dayOrder,
        dayName: dayName,
        capturedAt: capturedAt,
        exercises: exercises,
        warmupMovements: warmupMovements,
        cardio: cardio,
        readiness: readiness,
        notes: notes,
        status: status ?? this.status,
        lastError: clearLastError ? null : (lastError ?? this.lastError),
        serverResponse: serverResponse ?? this.serverResponse,
        updatedAt: updatedAt ?? this.updatedAt,
        attempt: attempt ?? this.attempt,
        nextAttemptAt:
            clearNextAttempt ? null : (nextAttemptAt ?? this.nextAttemptAt),
      );

  /// The `POST /workouts/sessions` body for this draft.
  Map<String, dynamic> toCommitBody() => <String, dynamic>{
        'day_order': dayOrder,
        'readiness': readiness,
        'session_notes': notes,
        'sets': <Map<String, dynamic>>[
          for (final DraftExercise exercise in exercises)
            if (!exercise.skipped && exercise.sets.isNotEmpty)
              <String, dynamic>{
                'exercise': exercise.exercise,
                'sets': <Map<String, dynamic>>[
                  for (final WorkoutSetLog set in exercise.sets) set.toJson(),
                ],
              },
        ],
        if (warmupMovements.any((WarmupMovementDraft movement) =>
            movement.hasTickedSets))
          'warmup_movements': <Map<String, dynamic>>[
            for (final WarmupMovementDraft movement in warmupMovements)
              if (movement.hasTickedSets) movement.toCommitLog().toJson(),
          ],
        if (cardio?.isCommitted == true) 'cardio': cardio!.toCommitJson(),
        'client_session_id': clientSessionId,
        'performed_date': performedDate,
        'performed_timezone': performedTimezone,
        'program_version': programVersion,
        'captured_at': capturedAt,
      };

  Map<String, dynamic> toJson() => <String, dynamic>{
        'client_session_id': clientSessionId,
        'account_id': accountId,
        'performed_date': performedDate,
        'performed_timezone': performedTimezone,
        'program_version': programVersion,
        'day_order': dayOrder,
        'day_name': dayName,
        'captured_at': capturedAt,
        'exercises': <Map<String, dynamic>>[
          for (final DraftExercise exercise in exercises) exercise.toJson(),
        ],
        if (warmupMovements.isNotEmpty)
          'warmup_movements': <Map<String, dynamic>>[
            for (final WarmupMovementDraft movement in warmupMovements)
              movement.toJson(),
          ],
        if (cardio != null) 'cardio': cardio!.toJson(),
        'readiness': readiness,
        'notes': notes,
        'status': status,
        'last_error': lastError,
        'server_response': serverResponse,
        'updated_at': updatedAt,
        'attempt': attempt,
        'next_attempt_at': nextAttemptAt,
      };
}

/// One auto-regulated target from `GET /workouts/prescription`.
class PrescriptionTarget {
  const PrescriptionTarget({
    required this.exerciseId,
    required this.exerciseName,
    required this.isBarbell,
    required this.effectiveSets,
    required this.targetRpeCap,
    required this.projectedWeight,
    this.lastPerf = const <Map<String, dynamic>>[],
  });

  factory PrescriptionTarget.fromJson(Map<String, dynamic> json) =>
      PrescriptionTarget(
        exerciseId: json['exercise_id'] as String,
        exerciseName: json['exercise_name'] as String? ?? '',
        isBarbell: json['is_barbell'] as bool? ?? false,
        effectiveSets: (json['effective_sets'] as num?)?.toInt() ?? 3,
        targetRpeCap: (json['target_rpe_cap'] as num?)?.toDouble() ?? 8.5,
        projectedWeight: (json['projected_weight'] as num?)?.toDouble() ?? 0,
        lastPerf: (json['last_perf'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic s) =>
                Map<String, dynamic>.from(s as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String exerciseId;
  final String exerciseName;
  final bool isBarbell;
  final int effectiveSets;
  final double targetRpeCap;
  final double projectedWeight;
  final List<Map<String, dynamic>> lastPerf;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'exercise_id': exerciseId,
        'exercise_name': exerciseName,
        'is_barbell': isBarbell,
        'effective_sets': effectiveSets,
        'target_rpe_cap': targetRpeCap,
        'projected_weight': projectedWeight,
        'last_perf': lastPerf,
      };
}

enum DeloadState { applied, suggested, none }

/// The server's decision and the fatigue signal that produced it.
class DeloadDecision {
  const DeloadDecision({
    this.state = DeloadState.none,
    this.reason,
    this.volumeMultiplier = 1.0,
    this.intensityCapRpe,
  });

  factory DeloadDecision.fromJson(Map<String, dynamic> json) {
    final Object? rawState = json['state'];
    final String stateName = rawState is String ? rawState : 'none';
    final DeloadState state = switch (stateName) {
      'applied' => DeloadState.applied,
      'suggested' => DeloadState.suggested,
      'none' => DeloadState.none,
      _ => DeloadState.none,
    };
    return DeloadDecision(
      state: state,
      reason: json['reason'] as String?,
      volumeMultiplier:
          (json['volume_multiplier'] as num?)?.toDouble() ?? 1.0,
      intensityCapRpe:
          (json['intensity_cap_rpe'] as num?)?.toDouble(),
    );
  }

  final DeloadState state;
  final String? reason;
  final double volumeMultiplier;
  final double? intensityCapRpe;

  bool get isVisible => state != DeloadState.none;
  bool get isApplied => state == DeloadState.applied;
  bool get isSuggested => state == DeloadState.suggested;

  String get title => isApplied ? 'Deload applied' : 'Deload suggested';

  List<String> get changeDetails {
    final List<String> changes = <String>[];
    if (volumeMultiplier < 1.0) {
      final int targetVolume = (volumeMultiplier * 100).round();
      changes.add('sets scaled to $targetVolume% of plan');
    }
    final double? rpeCap = intensityCapRpe;
    if (rpeCap != null) {
      changes.add('RPE capped at ${_formatDeloadRpe(rpeCap)}');
    }
    return changes;
  }

  String get changeSummary {
    final List<String> changes = changeDetails;
    if (changes.isEmpty) {
      return isApplied
          ? 'No set or RPE changes applied.'
          : 'No set or RPE changes proposed. Your coach has been told.';
    }
    final String action = isApplied ? 'Applied' : 'If applied';
    final String coachNote = isSuggested ? ' Your coach has been told.' : '';
    return '$action: ${changes.join(' · ')}.$coachNote';
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        'state': state.name,
        'reason': reason,
        'volume_multiplier': volumeMultiplier,
        'intensity_cap_rpe': intensityCapRpe,
      };
}

String _formatDeloadRpe(double rpe) => rpe == rpe.roundToDouble()
    ? rpe.toStringAsFixed(0)
    : rpe.toStringAsFixed(1);

/// `GET /workouts/prescription`: fatigue state and auto-regulated targets.
class Prescription {
  const Prescription(
      {this.fatigueInfo = const <String, dynamic>{},
      this.deload = const DeloadDecision(),
      required this.targets});

  factory Prescription.fromJson(Map<String, dynamic> json) => Prescription(
        fatigueInfo: Map<String, dynamic>.from(
            (json['fatigue_info'] as Map<String, dynamic>?) ??
                const <String, dynamic>{}),
        deload: DeloadDecision.fromJson(
          (json['deload'] as Map<String, dynamic>?) ??
              const <String, dynamic>{},
        ),
        targets: (json['targets'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic t) =>
                PrescriptionTarget.fromJson(t as Map<String, dynamic>))
            .toList(growable: false),
      );

  final Map<String, dynamic> fatigueInfo;
  final DeloadDecision deload;
  final List<PrescriptionTarget> targets;

  PrescriptionTarget? forExercise(String exerciseId) {
    for (final PrescriptionTarget target in targets) {
      if (target.exerciseId == exerciseId) {
        return target;
      }
    }
    return null;
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        'fatigue_info': fatigueInfo,
        'deload': deload.toJson(),
        'targets': <Map<String, dynamic>>[
          for (final PrescriptionTarget target in targets) target.toJson(),
        ],
      };
}

/// One catalog exercise from `GET /workouts/exercises?query=`, used to pick a
/// real unplanned exercise instead of inventing an id (ADR 020/033, #34).
///
/// [imagePath] is the catalog's relative picture path, carried so an exercise
/// added this way gets its card's picture like any planned one (#161).
/// [targetMuscle] is the catalog's `target_muscle` column, carried so the
/// Replace exercise search can pre-filter its results to the planned
/// exercise's muscle client-side (#162).
class ExerciseCatalogEntry {
  const ExerciseCatalogEntry({
    required this.id,
    required this.name,
    this.imagePath,
    this.targetMuscle,
  });

  factory ExerciseCatalogEntry.fromJson(Map<String, dynamic> json) =>
      ExerciseCatalogEntry(
        id: json['id'] as String,
        name: json['name'] as String,
        imagePath: json['image_path'] as String?,
        targetMuscle: json['target_muscle'] as String?,
      );

  final String id;
  final String name;
  final String? imagePath;

  /// The muscle the catalog file trains (`Quads`, `Chest`, …), or null when
  /// the row carries none.
  final String? targetMuscle;
}

/// `GET /workouts/exercises/{exercise_id}`: read-only catalog detail for the
/// exercise-detail view (#53).
///
/// [category] mirrors [bodyPart] in the source data (the same field upstream).
/// [imagePath]/[gifPath] are the ExerciseDB-derived local file paths stored in
/// the catalog; they are relative paths (`images/…`, `videos/…`) that resolve
/// to the API's public `/media` route through [mediaUrlFor]. Rendering them
/// stays behind the build-time media flag and Gym visual's terms
/// (`docs/design-review/53/MEDIA-PROVENANCE.md`).
class ExerciseCatalogDetail {
  const ExerciseCatalogDetail({
    required this.id,
    required this.name,
    required this.category,
    required this.bodyPart,
    required this.equipment,
    required this.primaryMuscles,
    required this.secondaryMuscles,
    this.instructions,
    this.imagePath,
    this.gifPath,
  });

  factory ExerciseCatalogDetail.fromJson(Map<String, dynamic> json) =>
      ExerciseCatalogDetail(
        id: json['id'] as String,
        name: json['name'] as String,
        category: json['category'] as String? ?? '',
        bodyPart: json['body_part'] as String? ?? '',
        equipment: json['equipment'] as String? ?? '',
        primaryMuscles: _stringList(json['primary_muscles']),
        secondaryMuscles: _stringList(json['secondary_muscles']),
        instructions: json['instructions'] as String?,
        imagePath: json['image_path'] as String?,
        gifPath: json['gif_path'] as String?,
      );

  final String id;
  final String name;
  final String category;
  final String bodyPart;
  final String equipment;
  final List<String> primaryMuscles;
  final List<String> secondaryMuscles;
  final String? instructions;
  final String? imagePath;
  final String? gifPath;

  bool get hasInstructions =>
      instructions != null && instructions!.trim().isNotEmpty;

  /// All distinct muscle labels (primary then secondary), for the chips.
  List<String> get muscles => <String>[
        ...primaryMuscles,
        for (final String muscle in secondaryMuscles)
          if (!primaryMuscles.contains(muscle)) muscle,
      ];

  /// The served address of the animated GIF (`GET /media/videos/…`), null
  /// when the catalog row carries no GIF (#53/#161).
  String? get gifUrl => mediaUrlFor(gifPath);

  /// The served address of the still picture (`GET /media/images/…`), null
  /// when the catalog row carries no picture (#53/#161).
  String? get imageUrl => mediaUrlFor(imagePath);

  /// True when any of the catalog's media can be shown: the relative
  /// ExerciseDB paths resolve through [mediaUrlFor], which refuses a payload
  /// that would point the app at a host other than the configured API base.
  bool get hasLoadableMedia => gifUrl != null || imageUrl != null;
}

/// One distinct exercise the player has logged history for
/// (`GET /dashboard/exercises`, #48).
class LoggedExercise {
  const LoggedExercise({required this.id, required this.name});

  factory LoggedExercise.fromJson(Map<String, dynamic> json) => LoggedExercise(
        id: json['id'] as String,
        name: json['name'] as String,
      );

  final String id;
  final String name;
}

/// One progression point in `GET /dashboard/exercises/{id}/history`.
class ExerciseHistoryPoint {
  const ExerciseHistoryPoint({
    required this.date,
    required this.weightKg,
    required this.reps,
    required this.rpe,
    required this.e1rm,
  });

  factory ExerciseHistoryPoint.fromJson(Map<String, dynamic> json) =>
      ExerciseHistoryPoint(
        date: json['date'] as String,
        weightKg: (json['weight_kg'] as num).toDouble(),
        reps: (json['reps'] as num).toInt(),
        rpe: (json['rpe'] as num?)?.toDouble(),
        e1rm: (json['e1rm'] as num).toDouble(),
      );

  final String date;
  final double weightKg;
  final int reps;

  /// Stored RPE, null when the set was logged without effort (#111); shown to
  /// the player as RIR through [rirLabel] (core/effort.dart).
  final double? rpe;
  final double e1rm;
}

/// `GET /dashboard/exercises/{id}/history`: progression points, records, caption.
class ExerciseHistory {
  const ExerciseHistory({
    required this.history,
    required this.records,
    this.caption,
  });

  factory ExerciseHistory.fromJson(Map<String, dynamic> json) =>
      ExerciseHistory(
        history: (json['history'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic point) =>
                ExerciseHistoryPoint.fromJson(point as Map<String, dynamic>))
            .toList(growable: false),
        records: (json['records'] as List<dynamic>? ?? const <dynamic>[])
            .map((dynamic record) =>
                CoachExerciseRecord.fromJson(record as Map<String, dynamic>))
            .toList(growable: false),
        caption: json['caption'] as String?,
      );

  final List<ExerciseHistoryPoint> history;
  final List<CoachExerciseRecord> records;
  final String? caption;

  bool get isEmpty => history.isEmpty;
}

List<String> _stringList(dynamic raw) =>
    (raw as List<dynamic>? ?? const <dynamic>[])
        .map((dynamic value) => value.toString())
        .toList(growable: false);

/// `GET /workouts/sessions/latest`: the player's most recent committed session.
///
/// [splitName] is the program day name written at commit; [dayOrder] is null
/// when the ledger does not store one, so Home matches the program day by name.
class LatestSession {
  const LatestSession({
    required this.sessionId,
    required this.sessionDate,
    required this.splitName,
    this.dayOrder,
    this.programVersion,
    this.warmupMovements = const <WarmupMovementLog>[],
    this.cardio,
  });

  factory LatestSession.fromJson(Map<String, dynamic> json) => LatestSession(
        sessionId: json['session_id'] as String,
        sessionDate: json['session_date'] as String,
        splitName: json['split_name'] as String? ?? '',
        dayOrder: (json['day_order'] as num?)?.toInt(),
        programVersion: (json['program_version'] as num?)?.toInt(),
        warmupMovements: (json['warmup_movements'] as List<dynamic>? ?? const [])
            .map((dynamic movement) => WarmupMovementLog.fromJson(
                movement as Map<String, dynamic>))
            .toList(growable: false),
        cardio: json['cardio'] is Map<String, dynamic>
            ? WorkoutCardio.fromJson(json['cardio'] as Map<String, dynamic>)
            : null,
      );

  final String sessionId;
  final String sessionDate;
  final String splitName;
  final int? dayOrder;
  final int? programVersion;
  final List<WarmupMovementLog> warmupMovements;
  final WorkoutCardio? cardio;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'session_id': sessionId,
        'session_date': sessionDate,
        'split_name': splitName,
        'day_order': dayOrder,
        'program_version': programVersion,
        'warmup_movements': <Map<String, dynamic>>[
          for (final WarmupMovementLog movement in warmupMovements)
            movement.toJson(),
        ],
        if (cardio != null) 'cardio': cardio!.toJson(),
      };
}
