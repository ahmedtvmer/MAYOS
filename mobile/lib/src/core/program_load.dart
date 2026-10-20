/// A coach-authored fixed or e1RM-relative exercise load.
class ProgramLoad {
  const ProgramLoad({required this.kind, required this.value});

  factory ProgramLoad.fromJson(Map<String, dynamic> json) => ProgramLoad(
        kind: json['kind'] as String,
        value: (json['value'] as num).toDouble(),
      );

  static const double minimumKg = 0;
  static const double maximumKg = 1000;
  static const double minimumPercentE1rm = 1;
  static const double maximumPercentE1rm = 100;
  static const double weightIncrementKg = 2.5;

  final String kind;
  final double value;

  static bool acceptsValue(String kind, double candidate) => switch (kind) {
        'kg' => candidate > minimumKg && candidate <= maximumKg,
        'pct_e1rm' =>
          candidate >= minimumPercentE1rm &&
              candidate <= maximumPercentE1rm,
        _ => false,
      };

  double? suggestedWeightKg(double? bestE1rmKg) {
    if (kind == 'kg') return value;
    if (kind != 'pct_e1rm') return null;
    if (bestE1rmKg == null) return null;
    return roundToWeightIncrement(bestE1rmKg * value / maximumPercentE1rm);
  }

  static double roundToWeightIncrement(double weightKg) =>
      (weightKg / weightIncrementKg).round() * weightIncrementKg;

  static String formatValue(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : '$value';

  Map<String, dynamic> toJson() => <String, dynamic>{
        'kind': kind,
        'value': value,
      };
}
