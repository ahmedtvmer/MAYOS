import 'food_log_copy.dart';

class CoachFoodLogCopy extends FoodLogCopy {
  const CoachFoodLogCopy(super.languageCode);

  String get targetsView => isArabic ? 'الأهداف' : 'Targets';
  String get foodLogFood => isArabic ? 'الطعام' : 'Food';
  String get personalFood => isArabic ? 'طعام خاص' : 'Personal food';
  String get quickAdd => isArabic ? 'إضافة سريعة' : 'Quick add';
  String get computed => isArabic ? 'محسوب من السجل' : 'Computed from log';
  String get answered => isArabic ? 'إجابة اللاعب' : 'Answered';
  String get dayTotal => isArabic ? 'إجمالي اليوم' : 'Day total';
  String get totalTarget => isArabic ? 'إجمالي اليوم · الهدف' : 'Day total · target';
  String get over => isArabic ? 'فوق الهدف' : 'Over';
  String get short => isArabic ? 'دون الهدف' : 'Short';
  String get atTarget => isArabic ? 'على الهدف' : 'On target';
}
