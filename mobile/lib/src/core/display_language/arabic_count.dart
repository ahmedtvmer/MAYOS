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
String arabicCountPhrase(
  int count,
  ArabicCountNoun noun, {
  bool afterPreposition = false,
}) {
  if (count == 0) return '0 ${noun.zeroAndFew}';
  if (count == 1) return noun.one;
  if (count == 2) {
    final String dual =
        afterPreposition ? noun.dualOblique : noun.dualNominative;
    return dual;
  }

  final int magnitude = count.abs();
  if (magnitude >= 3 && magnitude <= 10) {
    return '$count ${noun.zeroAndFew}';
  }

  return '$count ${noun.many}';
}
