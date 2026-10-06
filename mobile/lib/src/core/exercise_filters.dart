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

class PrimaryAction {
  const PrimaryAction(this.apiValue, this.arabicLabel);

  final String apiValue;
  final String arabicLabel;
}

const List<PrimaryAction> primaryActions = <PrimaryAction>[
  PrimaryAction('Shoulder Flexion', 'ثني الكتف'),
  PrimaryAction('Shoulder Extension', 'بسط الكتف'),
  PrimaryAction('Shoulder Abduction', 'إبعاد الكتف'),
  PrimaryAction('Shoulder Adduction', 'تقريب الكتف'),
  PrimaryAction('Shoulder Horizontal Adduction', 'التقريب الأفقي للكتف'),
  PrimaryAction('Shoulder Horizontal Abduction', 'الإبعاد الأفقي للكتف'),
  PrimaryAction('Shoulder External Rotation', 'الدوران الخارجي للكتف'),
  PrimaryAction('Shoulder Internal Rotation', 'الدوران الداخلي للكتف'),
  PrimaryAction('Scapular Elevation', 'رفع لوح الكتف'),
  PrimaryAction('Scapular Retraction', 'تقريب لوحي الكتف'),
  PrimaryAction('Scapular Depression', 'خفض لوح الكتف'),
  PrimaryAction('Scapular Protraction', 'إبعاد لوحي الكتف'),
  PrimaryAction('Elbow Flexion', 'ثني المرفق'),
  PrimaryAction('Elbow Extension', 'بسط المرفق'),
  PrimaryAction('Wrist Flexion', 'ثني الرسغ'),
  PrimaryAction('Wrist Extension', 'بسط الرسغ'),
  PrimaryAction('Spinal Flexion', 'ثني العمود الفقري'),
  PrimaryAction('Spinal Extension', 'بسط العمود الفقري'),
  PrimaryAction('Spinal Rotation', 'دوران العمود الفقري'),
  PrimaryAction('Spinal Lateral Flexion', 'الانثناء الجانبي للعمود الفقري'),
  PrimaryAction('Anti-Extension', 'مقاومة بسط الجذع'),
  PrimaryAction('Anti-Rotation', 'مقاومة دوران الجذع'),
  PrimaryAction('Anti-Lateral Flexion', 'مقاومة الانثناء الجانبي للجذع'),
  PrimaryAction('Hip Flexion', 'ثني الورك'),
  PrimaryAction('Hip Extension', 'بسط الورك'),
  PrimaryAction('Hip Abduction', 'إبعاد الورك'),
  PrimaryAction('Hip Adduction', 'تقريب الورك'),
  PrimaryAction('Knee Flexion', 'ثني الركبة'),
  PrimaryAction('Knee Extension', 'بسط الركبة'),
  PrimaryAction('Ankle Plantar Flexion', 'العطف الأخمصي للكاحل'),
  PrimaryAction('Ankle Dorsiflexion', 'العطف الظهري للكاحل'),
  PrimaryAction('Neck Flexion', 'ثني الرقبة'),
  PrimaryAction('Neck Extension', 'بسط الرقبة'),
  PrimaryAction('Conditioning', 'اللياقة البدنية'),
];

class ExerciseFilterState {
  const ExerciseFilterState({
    this.primaryMuscles = const <String>[],
    this.primaryActions = const <String>[],
  });

  final List<String> primaryMuscles;
  final List<String> primaryActions;

  bool get hasCuratedFilters =>
      primaryMuscles.isNotEmpty || primaryActions.isNotEmpty;

  ExerciseFilterState copyWith({
    List<String>? primaryMuscles,
    List<String>? primaryActions,
  }) =>
      ExerciseFilterState(
        primaryMuscles: primaryMuscles ?? this.primaryMuscles,
        primaryActions: primaryActions ?? this.primaryActions,
      );
}
