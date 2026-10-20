abstract final class ProgramDraftPrescription {
  static const int minReps = 4;
  static const int maxReps = 30;
  static const int maxDays = 5;
  static const int maxWeeks = 12;
  static const int minWarmupSets = 0;
  static const int maxWarmupSets = 4;
  static const int defaultExerciseRestSeconds = 180;
  static const int defaultWarmupMovementSets = 2;
  static const int defaultWarmupMovementReps = 10;
  static const int defaultWarmupMovementRestSeconds = 45;
  static const int minWarmupMovementSets = 1;
  static const int maxWarmupMovementSets = 3;
  static const int minWarmupMovementReps = 5;
  static const int maxWarmupMovementReps = 20;
  static const int maxTempoLength = 50;
  static const int maxProgramNotesLength = 2000;
  static const double minRir = 0;
  static const double maxRir = 5;
  static const int defaultSets = 2;
  static const int defaultBackoffSets = 3;
  static const int defaultBackoffLoadPercent = 90;
  static const int defaultMinReps = 8;
  static const int defaultMaxReps = 12;
  static const double defaultRir = 2;
}

String formatSetGroups(
  List<Map<String, dynamic>> groups, {
  required String amrapLabel,
}) => groups.map((Map<String, dynamic> group) {
      final int sets = (group['sets'] as num?)?.toInt() ?? 0;
      final int low = (group['reps_min'] as num?)?.toInt() ?? 0;
      final int high = (group['reps_max'] as num?)?.toInt() ?? low;
      final double rir = (group['target_rir'] as num?)?.toDouble() ?? 0;
      final String reps = low == high ? '$low' : '$low–$high';
      final dynamic rawLoad = group['load'];
      final String load = rawLoad is Map<String, dynamic>
          ? rawLoad['kind'] == 'pct_of_first_group'
              ? ' · −${100 - (rawLoad['value'] as num).toInt()}%'
              : rawLoad['kind'] == 'kg'
                  ? ' · ${rawLoad['value']} kg'
                  : ' · ${rawLoad['value']}% e1RM'
          : '';
      final String rirValue = rir == rir.roundToDouble() ? '${rir.toInt()}' : '$rir';
      return '$sets × $reps @ RIR $rirValue$load${group['amrap_last_set'] == true ? ' · $amrapLabel' : ''}';
    }).join(' · ');
