import 'food_log_copy.dart';

class MealSetupCopy extends FoodLogCopy {
  const MealSetupCopy(super.languageCode);

  static const List<String> allergens = <String>[
    'milk', 'eggs', 'wheat_gluten', 'peanuts', 'tree_nuts', 'fish', 'shellfish', 'sesame', 'soy',
  ];
  String get mealSetup => isArabic ? 'إعداد الوجبات' : 'Meal setup';
  String get mealCount => isArabic ? 'عدد الوجبات' : 'Meals per day';
  String get trainingTime => isArabic ? 'وقت التدريب المعتاد' : 'Usual training time';
  String get restrictions => isArabic ? 'القيود الغذائية' : 'Food restrictions';
  String get allergies => isArabic ? 'الحساسية الغذائية' : 'Food allergies';
  String get allergyNote => isArabic
    ? 'تعتمد التنبيهات على مسببات الحساسية المراجعة؛ قد لا تتوفر معلومات لكل طعام، لذا تحقق من مكوناته.'
    : 'Warnings use reviewed allergen tags; information may be missing for some foods, so check their ingredients.';
  String get vegetarian => isArabic ? 'نظام نباتي' : 'Vegetarian';
  String get vegetarianNote => isArabic ? 'استبعاد اللحوم والدواجن والأسماك من الاقتراحات.'
    : 'Exclude meat, poultry and fish from suggestions.';
  String get dislikes => isArabic ? 'أطعمة لا تفضلها' : 'Disliked foods';
  String get addDislike => isArabic ? 'اختر طعامًا لا تفضله' : 'Choose a disliked food';
  String get restricted => isArabic ? 'طعام مقيّد' : 'Restricted food';
  String get remove => isArabic ? 'إزالة' : 'Remove';
  String timeLabel(String time) => switch (time) {
    'morning' => isArabic ? 'صباحًا' : 'Morning',
    'afternoon' => isArabic ? 'بعد الظهر' : 'Afternoon',
    _ => isArabic ? 'مساءً' : 'Evening',
  };
  String reason(String tag) => switch (tag) {
    'milk' => isArabic ? 'الحليب' : 'Milk',
    'eggs' => isArabic ? 'البيض' : 'Eggs',
    'wheat_gluten' => isArabic ? 'القمح / الغلوتين' : 'Wheat / gluten',
    'peanuts' => isArabic ? 'الفول السوداني' : 'Peanuts',
    'tree_nuts' => isArabic ? 'المكسرات' : 'Tree nuts',
    'fish' => isArabic ? 'الأسماك' : 'Fish',
    'shellfish' => isArabic ? 'المحار والقشريات' : 'Shellfish',
    'sesame' => isArabic ? 'السمسم' : 'Sesame',
    'soy' => isArabic ? 'الصويا' : 'Soy',
    'vegetarian' => isArabic ? 'غير مناسب للنظام النباتي' : 'Not vegetarian',
    'disliked' => isArabic ? 'طعام لا تفضله' : 'Disliked',
    _ => tag,
  };
  String slotLayout(int count) => <String>[
    mealLabel('breakfast'), if (count == 5) mealLabel('morning_snack'),
    mealLabel('lunch'), if (count >= 4) mealLabel('afternoon_snack'), mealLabel('dinner'),
  ].join(' · ');
}
