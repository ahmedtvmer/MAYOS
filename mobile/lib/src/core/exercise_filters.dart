class PrimaryMuscle {
  const PrimaryMuscle(this.apiValue, this.arabicLabel);

  final String apiValue;
  final String arabicLabel;
}

const List<PrimaryMuscle> primaryMuscles = <PrimaryMuscle>[
  PrimaryMuscle('Chest', 'الصدر'),
  PrimaryMuscle('Upper Chest', 'أعلى الصدر'),
  PrimaryMuscle('Front Delts', 'الكتف الأمامي'),
  PrimaryMuscle('Side Delts', 'الكتف الجانبي'),
  PrimaryMuscle('Rear Delts', 'الكتف الخلفي'),
  PrimaryMuscle('Lats', 'العضلات الظهرية العريضة'),
  PrimaryMuscle('Upper Back', 'أعلى الظهر'),
  PrimaryMuscle('Traps', 'العضلة شبه المنحرفة'),
  PrimaryMuscle('Lower Back', 'أسفل الظهر'),
  PrimaryMuscle('Biceps', 'العضلة ذات الرأسين'),
  PrimaryMuscle('Triceps', 'العضلة ثلاثية الرؤوس'),
  PrimaryMuscle('Forearms', 'الساعد'),
  PrimaryMuscle('Abs', 'عضلات البطن'),
  PrimaryMuscle('Obliques', 'العضلات المائلة'),
  PrimaryMuscle('Quads', 'العضلة رباعية الرؤوس'),
  PrimaryMuscle('Hamstrings', 'عضلات الفخذ الخلفية'),
  PrimaryMuscle('Glutes', 'عضلات الألوية'),
  PrimaryMuscle('Adductors', 'العضلات المقربة'),
  PrimaryMuscle('Abductors', 'العضلات المبعدة'),
  PrimaryMuscle('Calves', 'عضلات الساق'),
  PrimaryMuscle('Neck', 'الرقبة'),
  PrimaryMuscle('Cardio', 'تمارين القلب'),
];

class ExerciseFilterState {
  const ExerciseFilterState({this.primaryMuscles = const <String>[]});

  final List<String> primaryMuscles;

  bool get hasCuratedFilters => primaryMuscles.isNotEmpty;

  ExerciseFilterState copyWith({List<String>? primaryMuscles}) =>
      ExerciseFilterState(
        primaryMuscles: primaryMuscles ?? this.primaryMuscles,
      );
}
