/// Wire models mirroring the FastAPI service contracts in `svc/schemas.py` and
/// `agent/ProgramState.py`.
library;

class Capabilities {
  const Capabilities({required this.player, required this.coach});

  factory Capabilities.fromJson(Map<String, dynamic> json) => Capabilities(
        player: json['player'] as bool? ?? false,
        coach: json['coach'] as bool? ?? false,
      );

  final bool player;
  final bool coach;
}

/// Current account identity and capabilities from `GET /auth/me`.
class Account {
  const Account({
    required this.accountId,
    required this.traineeId,
    required this.capabilities,
  });

  factory Account.fromJson(Map<String, dynamic> json) => Account(
        accountId: json['account_id'] as String,
        traineeId: json['trainee_id'] as String,
        capabilities: Capabilities.fromJson(
          json['capabilities'] as Map<String, dynamic>,
        ),
      );

  final String accountId;

  /// The legacy wire field for the reusable username.
  final String traineeId;
  final Capabilities capabilities;

  bool get isCoach => capabilities.coach;
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
class OnboardingCompletion {
  const OnboardingCompletion({
    required this.programName,
    required this.weeklyFrequency,
  });

  factory OnboardingCompletion.fromJson(Map<String, dynamic> json) =>
      OnboardingCompletion(
        programName: json['program_name'] as String,
        weeklyFrequency: (json['weekly_frequency'] as num).toInt(),
      );

  final String programName;
  final int weeklyFrequency;
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
    this.restSeconds = 180,
    this.notes,
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
        restSeconds: (json['rest_seconds'] as num?)?.toInt() ?? 180,
        notes: json['notes'] as String?,
      );

  final String exerciseId;
  final String exerciseName;
  final int targetSets;
  final int targetRepsMin;
  final int targetRepsMax;
  final double targetRpe;

  /// Ramped warm-up sets prescribed before the working sets (0 when none).
  final int warmupSets;
  final int restSeconds;
  final String? notes;

  bool get hasNotes => notes != null && notes!.isNotEmpty;

  bool get hasWarmupSets => warmupSets > 0;

  String get prescription =>
      '$targetSets × $targetRepsMin–$targetRepsMax @ RPE ${targetRpe.toStringAsFixed(1)}';

  String get restLabel => 'rest ${restSeconds}s';
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
}

/// `GeneratedProgramSchema` from `GET /programs/active`.
class TrainingProgram {
  const TrainingProgram({
    required this.programName,
    required this.splitType,
    required this.weeklyFrequency,
    required this.days,
  });

  factory TrainingProgram.fromJson(Map<String, dynamic> json) =>
      TrainingProgram(
        programName: json['program_name'] as String,
        splitType: json['split_type'] as String? ?? 'custom',
        weeklyFrequency: (json['weekly_frequency'] as num).toInt(),
        days: (json['days'] as List<dynamic>? ?? const [])
            .map((dynamic d) => ProgramDay.fromJson(d as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String programName;
  final String splitType;
  final int weeklyFrequency;
  final List<ProgramDay> days;
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
