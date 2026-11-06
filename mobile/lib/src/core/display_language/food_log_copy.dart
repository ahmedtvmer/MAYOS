import 'nutrition_copy.dart';

class FoodLogCopy extends NutritionCopy {
  const FoodLogCopy(super.languageCode);

  String get foodLog => isArabic ? 'سجل الطعام' : 'Food log';
  String get quickAdd => isArabic ? 'إضافة سريعة' : 'Quick add';
  String get createPersonal => isArabic ? 'إنشاء طعام خاص' : 'Create a Personal food';
  String get cantFind => isArabic ? 'لم تجد ما تبحث عنه؟' : "Can't find it?";
  String get foodName => isArabic ? 'اسم الطعام' : 'Food name';
  String get nutrientBasis => isArabic ? 'القيم الغذائية لكل' : 'Nutrients per';
  String get hundredGrams => isArabic ? '١٠٠ جرام' : '100 g';
  String get portion => isArabic ? 'حصة' : 'Portion';
  String get portionName => isArabic ? 'اسم الحصة' : 'Portion name';
  String get portionWeight => isArabic ? 'وزن الحصة بالجرام' : 'Portion grams';
  String get optionalMacros => isArabic ? 'المغذيات الكبرى (اختياري)' : 'Macros (optional)';
  String get invalidNutrients => isArabic
      ? 'أدخل قيمًا صحيحة غير سالبة وأكمل الحقول المطلوبة.'
      : 'Enter valid nonnegative values and complete the required fields.';
  String get copyMeal => isArabic ? 'نسخ وجبة من أمس' : 'Copy a meal from yesterday';
  String get copying => isArabic ? 'جارٍ النسخ…' : 'Copying…';
  String get searchFoods => isArabic ? 'ابحث عن طعام' : 'Search foods';
  String get addFood =>
      isArabic ? 'أضف طعامًا، مثل «فول»' : 'Add food, e.g. “فول”';
  String get close => isArabic ? 'إغلاق' : 'Close';
  String get previousDay => isArabic ? 'اليوم السابق' : 'Previous day';
  String get nextDay => isArabic ? 'اليوم التالي' : 'Next day';
  String get today => isArabic ? 'اليوم' : 'Today';
  String get yesterday => isArabic ? 'أمس' : 'Yesterday';
  String get readOnly =>
      isArabic ? 'هذا اليوم للقراءة فقط' : 'This day is read-only';
  String get noEntries => isArabic
      ? 'لا يوجد طعام مسجل لهذا اليوم.'
      : 'No food logged for this day.';
  String get recentFoods =>
      isArabic ? 'أطعمتك الأخيرة والمتكررة' : 'Recent and frequent foods';
  String get noRecent => isArabic
      ? 'ابحث عن طعام لبدء سجل الطعام.'
      : 'Search for a food to start your Food log.';
  String get noResults =>
      isArabic ? 'لا توجد أطعمة مطابقة.' : 'No matching foods.';
  String get staple => isArabic ? 'أساسي' : 'Staple';
  String get recipe => isArabic ? 'وصفة' : 'Recipe';
  String get grams => isArabic ? 'جرام' : 'g';
  String get amount => isArabic ? 'الكمية' : 'Amount';
  String get unit => isArabic ? 'الوحدة' : 'Unit';
  String get meal => isArabic ? 'الوجبة' : 'Meal';
  String get add => isArabic ? 'إضافة' : 'Add';
  String get edit => isArabic ? 'تعديل الطعام' : 'Edit food';
  String get save => isArabic ? 'حفظ' : 'Save';
  String get delete => isArabic ? 'حذف' : 'Delete';
  String get deleteTitle => isArabic ? 'حذف هذا الطعام؟' : 'Delete this food?';
  String get invalidAmount => isArabic
      ? 'أدخل كمية أكبر من صفر وحتى ١٠٬٠٠٠ جرام.'
      : 'Enter an amount above zero and at most 10,000 g.';
  String get afterAdding =>
      isArabic ? 'السعرات المتبقية بعد الإضافة' : 'kcal left after adding';
  String get afterSaving =>
      isArabic ? 'السعرات المتبقية بعد الحفظ' : 'kcal left after saving';
  String get targetsTitle =>
      isArabic ? 'الأهداف الغذائية' : 'Nutrition targets';
  String mealLabel(String value) => switch (value) {
    'breakfast' => isArabic ? 'الإفطار' : 'Breakfast',
    'lunch' => isArabic ? 'الغداء' : 'Lunch',
    'dinner' => isArabic ? 'العشاء' : 'Dinner',
    _ => isArabic ? 'وجبة خفيفة' : 'Snack',
  };
  String addTo(String meal) =>
      isArabic ? 'إضافة إلى ${mealLabel(meal)}' : 'Add to ${mealLabel(meal)}';
  String leftOf(num target) => isArabic
      ? 'سعرة متبقية من ${target.round()}'
      : 'kcal left of ${target.round()}';
  String macroLeft(String macro) => isArabic ? '$macro المتبقي' : '$macro left';
  String per100g(num kcal) => isArabic
      ? '${kcal.round()} سعرة / ١٠٠ جرام'
      : '${kcal.round()} kcal / 100 g';
  String proteinDetail(num value) => isArabic
      ? '${value.round()} جرام بروتين لكل ١٠٠ جرام'
      : '${value.round()} g protein per 100 g';
  String loggedTimes(int value) =>
      isArabic ? 'مسجل $value مرة' : 'Logged $value times';
  String amountLabel(double quantity, String unit, String? portionLabel) =>
      '${quantity == quantity.roundToDouble() ? quantity.toInt() : quantity} ${unit == 'portion' ? portionLabel ?? grams : grams}';
}
