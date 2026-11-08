class PlannedMealsCopy {
  const PlannedMealsCopy(this.language);
  final String language;
  bool get arabic => language == 'ar';
  String get title => arabic ? 'الوجبات المخططة' : 'Planned meals';
  String get loggedLabel => arabic ? '??????' : 'Logged';
  String logMeal(String name) => arabic ? '????? $name' : 'Log $name';
  String showMore(int count) =>
      arabic ? '??? $count ????? ????' : 'Show $count more meals';
  String get turnOn => arabic ? 'تفعيل الوجبات' : 'Turn on meals';
  String get introduction => arabic
      ? 'وجبات من أطعمة أساسية بحصص عملية تراعي قيودك الغذائية؛ إذا تعذر الاقتراب من الأهداف ضمن ٥٪، نعرض أقرب وجبة والفرق عن هدف كل وجبة.'
      : 'Staple foods in practical portions that respect your Food restrictions; if no meal fits within 5%, we show the closest meal and its difference from each slot target.';
  String get unavailable => arabic
      ? 'الوجبات غير متاحة بعد. نحتاج إلى أطعمة أساسية معتمدة ذات بيانات غذائية كاملة تسمح بها قيودك الغذائية.'
      : "Meals aren't available yet. We need reviewed Staple foods with complete nutrients that your Food restrictions allow.";
  String get targetsNeeded => arabic
      ? 'أعدّ الأهداف الغذائية أولًا.'
      : 'Set up Nutrition targets first.';
  String get coachTargetsOnly => arabic
      ? 'حدد مدربك الأهداف فقط؛ لا توجد وجبات في هذه الخطة.'
      : 'Your coach set targets only; this plan has no meals.';
  String get log => arabic ? 'تسجيل هذه الوجبة' : 'Log this meal';
  String get logged =>
      arabic ? 'أُضيفت الوجبة إلى سجل الطعام.' : 'Meal added to your Food log.';
  String get coach => arabic ? 'حددها مدربك' : 'Set by your coach';
  String get targetsChanged => arabic
      ? 'تغيّرت الأهداف؛ الوجبات بانتظار تحديث مدربك.'
      : 'Targets changed; your coach needs to update these meals.';
  String get setup => arabic
      ? 'إعداد الوجبات والقيود الغذائية'
      : 'Meal setup and Food restrictions';
  String get retry => arabic ? 'إعادة المحاولة' : 'Retry';
  String get trainingDay => arabic ? 'يوم تدريب' : 'Training day';
  String get restDay => arabic ? 'يوم راحة' : 'Rest day';
  String deviation(Map<String, double> amounts) {
    final Map<String, String> labels = <String, String>{
      'calories': arabic ? 'السعرات' : 'Calories',
      'protein_g': arabic ? 'البروتين' : 'protein',
      'carbs_g': arabic ? 'الكربوهيدرات' : 'carbs',
      'fat_g': arabic ? 'الدهون' : 'fat',
    };
    final String differences = labels.entries
        .where((entry) => amounts.containsKey(entry.key))
        .map((entry) {
      final double amount = amounts[entry.key]!;
      final String unit = entry.key == 'calories'
          ? (arabic ? 'سعرة' : 'kcal')
          : (arabic ? 'غ' : 'g');
      return '${entry.value} ${amount >= 0 ? '+' : ''}${amount.toStringAsFixed(1)} $unit';
    }).join(arabic ? '، ' : ', ');
    return arabic
        ? 'فرق الحصص العملية عن هدف الوجبة: $differences.'
        : 'Practical portions compared with the meal target: $differences.';
  }

  String slot(String slot) => switch (slot) {
        'breakfast' => arabic ? 'الإفطار' : 'Breakfast',
        'morning_snack' => arabic ? 'وجبة خفيفة صباحًا' : 'Morning snack',
        'lunch' => arabic ? 'الغداء' : 'Lunch',
        'afternoon_snack' => arabic ? 'وجبة خفيفة عصرًا' : 'Afternoon snack',
        'dinner' => arabic ? 'العشاء' : 'Dinner',
        _ => arabic ? 'وجبة' : 'Meal',
      };
  String amount(double grams) =>
      '${grams.toStringAsFixed(grams == grams.roundToDouble() ? 0 : 1)} ${arabic ? 'غ' : 'g'}';
  String calories(double calories) =>
      '${calories.round()} ${arabic ? 'سعرة' : 'kcal'}';
}
