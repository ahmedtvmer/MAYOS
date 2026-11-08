class NutritionCopy {
  const NutritionCopy(this.languageCode);
  final String languageCode;
  bool get isArabic => languageCode == 'ar';
  String get tab => isArabic ? 'التغذية' : 'Nutrition';
  String get setup => isArabic ? 'إعداد الأهداف الغذائية' : 'Set up Nutrition targets';
  String get confirmSex => isArabic ? 'اختر الجنس لحساب الأهداف الغذائية.' : 'Choose your sex for Nutrition targets.';
  String get male => isArabic ? 'ذكر' : 'Male';
  String get female => isArabic ? 'أنثى' : 'Female';
  String get dailyActivity => isArabic ? 'النشاط اليومي' : 'Daily activity';
  String get activityQuestion => isArabic ? 'ما طبيعة النشاط اليومي؟' : 'What is your Daily activity?';
  String get mostlySitting => isArabic ? 'أجلس معظم اليوم' : 'Mostly sitting';
  String get onFeet => isArabic ? 'أقف معظم اليوم' : 'On my feet';
  String get physicalJob => isArabic ? 'عمل بدني' : 'Physical job';
  String activityLabel(String? value) => switch (value) {
        'on_feet' => onFeet,
        'physical_job' => physicalJob,
        _ => mostlySitting,
      };
  String get healthCheck => isArabic ? 'فحص صحي قصير' : 'A short health check';
  String get pregnancy => isArabic ? 'هل أنتِ حامل أو مرضعة؟' : 'Are you pregnant or breastfeeding?';
  String get condition => isArabic ? 'هل لديك حالة صحية تؤثر في الغذاء؟' : 'Do you have a medical condition that affects diet?';
  String get eatingDisorder => isArabic ? 'هل عانيت من اضطراب في الأكل؟' : 'Do you have a current or past eating disorder?';
  String get showTargets => isArabic ? 'عرض الأهداف الغذائية' : 'Show my targets';
  String get saving => isArabic ? 'جارٍ الحفظ…' : 'Saving…';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get calories => isArabic ? 'سعرة حرارية' : 'kcal';
  String cardioBurned(int value) => isArabic ? 'السعرات المحروقة بالكارديو ~$value سعرة' : 'Cardio burned ~$value kcal';
  String cardioAdjustment(int value) => isArabic ? 'تعديل الهدف بسبب الكارديو +$value سعرة' : 'Cardio target adjustment +$value kcal';
  String get protein => isArabic ? 'البروتين' : 'Protein';
  String get carbs => isArabic ? 'الكربوهيدرات' : 'Carbohydrates';
  String get carbsShort => isArabic ? 'الكربوهيدرات' : 'Carbs';
  String get checkIn => isArabic ? 'متابعة اليوم' : 'Check-in';
  String get howYesterdayWent =>
      isArabic ? 'كيف كان يوم أمس؟' : 'How did yesterday go?';
  String get howDayWent =>
      isArabic ? 'كيف كان هذا اليوم؟' : 'How did this day go?';
  String onTargetCount(int count) =>
      isArabic ? '$count على الهدف' : '$count on target';
  String waterProgress(int glasses, int targetMl) => isArabic
      ? '$glasses من ${targetMl ~/ 250} أكواب · ${(glasses / 4).toStringAsFixed(2)} من ${(targetMl / 1000).toStringAsFixed(1)} لتر'
      : '$glasses of ${targetMl ~/ 250} glasses · ${(glasses / 4).toStringAsFixed(2)} of ${(targetMl / 1000).toStringAsFixed(1)} L';
  String get removeGlass =>
      isArabic ? 'إزالة كوب ماء' : 'Remove a glass of water';
  String get addWaterGlass =>
      isArabic ? 'إضافة كوب ماء' : 'Add a glass of water';
  String get waterUnavailable => isArabic
      ? 'لا يتوفر سجل الماء لهذا اليوم.'
      : 'Water history is unavailable for this day.';
  String waterAmount(int glasses) => isArabic
      ? '$glasses أكواب · ${(glasses / 4).toStringAsFixed(2)} لتر'
      : '$glasses glasses · ${(glasses / 4).toStringAsFixed(2)} L';
  String weekdayInitial(DateTime date) => (isArabic
      ? <String>['ن', 'ث', 'ر', 'خ', 'ج', 'س', 'ح']
      : <String>['M', 'T', 'W', 'T', 'F', 'S', 'S'])[date.weekday - 1];
  String activityExample(String activity) => switch (activity) {
        'on_feet' => isArabic
            ? 'مثل التدريس أو العمل في متجر.'
            : 'For example, teaching or working in a shop.',
        'physical_job' => isArabic
            ? 'مثل البناء أو حمل الأوزان في العمل.'
            : 'For example, construction or lifting at work.',
        _ => isArabic
            ? 'مثل العمل المكتبي أو الدراسة.'
            : 'For example, desk work or studying.',
      };
  String get screeningNote => isArabic
      ? 'إذا انطبق أي مما سبق، تحدّث إلى اختصاصي تغذية مسجل قبل تحديد الأهداف.'
      : 'If any apply, speak with a registered dietitian before setting targets.';
  String goalReason(Map<String, dynamic>? reason) => switch (reason?['code']) {
        'current_goal' => isArabic
            ? 'بناءً على هدفك الحالي: ${reason?['goal_text'] ?? ''}'
            : 'Based on your Current goal: ${reason?['goal_text'] ?? ''}',
        'target_weight' => isArabic
            ? 'بناءً على وزنك المستهدف.'
            : 'Based on your Target weight.',
        _ => isArabic
            ? 'الحفاظ على الوزن هو نقطة البداية الافتراضية.'
            : 'Maintain is the default starting point.',
      };
  String get meals => isArabic ? 'الوجبات' : 'Meals';
  String get foodRestrictions => isArabic ? 'القيود الغذائية' : 'Food restrictions';
  String get weight => isArabic ? 'الوزن' : 'Weight';
  String get latest => isArabic ? 'الأحدث' : 'Latest';
  String get target => isArabic ? 'المستهدف' : 'Target';
  String waterPrescription(int ml) => isArabic
      ? '${(ml / 1000).toStringAsFixed(1)} لتر · ${ml ~/ 250} أكواب بسعة 250 مل'
      : '${(ml / 1000).toStringAsFixed(1)} L · ${ml ~/ 250} glasses of 250 ml';
  String get cardioNote => isArabic
      ? 'تظهر تعديلات السعرات الناتجة عن الكارديو ضمن أهدافك اليومية.'
      : 'Cardio calorie adjustments are included in your daily targets.';
  String get fat => isArabic ? 'الدهون' : 'Fat';
  String get fiberTarget => isArabic ? 'هدف الألياف' : 'Fiber target';
  String get waterTarget => isArabic ? 'هدف الماء' : 'Water target';
  String fiberValue(Object value) => isArabic ? '$value جم' : '$value g';
  String get fiberUnit => isArabic ? 'جم' : 'g';
  String get waterUnit => isArabic ? 'مل' : 'ml';
  String waterValue(int ml) => isArabic
      ? '${(ml / 1000).toStringAsFixed(2)} لتر · ${ml ~/ 250} كوبًا'
      : '${(ml / 1000).toStringAsFixed(2)} L · ${ml ~/ 250} glasses';
  String get coachFiber => isArabic ? 'الألياف' : 'Fiber';
  String get coachWater => isArabic ? 'الماء' : 'Water';
  String get macrosTitle => isArabic ? 'الماكروز' : 'Macros';
  String get howTodayWent => isArabic ? 'كيف كان يومك؟' : 'How did today go?';
  String get onTarget => isArabic ? 'على الهدف' : 'On target';
  String get roughly => isArabic ? 'تقريبًا' : 'Roughly';
  String get off => isArabic ? 'بعيد عن الهدف' : 'Off';
  String get lastSevenDays => isArabic ? 'آخر 7 أيام' : 'Last 7 days';
  String get latestWeight => isArabic ? 'أحدث وزن' : 'Latest weight';
  String get targetWeight => isArabic ? 'الوزن المستهدف' : 'Target weight';
  String get setByCoach => isArabic ? 'حدّدها مدربك' : 'Set by your coach';
  String get kilograms => isArabic ? 'كجم' : 'kg';
  String adherenceLabel(String? value) => switch (value) {
        'on_target' => onTarget,
        'roughly' => roughly,
        'off' => off,
        _ => isArabic ? 'غير مسجل' : 'Unlogged',
      };
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';
  String get updateTargets => isArabic ? 'تحديث الأهداف الغذائية' : 'Update Nutrition targets';
  String get adjust => isArabic ? 'تعديل' : 'Adjust';
  String get saveGoal => isArabic ? 'حفظ هدف التغذية' : 'Save Nutrition goal';
  String get weeklyChange => isArabic ? 'التغير الأسبوعي' : 'Weekly change';
  String weeklyRate(double value) {
    final String sign = value < 0 ? '−' : value > 0 ? '+' : '';
    final String amount = value.abs().toStringAsFixed(1);
    return isArabic ? '$sign$amount كجم أسبوعيًا' : '$sign$amount kg a week';
  }
  String formatDate(String value) {
    final DateTime date = DateTime.parse(value);
    if (!isArabic) {
      const List<String> months = <String>[
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ];
      return '${months[date.month - 1]} ${date.day}, ${date.year}';
    }
    const List<String> months = <String>[
      'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
      'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر',
    ];
    return '${date.day} ${months[date.month - 1]} ${date.year}';
  }
  String get reachTarget => isArabic ? 'تاريخ الوصول إلى الوزن المستهدف' : 'Target weight date';
  String get floorWarning => isArabic ? 'يحدّ الحد الأدنى للسعرات من معدل التغير الأسبوعي الفعلي.' : 'The Calorie floor applies; this is your real weekly rate.';
  String get gainWarning => isArabic ? 'وزنك المستهدف أقل من وزنك الحالي.' : 'Your Target weight is below your current weight.';
  String get updateOffer => isArabic ? 'تغير هدفك. هل تريد تحديث هدف التغذية؟' : 'Your goal changed. Update your Nutrition goal?';
  String get accept => isArabic ? 'تحديث' : 'Update';
  String get dismiss => isArabic ? 'لاحقًا' : 'Later';
  String get continueLabel => isArabic ? 'متابعة' : 'Continue';
  String stop(String goalValue, String pace) => '${goal(goalValue)} · ${isArabic ? <String, String>{'light': 'خفيف', 'moderate': 'متوسط', 'aggressive': 'قوي'}[pace] : pace[0].toUpperCase() + pace.substring(1)}';
  String get dietitian => isArabic ? 'لن يحدد ميوس أهدافًا غذائية. يُرجى التحدث إلى اختصاصي تغذية مسجل.' : 'MAYOS will not set calorie targets. Please speak with a registered dietitian.';
  String get under18 => isArabic ? 'لا يحدد ميوس أهدافًا غذائية تلقائية لمن هم دون 18 عامًا.' : 'MAYOS does not set automatic Nutrition targets for players under 18.';
  String get incomplete => isArabic ? 'أكمل الملف التدريبي قبل إعداد الأهداف الغذائية.' : 'Complete your Training profile before setting Nutrition targets.';
  String get coachSetByPlayer => isArabic ? 'حدده اللاعب' : 'Set by player';
  String get coachSetByYou => isArabic ? 'حددته أنت' : 'Set by you';
  String get coachTakeoverTitle => isArabic ? 'تولي أهداف التغذية' : 'Take over Nutrition targets';
  String get coachTakeoverPrompt => isArabic ? 'سيصبح لك حق تعديل أهداف التغذية لهذا اللاعب طوال مدة التعيين.' : 'You will control this Player’s Nutrition targets while the Assignment is active.';
  String get coachConfirmTakeover => isArabic ? 'تولي الأهداف' : 'Take over targets';
  String get coachTargets => isArabic ? 'أهداف التغذية' : 'Nutrition targets';
  String get waterLog => isArabic ? 'سجل الماء' : 'Water log';
  String get waterGlasses => isArabic ? 'أكواب اليوم' : 'Glasses today';
  String get addGlass => isArabic ? '+ كوب' : '+1 glass';
  String get undoGlass => isArabic ? 'تراجع' : 'Undo';
  String get waterUpdateFailed => isArabic ? 'تعذر تحديث سجل الماء' : 'Could not update the Water log';
  String get coachWaterHistory => isArabic ? 'الماء · آخر 14 يومًا' : 'Water · last 14 days';
  String get fiberEaten => isArabic ? 'الألياف المتناولة' : 'Fiber eaten';
  String get coachSaveTargets => isArabic ? 'حفظ الأهداف' : 'Save targets';
  String get coachCalorieFloor => isArabic ? 'الحد الأدنى للسعرات' : 'Calorie floor';
  String get coachTargetCalories => isArabic ? 'السعرات' : 'Calories';
  String get coachUseDayTargets => isArabic ? 'أهداف منفصلة لأيام التدريب والراحة' : 'Separate training-day and rest-day targets';
  String get coachTrainingDay => isArabic ? 'يوم التدريب' : 'Training day';
  String get coachRestDay => isArabic ? 'يوم الراحة' : 'Rest day';
  String get coachAdherence14 => isArabic ? 'الالتزام الغذائي · آخر 14 يومًا' : 'Nutrition adherence · last 14 days';
  String get coachWeightTrend => isArabic ? 'اتجاه الوزن' : 'Weight trend';
  String get coachCharts => isArabic ? 'الرسوم البيانية' : 'Charts';
  String get coachWeightAdherence => isArabic ? 'الوزن والالتزام الغذائي · آخر 28 يومًا' : 'Weight and Nutrition adherence · last 28 days';
  String get coachChartAdherence => isArabic ? 'الالتزام الغذائي · آخر 28 يومًا' : 'Nutrition adherence · last 28 days';
  String get coachChartStart => isArabic ? 'منذ 27 يومًا' : '27 days ago';
  String get coachToday => isArabic ? 'اليوم' : 'Today';
  String coachWeightChange(double first, double last) => isArabic
      ? 'تغير الوزن من ${first.toStringAsFixed(1)} إلى ${last.toStringAsFixed(1)} كجم.'
      : 'Weight changed from ${first.toStringAsFixed(1)} to ${last.toStringAsFixed(1)} kg.';
  String coachPlannedRate(double rate, String date) => isArabic
      ? 'الوتيرة المخططة ${rate.toStringAsFixed(2)}٪ أسبوعيًا بدءًا من $date.'
      : 'Planned pace ${rate.toStringAsFixed(2)}% per week from $date.';
  String coachAdherenceSummary(int onTarget, int roughly, int off) => isArabic
      ? 'الالتزام الغذائي: $onTarget يوم على الهدف، و$roughly يوم تقريبًا، و$off يوم بعيد عن الهدف.'
      : 'Nutrition adherence: $onTarget ${onTarget == 1 ? 'day' : 'days'} on target, $roughly ${roughly == 1 ? 'day' : 'days'} roughly on target and $off ${off == 1 ? 'day' : 'days'} off.';
  String get coachPlannedPace => isArabic ? 'الوتيرة المخططة' : 'Planned pace';
  String get coachNoChartData => isArabic ? 'لا توجد بيانات وزن أو التزام لهذه الفترة.' : 'No weight or adherence data for this period.';
  String get coachChartLoadError => isArabic ? 'تعذر تحميل بيانات الرسم البياني.' : 'Could not load chart data.';
  String get coachNextPaceCheck => isArabic ? 'فحص الوتيرة القادم' : 'Next pace check';
  String get coachPaceCheckPending => isArabic ? 'بعد 21 يومًا من تسجيل الوزن' : 'After 21 days of weigh-ins';
  String get paceProposal => isArabic ? 'اقتراح فحص الوتيرة' : 'Pace check proposal';
  String paceProposalRates(Object? actual, Object? planned) => isArabic
      ? 'الوتيرة الفعلية: ${_signedRate(actual)}٪ · المخططة: ${_signedRate(planned)}٪'
      : 'Actual pace: ${_signedRate(actual)}% · planned: ${_signedRate(planned)}%';
  String paceProposalCalories(Object? calories, Object? change) => isArabic
      ? '$calories سعرة حرارية (${_signedCalories(change)} سعرة)'
      : '$calories kcal (${_signedCalories(change)} kcal)';

  String _signedRate(Object? value) {
    final double? number = value is num ? value.toDouble() : double.tryParse('$value');
    if (number == null) return '$value';
    final String rounded = number.abs().toStringAsFixed(1);
    final String compact = rounded.endsWith('.0') ? rounded.substring(0, rounded.length - 2) : rounded;
    return '${number > 0 ? '+' : number < 0 ? '−' : ''}$compact';
  }

  String _signedCalories(Object? value) {
    final int? number = value is num ? value.toInt() : int.tryParse('$value');
    if (number == null) return '$value';
    return '${number > 0 ? '+' : number < 0 ? '−' : ''}${number.abs()}';
  }
  String get proposalAccept => isArabic ? 'تطبيق' : 'Apply';
  String get proposalKeep => isArabic ? 'الإبقاء على الأهداف' : 'Keep targets';
  String proposalDecision(String? value) => switch (value) {
    'accepted' => isArabic ? 'طُبّق الاقتراح' : 'Proposal accepted',
    'kept' => isArabic ? 'تم الإبقاء على الأهداف' : 'Targets kept',
    _ => isArabic ? 'بانتظار القرار' : 'Decision pending',
  };
  String proposalDecisionBy(String? decision, String? actor) {
    final String person = actor == 'coach'
        ? (isArabic ? 'المدرب' : 'Coach')
        : (isArabic ? 'اللاعب' : 'Player');
    return decision == null || decision == 'pending'
        ? proposalDecision(decision)
        : isArabic ? '${proposalDecision(decision)} · $person'
            : '${decision == 'accepted' ? 'Accepted' : 'Kept'} by $person';
  }
  String get staleProposal => isArabic ? 'تغيرت خطة التغذية؛ لم يعد هذا الاقتراح صالحًا.'
      : 'The Nutrition plan changed; this proposal is stale.';
  String coachPaceCheckValue(String? value) => switch (value) {
    'after_21_days_of_weigh_ins' => coachPaceCheckPending,
    _ => value ?? coachPaceCheckPending,
  };
  String get coachNutritionSaved => isArabic ? 'تم حفظ أهداف التغذية.' : 'Nutrition targets saved.';
  String? coachValidationError(String message) {
    if (message.contains('fiber_g')) return isArabic ? 'الألياف: من 10 إلى 80 جم.' : 'Fiber must be between 10 and 80 g.';
    if (message.contains('water_ml')) return isArabic ? 'الماء: من 1,000 إلى 6,000 مل بخطوات 250 مل.' : 'Water must be 1,000–6,000 ml in 250 ml steps.';
    if (message.contains('Training profile')) {
      return isArabic ? 'أكمل الملف التدريبي للاعب قبل إعداد الأهداف الغذائية.'
          : "Complete the Player's Training profile before setting Nutrition targets.";
    }
    if (message.contains('registered dietitian')) {
      return isArabic ? 'لا يمكن إعداد الأهداف الغذائية؛ يُرجى التحدث مع اختصاصي تغذية مسجل.'
          : 'Nutrition targets are blocked. Please speak with a registered dietitian.';
    }
    if (message.contains('under 18')) {
      return isArabic ? 'لا يمكن إعداد أهداف خسارة الوزن للاعب دون 18 عامًا.'
          : 'Players under 18 may only have Maintain or Gain targets.';
    }
    if (message.contains('Confirm that you are taking over')) {
      return isArabic ? 'أكد تولي مسؤولية أهداف التغذية.'
          : 'Confirm that you are taking over Nutrition authority.';
    }
    if (message.contains('Set Nutrition targets') || message.contains('must include calories')) {
      return isArabic ? 'أدخل أهداف السعرات والماكروز.' : 'Set Nutrition targets with calories and Macros.';
    }
    final RegExpMatch? floor = RegExp(r'floor of (\d+) kcal').firstMatch(message);
    if (floor != null) {
      final String amount = floor.group(1)!;
      return isArabic ? 'يجب ألا تقل السعرات عن الحد الأدنى البالغ $amount.'
          : 'Calories must meet the Calorie floor of $amount kcal.';
    }
    if (message.contains('within 5%')) {
      return isArabic ? 'يجب أن تتوافق سعرات الماكروز مع الهدف ضمن 5٪.'
          : 'Calories from Macros must be within 5% of the target.';
    }
    final RegExpMatch? rate = RegExp(r'not exceed ([\d.]+)%').firstMatch(message);
    if (rate != null) {
      final String amount = rate.group(1)!;
      return isArabic ? 'يجب ألا تتجاوز الوتيرة الأسبوعية $amount٪ من وزن الجسم.'
          : 'The weekly rate must not exceed $amount% of bodyweight.';
    }
    if (message.contains('must be a whole number') || message.contains('valid ')) {
      return isArabic ? 'أدخل السعرات والماكروز كأعداد صحيحة غير سالبة.'
          : 'Enter calories and Macros as whole numbers; Macro values cannot be negative.';
    }
    return null;
  }
  String get coachGoal => isArabic ? 'هدف التغذية' : 'Nutrition goal';
  String get coachMacroCalories => isArabic ? 'السعرات المحسوبة من الماكروز' : 'Calories from Macros';
  String coachWeightValue(String date, Object weight) => isArabic
      ? '\u2066$date · $weight\u2069 كجم' : '$date · $weight kg';
  String goal(String value) => isArabic
      ? <String, String>{'lose': 'خسارة الوزن', 'gain': 'زيادة الوزن', 'maintain': 'الحفاظ على الوزن'}[value] ?? value
      : value[0].toUpperCase() + value.substring(1);
}
