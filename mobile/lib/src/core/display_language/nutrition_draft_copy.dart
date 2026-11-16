import 'nutrition_copy.dart';

class NutritionDraftCopy {
  const NutritionDraftCopy(this.language);
  final String language;
  bool get arabic => language == 'ar';
  String text(String en, String ar) => arabic ? ar : en;
  String get title => text('Nutrition plan draft', 'مسودة خطة تغذية');
  String get open => text('Write Nutrition plan', 'كتابة خطة تغذية');
  String get addMeal => text('Add Meal slot', 'إضافة وجبة');
  String get addFood => text('Add Staple food', 'إضافة طعام أساسي');
  String get publish => text('Publish Nutrition plan', 'نشر خطة التغذية');
  String get saved => text('All changes saved', 'تم حفظ كل التغييرات');
  String get saving => text('Saving…', 'جارٍ الحفظ…');
  String get retry => text('Retry save', 'إعادة محاولة الحفظ');
  String day(String day) => switch (day) {
    'training_day' => text('Training day', 'يوم تدريب'),
    'rest_day' => text('Rest day', 'يوم راحة'),
    _ => text('Daily', 'يوميًا'),
  };
  String nutrient(String key) => switch (key) {
    'calories' => text('Calories', 'السعرات'),
    'protein_g' => text('Protein (g)', 'البروتين (غ)'),
    'carbs_g' => text('Carbs (g)', 'الكربوهيدرات (غ)'),
    _ => text('Fat (g)', 'الدهون (غ)'),
  };
  String issue(String issue) {
    if (!arabic) return issue;
    final String? targetIssue = NutritionCopy(language).coachValidationError(issue);
    if (targetIssue != null) return targetIssue;
    if (issue.contains('15%')) return 'يجب أن تكون إجماليات كل يوم ضمن ١٥٪ من كل هدف.';
    if (issue.contains('Calorie floor')) return 'سعرات الوجبات أقل من الحد الأدنى للسعرات.';
    if (issue.contains('restriction') || issue.contains('allergen')) {
      return 'يوجد تعارض مع الحساسية أو النظام النباتي، أو معلومات حساسية غير معتمدة.';
    }
    if (issue.contains('Staple')) return 'استخدم أطعمة أساسية معتمدة فقط.';
    if (issue.contains('food') || issue.contains('Food')) return 'راجع الأطعمة والجرامات في كل وجبة.';
    return 'راجع أهداف المسودة والوجبات قبل النشر.';
  }
}
