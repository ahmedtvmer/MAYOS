import 'meal_setup_copy.dart';

class FoodSwapCopy extends MealSetupCopy {
  const FoodSwapCopy(super.languageCode);

  String get swap => isArabic ? 'تبديل الطعام' : 'Swap food';
  String get permanent => isArabic
    ? 'يغيّر هذا الطعام في هذه الوجبة في خطتك لأيام التدريب والراحة. تسجيل ما تأكله لا يغيّر الخطة.'
    : 'Changes this food in this Meal slot in your plan for training and rest days. Logging what you eat does not change the plan.';
  String get nextStaples => isArabic ? 'الأطعمة الأساسية التالية' : 'Next Staple foods';
  String get searchResults => isArabic ? 'نتائج البحث' : 'Search results';
  String get searchHint => isArabic ? 'أو ابحث عن طعام آخر' : 'Or search for another food';
  String get noStaples => isArabic ? 'لا توجد بدائل أساسية مناسبة؛ ابحث عن طعام آخر.'
    : 'No suitable Staple alternatives; search for another food.';
  String get unavailableSwap => isArabic ? 'لا يمكن استخدام هذا الطعام في تبديل الطعام في الخطة.'
    : 'This food cannot be used for a Food swap.';
  String get saveSwap => isArabic ? 'حفظ التبديل في الخطة' : 'Save Food swap';
  String get saved => isArabic ? 'حُفظ تبديل الطعام في خطتك.' : 'Food swap saved in your plan.';
  String preview(double grams, double calories, double protein) => isArabic
    ? '${grams.toStringAsFixed(1)} غ · إجمالي الوجبة: ${calories.round()} سعرة · ${protein.toStringAsFixed(1)} غ بروتين'
    : '${grams.toStringAsFixed(1)} g · Meal total: ${calories.round()} kcal · ${protein.toStringAsFixed(1)} g protein';
}
