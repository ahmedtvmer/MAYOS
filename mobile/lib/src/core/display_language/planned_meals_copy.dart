class PlannedMealsCopy {
  const PlannedMealsCopy(this.language);
  final String language;
  bool get arabic => language == 'ar';
  String get title => arabic ? 'وجبات اليوم' : "Today's meals";
  String get turnOn => arabic ? 'تفعيل الوجبات' : 'Turn on meals';
  String get introduction => arabic
    ? 'وجبات من أطعمة أساسية بحصص عملية تناسب أهدافك وقيودك الغذائية.'
    : 'Staple foods in practical portions for your targets and Food restrictions.';
  String get unavailable => arabic
    ? 'الوجبات غير متاحة بعد. نحتاج إلى أطعمة أساسية معتمدة تناسب قيودك الغذائية وأهدافك.'
    : "Meals aren't available yet. We need reviewed Staple foods that fit your restrictions and targets.";
  String get targetsNeeded => arabic ? 'أعدّ الأهداف الغذائية أولًا.' : 'Set up Nutrition targets first.';
  String get log => arabic ? 'تسجيل هذه الوجبة' : 'Log this meal';
  String get logged => arabic ? 'أُضيفت الوجبة إلى سجل الطعام.' : 'Meal added to your Food log.';
  String get coach => arabic ? 'حددها مدربك' : 'Set by your coach';
  String get targetsChanged => arabic ? 'تغيّرت الأهداف؛ الوجبات بانتظار تحديث مدربك.'
    : 'Targets changed; your coach needs to update these meals.';
  String get setup => arabic ? 'إعداد الوجبات والقيود الغذائية' : 'Meal setup and Food restrictions';
  String get retry => arabic ? 'إعادة المحاولة' : 'Retry';
  String get trainingDay => arabic ? 'يوم تدريب' : 'Training day';
  String get restDay => arabic ? 'يوم راحة' : 'Rest day';
  String slot(String slot) => switch (slot) {
    'breakfast' => arabic ? 'الإفطار' : 'Breakfast',
    'morning_snack' => arabic ? 'وجبة خفيفة صباحًا' : 'Morning snack',
    'lunch' => arabic ? 'الغداء' : 'Lunch',
    'afternoon_snack' => arabic ? 'وجبة خفيفة عصرًا' : 'Afternoon snack',
    _ => arabic ? 'العشاء' : 'Dinner',
  };
  String amount(double grams) => '${grams.toStringAsFixed(grams == grams.roundToDouble() ? 0 : 1)} ${arabic ? 'غ' : 'g'}';
  String calories(double calories) => '${calories.round()} ${arabic ? 'سعرة' : 'kcal'}';
}
