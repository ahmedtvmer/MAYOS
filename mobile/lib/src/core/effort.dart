/// Effort at the display boundary (#111): RIR = 10 − RPE.
///
/// The wire keeps RPE; players and coaches only ever read RIR. This is the
/// app's **single** conversion plus its two display formatters, so no screen
/// can disagree about a value or its wording:
///
/// * [rirFromRpe] / [rirLabel] — a **recorded** effort on a set: `2`, `5+`,
///   or `not rated`.
/// * [minRirLabel] / [formatMinRir] — a program **target** or deload **cap**,
///   stated as the equivalent *minimum* RIR (a maximum RPE is a floor on RIR),
///   rounded up to a whole number: `≥ 2`.
///
/// An unrated set reads `not rated` on every surface — CONTEXT.md: "a blank
/// value means the player did not rate the set".
library;

/// The one wording for a set nobody rated, on every surface.
const String unratedEffort = 'not rated';

/// Two decimals, the precision the record aggregates and the API report use.
double round2(double value) => double.parse(value.toStringAsFixed(2));

/// RIR for a stored RPE (`10 - RPE`), null when the set is unrated.
double? rirFromRpe(double? rpe) => rpe == null ? null : round2(10.0 - rpe);

/// A recorded effort from an RIR value: `2`, `5+`, `not rated`.
///
/// At most one decimal (legacy RPEs were stored as 8.3, whose raw difference
/// is 1.6999999999999993), with the trailing `.0` dropped, and RIR 5 — the top
/// of the scale — shown as `5+` everywhere, not only on the keypad chip.
String formatRir(double rir) {
  final double shown = double.parse(rir.toStringAsFixed(1));
  if (shown >= 5.0) {
    return '5+';
  }
  return shown == shown.roundToDouble() ? shown.round().toString() : '$shown';
}

/// A recorded effort for a set: `2`, `5+`, or `not rated`.
String rirLabel(double? rpe) {
  final double? rir = rirFromRpe(rpe);
  return rir == null ? unratedEffort : formatRir(rir);
}

/// The whole-number minimum RIR for an RIR value, rounded up so a target or
/// cap is never understated (six decimals first, so `1.0` never ceilings to 2).
int minRirValue(double rir) => double.parse(rir.toStringAsFixed(6)).ceil();

/// A target or cap from an RIR value: `≥ 2`.
String formatMinRir(double rir) => '≥ ${minRirValue(rir)}';

/// A target or cap as its equivalent minimum RIR: `≥ 2`, or `not rated`.
String minRirLabel(double? rpe) {
  final double? rir = rirFromRpe(rpe);
  return rir == null ? unratedEffort : formatMinRir(rir);
}
