/// Nouns used by short Arabic gym copy that includes a count.
enum ArabicCountNoun {
  day(
    zeroAndFew: 'أيام',
    one: 'يوم واحد',
    dualNominative: 'يومان',
    dualOblique: 'يومين',
    many: 'يومًا',
  ),
  group(
    zeroAndFew: 'مجموعات',
    one: 'مجموعة واحدة',
    dualNominative: 'مجموعتان',
    dualOblique: 'مجموعتين',
    many: 'مجموعة',
  ),
  trainingSet(
    zeroAndFew: 'مجموعات تدريب',
    one: 'مجموعة تدريب واحدة',
    dualNominative: 'مجموعتا تدريب',
    dualOblique: 'مجموعتي تدريب',
    many: 'مجموعة تدريب',
  ),
  workingSet(
    zeroAndFew: 'مجموعات عمل',
    one: 'مجموعة عمل واحدة',
    dualNominative: 'مجموعتا عمل',
    dualOblique: 'مجموعتي عمل',
    many: 'مجموعة عمل',
  ),
  exercise(
    zeroAndFew: 'تمارين',
    one: 'تمرين واحد',
    dualNominative: 'تمرينان',
    dualOblique: 'تمرينين',
    many: 'تمرينًا',
  ),
  warmupSet(
    zeroAndFew: 'مجموعات إحماء',
    one: 'مجموعة إحماء واحدة',
    dualNominative: 'مجموعتا إحماء',
    dualOblique: 'مجموعتي إحماء',
    many: 'مجموعة إحماء',
  ),
  session(
    zeroAndFew: 'حصص',
    one: 'حصة واحدة',
    dualNominative: 'حصتان',
    dualOblique: 'حصتين',
    many: 'حصة',
  ),
  trainingSession(
    zeroAndFew: 'حصص تدريبية',
    one: 'حصة تدريبية واحدة',
    dualNominative: 'حصتان تدريبيتان',
    dualOblique: 'حصتين تدريبيتين',
    many: 'حصة تدريبية',
  ),
  workoutDraft(
    zeroAndFew: 'مسودات تدريبية',
    one: 'مسودة تدريبية واحدة',
    dualNominative: 'مسودتان تدريبيتان',
    dualOblique: 'مسودتين تدريبيتين',
    many: 'مسودة تدريبية',
  ),
  year(
    zeroAndFew: 'سنوات',
    one: 'سنة واحدة',
    dualNominative: 'سنتان',
    dualOblique: 'سنتين',
    many: 'سنة',
  ),
  second(
    zeroAndFew: 'ثوانٍ',
    one: 'ثانية واحدة',
    dualNominative: 'ثانيتان',
    dualOblique: 'ثانيتين',
    many: 'ثانية',
  ),
  repetition(
    zeroAndFew: 'تكرارات',
    one: 'تكرار واحد',
    dualNominative: 'تكراران',
    dualOblique: 'تكرارين',
    many: 'تكرارًا',
  ),
  character(
    zeroAndFew: 'أحرف',
    one: 'حرف واحد',
    dualNominative: 'حرفان',
    dualOblique: 'حرفين',
    many: 'حرفًا',
  ),
  assignment(
    zeroAndFew: 'علاقات تدريب',
    one: 'علاقة تدريب واحدة',
    dualNominative: 'علاقتا تدريب',
    dualOblique: 'علاقتي تدريب',
    many: 'علاقة تدريب',
  ),
  alert(
    zeroAndFew: 'تنبيهات',
    one: 'تنبيه واحد',
    dualNominative: 'تنبيهان',
    dualOblique: 'تنبيهين',
    many: 'تنبيهًا',
  ),
  request(
    zeroAndFew: 'طلبات',
    one: 'طلب واحد',
    dualNominative: 'طلبان',
    dualOblique: 'طلبين',
    many: 'طلبًا',
  ),
  warmupMovement(
    zeroAndFew: 'حركات إحماء',
    one: 'حركة إحماء واحدة',
    dualNominative: 'حركتا إحماء',
    dualOblique: 'حركتي إحماء',
    many: 'حركة إحماء',
  ),
  minute(
    zeroAndFew: 'دقائق',
    one: 'دقيقة واحدة',
    dualNominative: 'دقيقتان',
    dualOblique: 'دقيقتين',
    many: 'دقيقة',
  );

  const ArabicCountNoun({
    required this.zeroAndFew,
    required this.one,
    required this.dualNominative,
    required this.dualOblique,
    required this.many,
  });

  final String zeroAndFew;
  final String one;
  final String dualNominative;
  final String dualOblique;
  final String many;
}

/// Returns a short, readable Arabic count phrase using Western digits.
///
/// [afterPreposition] selects the oblique dual form for phrases such as
/// "replace on two other days" and "rest for two seconds".
/// [isolateCount] wraps a rendered numeral in LRI/PDI when it sits inside
/// Arabic prose.
String arabicCountPhrase(
  int count,
  ArabicCountNoun noun, {
  bool afterPreposition = false,
  bool isolateCount = false,
}) {
  final String numericCount = isolateCount ? '\u2066$count\u2069' : '$count';
  if (count == 0) return '$numericCount ${noun.zeroAndFew}';
  if (count == 1) return noun.one;
  if (count == 2) {
    final String dual =
        afterPreposition ? noun.dualOblique : noun.dualNominative;
    return dual;
  }

  final int magnitude = count.abs();
  if (magnitude >= 3 && magnitude <= 10) {
    return '$numericCount ${noun.zeroAndFew}';
  }

  return '$numericCount ${noun.many}';
}
