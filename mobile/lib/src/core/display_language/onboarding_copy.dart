import 'arabic_count.dart';

/// Hand-written labels for app-owned onboarding questions and choices.
/// Intake explanations, hints, examples, and option descriptions come from the
/// server and are rendered without modification.
class OnboardingCopy {
  const OnboardingCopy(this.languageCode);
  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String question(String field, {String? serverLabel}) => switch (field) {
        'gender' => isArabic
            ? 'أي تخصص تريد أن يوجّه تدريبك؟'
            : 'Which specialization should shape your training?',
        'proportions' => isArabic
            ? 'أي وصف يناسب نسب جسمك؟'
            : 'Which best describes your body proportions?',
        'age' => isArabic ? 'كم عمرك؟' : 'How old are you?',
        'height_cm' => isArabic ? 'ما طولك؟' : 'How tall are you?',
        'weight_kg' => isArabic ? 'ما وزنك؟' : 'What do you weigh?',
        'training_age_years' =>
          isArabic ? 'منذ متى وأنت تتدرب؟' : 'How long have you been training?',
        'current_goal' => isArabic
            ? 'ما هدفك الأساسي الآن؟'
            : "What's your main goal right now?",
        'long_term_goal' => isArabic
            ? 'ما هدفك على المدى الطويل؟'
            : 'Where do you want to be long term?',
        'weekly_frequency' => isArabic
            ? 'كم يومًا في الأسبوع يمكنك التدريب؟'
            : 'How many days a week can you train?',
        'equipment_access' =>
          isArabic ? 'ما المعدات المتاحة لك؟' : 'What can you train with?',
        'injuries_or_limitations' => isArabic
            ? 'هل هناك إصابة أو أمر يجب مراعاته؟'
            : 'Anything to work around?',
        'stress_and_sleep' =>
          isArabic ? 'كيف هو تعافيك؟' : "How's your recovery?",
        'rep_preference' => isArabic
            ? 'ما نطاق التكرارات الذي تفضله؟'
            : 'What rep range do you prefer?',
        _ => serverLabel ?? (isArabic ? 'السؤال' : 'Question'),
      };

  /// Localized copy for the enumerated onboarding choices owned by the app.
  /// Returns null for API-provided choices so the widget can render its server
  /// label directly without routing arbitrary text through this catalog.
  String? option(String field, String value) => switch ((field, value)) {
        ('gender', 'male') => isArabic ? 'ذكر' : 'Male',
        ('gender', 'female') => isArabic ? 'أنثى' : 'Female',
        ('proportions', 'long_legs') =>
          isArabic ? 'الساقان أطول من الجذع' : 'Legs longer than torso',
        ('proportions', 'long_torso') =>
          isArabic ? 'الجذع أطول من الساقين' : 'Torso longer than legs',
        ('proportions', 'balanced') ||
        ('rep_preference', 'balanced') =>
          isArabic ? 'متوازن' : 'Balanced',
        ('equipment_access', 'Commercial gym') =>
          isArabic ? 'صالة رياضية تجارية' : 'Commercial gym',
        ('equipment_access', 'Home gym') =>
          isArabic ? 'معدات منزلية' : 'Home gym',
        ('equipment_access', 'Bodyweight only') =>
          isArabic ? 'وزن الجسم فقط' : 'Bodyweight only',
        ('rep_preference', 'low') => isArabic ? 'منخفض' : 'Low',
        ('rep_preference', 'high') => isArabic ? 'مرتفع' : 'High',
        _ => null,
      };

  String get unknownOption => isArabic ? 'خيار' : 'Option';

  String reviewLabel(String field, {String? serverLabel}) => switch (field) {
        'gender' => isArabic ? 'التخصص' : 'Specialization',
        'proportions' => isArabic ? 'نسب الجسم' : 'Proportions',
        'age' => isArabic ? 'العمر' : 'Age',
        'height_cm' => isArabic ? 'الطول' : 'Height',
        'weight_kg' => isArabic ? 'الوزن' : 'Weight',
        'training_age_years' => isArabic ? 'سنوات التدريب' : 'Training age',
        'current_goal' => isArabic ? 'الهدف الحالي' : 'Current goal',
        'long_term_goal' => isArabic ? 'الهدف طويل المدى' : 'Long-term goal',
        'weekly_frequency' =>
          isArabic ? 'عدد أيام التدريب أسبوعيًا' : 'Weekly frequency',
        'equipment_access' => isArabic ? 'المعدات' : 'Equipment',
        'injuries_or_limitations' =>
          isArabic ? 'الإصابات أو القيود' : 'Injuries or limitations',
        'stress_and_sleep' => isArabic ? 'التوتر والنوم' : 'Stress and sleep',
        'rep_preference' => isArabic ? 'تفضيل التكرارات' : 'Rep preference',
        _ => serverLabel ?? (isArabic ? 'السؤال' : 'Question'),
      };

  String? unitFor(String fieldName) => switch (fieldName) {
        'height_cm' => 'cm',
        'weight_kg' => 'kg',
        'age' || 'training_age_years' => isArabic ? 'سنوات' : 'years',
        _ => null,
      };

  String yearsValue(String number) {
    final num? numericValue = num.tryParse(number);
    if (!isArabic || numericValue == null) return '$number ${unitFor('age')}';
    if (numericValue == numericValue.roundToDouble()) {
      return arabicCountPhrase(
        numericValue.round(),
        ArabicCountNoun.year,
      );
    }
    return '$number سنة';
  }

  String frequencyAnswer(int days) => isArabic
      ? '${arabicCountPhrase(days, ArabicCountNoun.day)} في الأسبوع'
      : '$days ${days == 1 ? 'day' : 'days'}/week';

  String numericRangeHint(int minimum, int maximum) =>
      isArabic ? '$minimum إلى $maximum' : '$minimum to $maximum';

  String get notAnswered => isArabic ? 'لم تتم الإجابة' : 'Not answered';
}
