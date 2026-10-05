import 'arabic_count.dart';

class MessageCopy {
  const MessageCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get unavailable =>
      isArabic ? 'تعذر عرض الرسالة.' : 'Message unavailable.';

  String missedExpectedDays(int count, String start, String end) {
    if (!isArabic) return missedExpectedDaysFallback(count, start, end);
    return 'فات اللاعب ${arabicCountPhrase(count, ArabicCountNoun.day)} '
        'من أيام التدريب المتوقعة (${_ltr(start)} إلى ${_ltr(end)})';
  }

  String missedExpectedDaysFallback(int count, String? start, String? end) =>
      'Missed $count expected training ${count == 1 ? 'day' : 'days'} '
      '(${start ?? '?'} to ${end ?? '?'})';

  String followUpDue(String date) => isArabic
      ? 'حان موعد المتابعة منذ ${_ltr(date)}'
      : 'Follow-up due since $date';

  String followUpDueFallback(String? date) =>
      'Follow-up due since ${date ?? 'an earlier date'}';

  String stalledSessions(int count, String? startDate) {
    if (!isArabic) {
      return 'Stalling — $count sessions without a personal record '
          '(since ${startDate ?? 'an earlier date'})';
    }
    final String since =
        startDate == null ? 'منذ تاريخ سابق' : 'منذ ${_ltr(startDate)}';
    return 'توقف التقدم: '
        '${arabicCountPhrase(count, ArabicCountNoun.trainingSession)} '
        'دون رقم قياسي شخصي ($since)';
  }

  String rollingReadinessDeload(double average) =>
      isArabic
          ? 'يوصى بتخفيف التدريب بسبب انخفاض الاستعداد في آخر 3 حصص تدريبية '
              '(المتوسط ${_ltr(average.toStringAsFixed(1))}/5)'
          : 'Deload recommended — Rolling readiness crash '
              '(avg ${average.toStringAsFixed(1)}/5)';

  String acuteReadinessDeload() =>
      isArabic
          ? 'يوصى بتخفيف التدريب بعد تسجيل الاستعداد بدرجة 1/5'
          : 'Deload recommended — Acute readiness floor (1/5 logged)';

  String highExertionDeload() =>
      isArabic
          ? 'يوصى بتخفيف التدريب بسبب ارتفاع نسبة مجموعات التدريب عند '
              'RIR 0.5 أو أقل مع انخفاض الاستعداد'
          : 'Deload recommended — High exertion density';

  String deloadChoice(String message, String? choice) {
    if (choice == 'apply') {
      return isArabic
          ? '$message · اختار اللاعب تطبيقه في الحصة التدريبية التالية فقط'
          : '$message · Player chose to apply it for the next workout only';
    }
    if (choice == 'undo') {
      return isArabic
          ? '$message · اختار اللاعب التراجع عنه للحصة التدريبية التالية فقط'
          : '$message · Player chose to undo it for the next workout only';
    }
    return message;
  }

  String deloadFallback(String? reason, Object? choice) {
    final String base =
        'Deload recommended — ${reason ?? 'Systemic fatigue'}';
    return switch (choice) {
      'apply' => '$base · Player chose to apply it for the next workout only',
      'undo' => '$base · Player chose to undo it for the next workout only',
      _ => base,
    };
  }

  String performanceRegression(String name, double delta, String badge) {
    final String sign = delta < 0 ? '−' : '+';
    if (!isArabic) {
      return 'Performance regression — $name: e1RM '
          '$sign${delta.abs().toStringAsFixed(1)} kg ($badge)';
    }
    return 'تراجع الأداء — ${_ltr(name)}: e1RM '
        '$sign${delta.abs().toStringAsFixed(1)} kg (${_ltr(badge)})';
  }

  String performanceRegressionFallback(
    String? name,
    double? delta,
    String? badge,
  ) {
    final String sign = delta == null ? '?' : delta < 0 ? '−' : '+';
    final String amount = delta == null ? '' : delta.abs().toStringAsFixed(1);
    return 'Performance regression — ${name ?? 'Exercise'}: e1RM '
        '$sign$amount kg (${badge ?? 'regression'})';
  }

  String profileChange(List<String> fields) {
    final List<String> labels = fields.map((String field) {
      return switch (field) {
        'injuries_or_limitations' =>
          isArabic ? 'الإصابات أو القيود' : 'Injuries or limitations',
        'equipment_access' =>
          isArabic ? 'المعدات المتاحة' : 'Equipment access',
        _ => '',
      };
    }).where((String label) => label.isNotEmpty).toList(growable: false);
    return isArabic
        ? 'تغير الملف التدريبي: ${labels.join('، ')}'
        : 'Training profile changed: ${labels.join(', ')}';
  }

  String profileChangeEvidence(
    Map<String, Map<String, String?>>? profileChanges,
  ) {
    const Map<String, String> englishLabels = <String, String>{
      'injuries_or_limitations': 'Injuries or limitations',
      'equipment_access': 'Equipment access',
    };
    const Map<String, String> arabicLabels = <String, String>{
      'injuries_or_limitations': 'الإصابات أو القيود',
      'equipment_access': 'المعدات المتاحة',
    };
    final Map<String, String> labels = isArabic ? arabicLabels : englishLabels;
    return (profileChanges ?? const <String, Map<String, String?>>{})
        .entries
        .where((MapEntry<String, Map<String, String?>> entry) =>
            labels.containsKey(entry.key))
        .map((MapEntry<String, Map<String, String?>> entry) {
          final String before = _profileValue(entry.value['before']);
          final String after = _profileValue(entry.value['after']);
          return '${labels[entry.key]}: $before → $after';
        })
        .join('\n');
  }

  String _profileValue(String? value) {
    if (value == null || value.isEmpty) {
      return isArabic ? 'غير محدد' : 'Not set';
    }
    return isArabic ? _ltr(value) : value;
  }
}

String _ltr(Object value) => '\u2066$value\u2069';
