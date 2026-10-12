/// Nouns used by short Arabic gym copy that includes a count.
enum ArabicCountNoun {
  day(
    zeroAndFew: 'أيام',
    one: 'يوم واحد',
    dualNominative: 'يومان',
    dualOblique: 'يومين',
    many: 'يومًا',
    other: 'يوم',
  ),
  group(
    zeroAndFew: 'مجموعات',
    one: 'مجموعة واحدة',
    dualNominative: 'مجموعتان',
    dualOblique: 'مجموعتين',
    many: 'مجموعة',
    other: 'مجموعة',
  ),
  trainingSet(
    zeroAndFew: 'مجموعات تدريب',
    one: 'مجموعة تدريب واحدة',
    dualNominative: 'مجموعتا تدريب',
    dualOblique: 'مجموعتي تدريب',
    many: 'مجموعة تدريب',
    other: 'مجموعة تدريب',
  ),
  exercise(
    zeroAndFew: 'تمارين',
    one: 'تمرين واحد',
    dualNominative: 'تمرينان',
    dualOblique: 'تمرينين',
    many: 'تمرينًا',
    other: 'تمرين',
  ),
  warmupSet(
    zeroAndFew: 'مجموعات إحماء',
    one: 'مجموعة إحماء واحدة',
    dualNominative: 'مجموعتا إحماء',
    dualOblique: 'مجموعتي إحماء',
    many: 'مجموعة إحماء',
    other: 'مجموعة إحماء',
  ),
  session(
    zeroAndFew: 'حصص',
    one: 'حصة واحدة',
    dualNominative: 'حصتان',
    dualOblique: 'حصتين',
    many: 'حصة',
    other: 'حصة',
  ),
  trainingSession(
    zeroAndFew: 'حصص تدريبية',
    one: 'حصة تدريبية واحدة',
    dualNominative: 'حصتان تدريبيتان',
    dualOblique: 'حصتين تدريبيتين',
    many: 'حصة تدريبية',
    other: 'حصة تدريبية',
  ),
  workoutDraft(
    zeroAndFew: 'مسودات تدريبية',
    one: 'مسودة تدريبية واحدة',
    dualNominative: 'مسودتان تدريبيتان',
    dualOblique: 'مسودتين تدريبيتين',
    many: 'مسودة تدريبية',
    other: 'مسودة تدريبية',
  ),
  year(
    zeroAndFew: 'سنوات',
    one: 'سنة واحدة',
    dualNominative: 'سنتان',
    dualOblique: 'سنتين',
    many: 'سنة',
    other: 'سنة',
  ),
  second(
    zeroAndFew: 'ثوانٍ',
    one: 'ثانية واحدة',
    dualNominative: 'ثانيتان',
    dualOblique: 'ثانيتين',
    many: 'ثانية',
    other: 'ثانية',
  ),
  repetition(
    zeroAndFew: 'تكرارات',
    one: 'تكرار واحد',
    dualNominative: 'تكراران',
    dualOblique: 'تكرارين',
    many: 'تكرارًا',
    other: 'تكرار',
  ),
  character(
    zeroAndFew: 'أحرف',
    one: 'حرف واحد',
    dualNominative: 'حرفان',
    dualOblique: 'حرفين',
    many: 'حرفًا',
    other: 'حرف',
  ),
  assignment(
    zeroAndFew: 'علاقات تدريب',
    one: 'علاقة تدريب واحدة',
    dualNominative: 'علاقتا تدريب',
    dualOblique: 'علاقتي تدريب',
    many: 'علاقة تدريب',
    other: 'علاقة تدريب',
  ),
  alert(
    zeroAndFew: 'تنبيهات',
    one: 'تنبيه واحد',
    dualNominative: 'تنبيهان',
    dualOblique: 'تنبيهين',
    many: 'تنبيهًا',
    other: 'تنبيه',
  ),
  request(
    zeroAndFew: 'طلبات',
    one: 'طلب واحد',
    dualNominative: 'طلبان',
    dualOblique: 'طلبين',
    many: 'طلبًا',
    other: 'طلب',
  ),
  warmupMovement(
    zeroAndFew: 'حركات إحماء',
    one: 'حركة إحماء واحدة',
    dualNominative: 'حركتا إحماء',
    dualOblique: 'حركتي إحماء',
    many: 'حركة إحماء',
    other: 'حركة إحماء',
  ),
  minute(
    zeroAndFew: 'دقائق',
    one: 'دقيقة واحدة',
    dualNominative: 'دقيقتان',
    dualOblique: 'دقيقتين',
    many: 'دقيقة',
    other: 'دقيقة',
  );

  const ArabicCountNoun({
    required this.zeroAndFew,
    required this.one,
    required this.dualNominative,
    required this.dualOblique,
    required this.many,
    required this.other,
  });

  final String zeroAndFew;
  final String one;
  final String dualNominative;
  final String dualOblique;
  final String many;
  final String other;
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
  // Mirrors agent/debrief.py:arabic_count_phrase.
  final String numericCount = isolateCount ? '\u2066$count\u2069' : '$count';
  if (count == 0) return '$numericCount ${noun.zeroAndFew}';
  if (count == 1) return noun.one;
  if (count == 2) {
    final String dual =
        afterPreposition ? noun.dualOblique : noun.dualNominative;
    return dual;
  }

  final int remainder = count % 100;
  if (remainder >= 3 && remainder <= 10) {
    return '$numericCount ${noun.zeroAndFew}';
  }
  if (remainder >= 11 && remainder <= 99) {
    return '$numericCount ${noun.many}';
  }
  return '$numericCount ${noun.other}';
}
