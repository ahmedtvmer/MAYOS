class ProgramChangeCopy {
  const ProgramChangeCopy(this.languageCode);

  final String languageCode;

  bool get isArabic => languageCode == 'ar';

  String get approvedAsIs => isArabic
      ? 'وافق مدربك على برنامجك التدريبي الحالي.'
      : 'Your coach approved your current program.';

  String get heading => isArabic ? 'تغييرات البرنامج التدريبي' : 'Program changes';

  String get viewProgram => isArabic ? 'عرض البرنامج التدريبي' : 'View program';

  String get dismiss => isArabic ? 'إخفاء' : 'Dismiss';

  String andMore(int count) => isArabic
      ? 'والمزيد من التغييرات: $count'
      : 'and $count more';

  String line(Map<String, dynamic> change) {
    final String type = change['type'] as String? ?? '';
    final String day = change['day'] as String? ?? '';
    return switch (type) {
      'day_added' => isArabic ? 'تمت إضافة يوم: $day' : 'Day added: $day',
      'day_removed' => isArabic ? 'تمت إزالة يوم: $day' : 'Day removed: $day',
      'day_renamed' => _renamedDay(change),
      'exercise_added' => isArabic
          ? 'تمت إضافة ${change['exercise']} في $day'
          : 'Added ${change['exercise']} on $day',
      'exercise_removed' => isArabic
          ? 'تمت إزالة ${change['exercise']} من $day'
          : 'Removed ${change['exercise']} from $day',
      'exercise_replaced' => _replacedExercise(change, day),
      'prescription_changed' => _prescription(change),
      _ => '',
    };
  }

  String _renamedDay(Map<String, dynamic> change) {
    final String before = change['before'] as String? ?? '';
    final String after = change['after'] as String? ?? '';
    return isArabic
        ? 'تغيير اسم اليوم: $before ← $after'
        : 'Day renamed: $before → $after';
  }

  String _replacedExercise(Map<String, dynamic> change, String day) {
    final String before = change['before'] as String? ?? '';
    final String after = change['after'] as String? ?? '';
    return isArabic
        ? 'استبدال $before بـ $after في $day'
        : '$before → $after on $day';
  }

  String _prescription(Map<String, dynamic> change) {
    final String exercise = change['exercise'] as String? ?? '';
    final String day = change['day'] as String? ?? '';
    final Map<String, dynamic> fields =
        change['fields'] as Map<String, dynamic>? ?? <String, dynamic>{};
    final List<String> labels = <String>[
      for (final String field in <String>[
        'sets',
        'warmup_sets',
        'reps',
        'rir',
        'rest_seconds',
      ])
        if (fields[field] is Map<String, dynamic>)
          _field(field, fields[field] as Map<String, dynamic>),
    ];
    final String prescriptions = labels.join(isArabic ? '، ' : ', ');
    return '$exercise ($day): $prescriptions';
  }

  String _field(String field, Map<String, dynamic> values) {
    final String label = switch (field) {
      'sets' => isArabic ? 'المجموعات' : 'sets',
      'warmup_sets' => isArabic ? 'مجموعات الإحماء' : 'warm-up sets',
      'reps' => isArabic ? 'التكرارات' : 'reps',
      'rir' => 'RIR',
      'rest_seconds' => isArabic ? 'الراحة' : 'rest',
      _ => field,
    };
    final String before = _fieldValue(field, values['before']);
    final String after = _fieldValue(field, values['after']);
    return '$label $before → $after';
  }

  String _fieldValue(String field, dynamic value) => field != 'rest_seconds'
      ? '$value'
      : isArabic
          ? '$value ثانية'
          : '${value}s';
}
