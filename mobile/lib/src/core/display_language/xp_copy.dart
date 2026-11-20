/// English and Arabic copy for XP, ranks and the Weekly streak (#743, #796).
class XpCopy {
  const XpCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String _n(int value) => isArabic ? '⁦$value⁩' : '$value';

  String _grouped(int value) {
    final String digits = value.abs().toString();
    final StringBuffer out = StringBuffer(value < 0 ? '-' : '');
    for (int i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) out.write(',');
      out.write(digits[i]);
    }
    return isArabic ? '⁦$out⁩' : out.toString();
  }

  String xp(int value) => isArabic ? '${_grouped(value)} XP' : '${_grouped(value)} XP';

  String get yourRank => isArabic ? 'رتبتك' : 'Your rank';
  String get rank => isArabic ? 'الرتبة' : 'Rank';
  String get allRanks => isArabic ? 'كل الرتب' : 'All ranks';
  String get you => isArabic ? 'أنت' : 'you';
  String get howYouEarn => isArabic ? 'كيف تكسب XP' : 'How you earn XP';

  /// The strip's progress line: "40 / 160 XP to Committed".
  String progressToNext(int into, int span, String next) => isArabic
      ? '${_n(into)} / ${_n(span)} XP للوصول إلى $next'
      : '$into / $span XP to $next';

  /// The sheet and Profile line: "120 more XP to Committed, about 15 workouts".
  String moreToNext(int remaining, String next) {
    final int workouts = (remaining / 8).ceil();
    return isArabic
        ? '${xp(remaining)} أخرى للوصول إلى $next، حوالي ${_n(workouts)} ${workouts == 1 ? 'تمرين' : 'تمارين'}'
        : '$remaining more XP to $next, about $workouts ${workouts == 1 ? 'workout' : 'workouts'}';
  }

  String get topRankReached =>
      isArabic ? 'وصلت إلى أعلى رتبة.' : 'You reached the top rank.';

  String get firstWorkoutHint => isArabic
      ? 'أكمل أول تمرين لتكسب XP'
      : 'Finish your first workout to earn XP';

  /// The strip and coach chip: "4-wk streak".
  String weekStreak(int weeks) =>
      isArabic ? 'سلسلة ${_n(weeks)} أسابيع' : '$weeks-wk streak';

  String weeklyStreakWeeks(int weeks) => isArabic
      ? '${_n(weeks)} ${weeks == 1 ? 'أسبوع' : 'أسابيع'}'
      : '$weeks wk';

  String get streakPaused => isArabic ? 'السلسلة متوقفة مؤقتًا' : 'Streak paused';
  String get paused => isArabic ? 'متوقفة' : 'paused';
  String get noStreakYet => isArabic ? 'لا سلسلة بعد' : 'No streak yet';
  String get thisWeekDone =>
      isArabic ? 'هذا الأسبوع مكتمل' : 'this week done';

  String get weeklyStreak => isArabic ? 'السلسلة الأسبوعية' : 'Weekly streak';
  String get longestStreak => isArabic ? 'أطول سلسلة' : 'Longest streak';
  String get workouts => isArabic ? 'التمارين' : 'Workouts';

  String ruleLabel(String kind) => switch (kind) {
        'planned_workout' =>
          isArabic ? 'إكمال تمرين مخطط' : 'Planned workout completed',
        'all_sets' =>
          isArabic ? 'إنجاز كل المجموعات المقررة' : 'All prescribed sets done',
        'effort_in_range' =>
          isArabic ? 'جهد ضمن النطاق المستهدف' : 'Effort in the target range',
        'personal_record' =>
          isArabic ? 'رقم قياسي شخصي (حتى ٢)' : 'Personal record (up to 2)',
        'cardio' => isArabic ? 'تسجيل جلسة كارديو' : 'Cardio session logged',
        'weekly_streak' =>
          isArabic ? 'الحفاظ على السلسلة الأسبوعية' : 'Weekly streak kept',
        _ => kind,
      };

  /// The Rank sheet's earning table, in rule order.
  List<({String label, String value})> get earningTable =>
      <({String label, String value})>[
        (label: ruleLabel('planned_workout'), value: '+5'),
        (label: ruleLabel('all_sets'), value: '+2'),
        (label: ruleLabel('effort_in_range'), value: '+1'),
        (label: ruleLabel('personal_record'), value: isArabic ? '+2 لكل رقم' : '+2 each'),
        (label: ruleLabel('cardio'), value: '+2'),
        (label: ruleLabel('weekly_streak'), value: '+5'),
      ];

  String get earningFootnote => isArabic
      ? 'يُحتسب تمرين واحد في اليوم. زيادة الوزن أو الجهد لا تضيف XP، وأسابيع التخفيف تكسب XP كاملًا. لا ينقص XP أبدًا.'
      : 'One workout a day counts. Going heavier earns nothing extra, and deload weeks earn full XP. XP never goes down.';

  // Workout saved (#796).
  String awarded(int value) => isArabic ? '+${_n(value)} XP' : '+$value XP';
  String get earnedForThisWorkout =>
      isArabic ? 'لهذا التمرين' : 'earned for this workout';
  String get streakCountsAtWeekEnd => isArabic
      ? 'السلسلة الأسبوعية: تُحتسب في نهاية الأسبوع'
      : 'Weekly streak: counts at the end of the week';
  String get effortAboveRangeNote => isArabic
      ? 'الجهد الأعلى من النطاق المستهدف لا يكسب XP، فلا داعي لتجاوز خطتك من أجل النقاط.'
      : 'Effort above the target range earns no XP, so you never have to push harder than your plan for points.';
  String get notCountedToday => isArabic
      ? 'تمرين واحد في اليوم يكسب XP، وقد حُفظ هذا التمرين.'
      : 'Only one workout a day earns XP. This one is saved.';
  String get xpAfterSync => isArabic
      ? 'يُضاف XP عند مزامنة هذا التمرين.'
      : 'XP is added when this workout syncs.';
  String rankLine(String rankName, int total) => isArabic
      ? '$rankName · ${xp(total)}'
      : '$rankName · ${xp(total)}';
  String toNext(int remaining, String next) => isArabic
      ? '${_n(remaining)} للوصول إلى $next'
      : '$remaining to $next';

  // Rank up (#796).
  String get newRank => isArabic ? 'رتبة جديدة' : 'New rank';
  String get rankUpLine => isArabic
      ? 'تمارين أنجزتها كما طلبت خطتك. هذا ما يقدّمك للأمام.'
      : "Workouts done the way your plan asked. That's what moves you forward.";
  String rankUpProgress(int total, String? next, int? threshold) {
    if (next == null || threshold == null) return xp(total);
    return isArabic
        ? '${xp(total)} · التالية: $next عند ${xp(threshold)}'
        : '${xp(total)} · next: $next at ${xp(threshold)}';
  }

  String get keepGoing => isArabic ? 'واصل' : 'Keep going';
  String get seeAllRanks => isArabic ? 'كل الرتب' : 'See all ranks';
}
