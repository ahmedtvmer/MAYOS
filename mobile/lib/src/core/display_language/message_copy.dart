import 'arabic_count.dart';
import 'intake_copy.dart';

class MessageCopy {
  const MessageCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get unavailable =>
      isArabic ? 'تعذر عرض الرسالة.' : 'Message unavailable.';

  String get badRequest => isArabic
      ? 'تعذر تنفيذ الطلب. راجع البيانات وحاول مجددًا.'
      : 'The request could not be completed.';

  String get unauthorized => isArabic
      ? 'تعذر التحقق من تسجيل الدخول. سجّل الدخول مجددًا.'
      : 'The request was not authorized.';

  String get forbidden => isArabic
      ? 'لا تملك صلاحية تنفيذ هذا الإجراء.'
      : 'You do not have permission to do that.';

  String get notFound => isArabic ? 'لم يُعثر على المطلوب.' : 'Not found.';

  String get conflict => isArabic
      ? 'تعذر إتمام الطلب بسبب تعارض مع الحالة الحالية.'
      : 'The request conflicts with the current state.';

  String get invalidRequest => isArabic
      ? 'راجع البيانات المدخلة وحاول مرة أخرى.'
      : 'The request contains invalid fields.';

  String inputTooLong(int limit) => isArabic
      ? 'يجب ألا يتجاوز هذا الحقل ${arabicCountPhrase(
          limit,
          ArabicCountNoun.character,
          isolateCount: true,
        )}'
      : 'The field must be no longer than $limit characters.';

  String get rateLimited => isArabic
      ? 'وصل الطلب إلى الحد المسموح. حاول مرة أخرى لاحقًا.'
      : 'Too many requests. Please try again later.';

  String get aiRequestRateLimited => isArabic
      ? 'أرسلت طلبات كثيرة إلى المساعد. انتظر دقيقة ثم أعد المحاولة.'
      : 'Too many AI requests. Please wait a minute and try again.';

  String get aiDailyLimit => isArabic
      ? 'وصلت إلى حد استخدام المساعد اليوم. أعد المحاولة غدًا.'
      : 'You have reached your daily AI usage limit. Please try again tomorrow.';

  String get requestUnavailable => isArabic
      ? 'تعذر إكمال الطلب. حاول مجددًا.'
      : 'The service is unavailable. Please retry.';

  String get requestFailed => isArabic
      ? 'تعذر تنفيذ الطلب. حاول مجددًا.'
      : 'The request failed. Please try again.';

  String get chatFailure => isArabic
      ? 'تعذر على المساعد إكمال الرد. يُرجى إعادة المحاولة.'
      : 'The assistant is temporarily unavailable.';

  String get googleAlreadyLinked => isArabic
      ? 'حساب Google هذا مرتبط بالفعل بحساب MAYOS.'
      : 'This Google account is already linked to a MAYOS account.';

  String get programVersionMismatch => isArabic
      ? 'سُجلت هذه الحصة على إصدار أقدم من البرنامج.'
      : 'This workout was logged against an older program version.';

  String? specificError(String code, {int? limit}) {
    if (!isArabic) return null;
    if (code == 'http.input_too_long.v1') {
      return limit == null
          ? null
          : 'يجب ألا يتجاوز هذا الحقل ${arabicCountPhrase(
              limit,
              ArabicCountNoun.character,
              isolateCount: true,
            )}';
    }
    final String? translation = _specificArabicErrors[code];
    if (translation == null) return null;
    if (translation.contains(_limitPlaceholder)) {
      if (limit == null) return null;
      return translation.replaceAll(
        _limitPlaceholder,
        arabicCountPhrase(
          limit,
          ArabicCountNoun.character,
          isolateCount: true,
        ),
      );
    }
    return translation;
  }

  String? intakeCopy(String code) =>
      isArabic ? arabicIntakeCopy[code] : null;

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

  String weightTrendEvidence(List<String> points, double? targetWeightKg) {
    final String evidence = points.map(_ltr).join(isArabic ? '، ' : '; ');
    final String target = targetWeightKg == null
        ? (isArabic ? 'غير متاح' : 'not available')
        : _ltr('${_formatMessageNumber(targetWeightKg)} kg');
    return isArabic
        ? 'نقاط الوزن المؤرخة: $evidence. الوزن المستهدف: $target.'
        : 'Dated weight points: $evidence. Target weight: $target.';
  }

  String weightTrendPoint(String date, String weight) =>
      isArabic ? _ltr('$date: $weight kg') : '$date: $weight kg';

  String weightOffTargetTrend(
    double changeKg,
    double targetWeightKg,
    int windowDays,
    double thresholdKg,
  ) =>
      isArabic
          ? 'ابتعد الوزن عن الهدف بمقدار '
              '${_ltr('${_formatMessageNumber(changeKg)} kg')} خلال آخر ${_ltr('$windowDays')} يومًا '
              '(حد التنبيه ${_ltr('${_formatMessageNumber(thresholdKg)} kg')}؛ '
              'الهدف ${_ltr('${_formatMessageNumber(targetWeightKg)} kg')}).'
          : 'Weight moved away from the target by '
              '${_formatMessageNumber(changeKg)} kg over $windowDays days '
              '(alert threshold ${_formatMessageNumber(thresholdKg)} kg; '
              'target ${_formatMessageNumber(targetWeightKg)} kg).';

  String _profileValue(String? value) {
    if (value == null || value.isEmpty) {
      return isArabic ? 'غير محدد' : 'Not set';
    }
    return isArabic ? _ltr(value) : value;
  }
}

const Map<String, String> _specificArabicErrors = <String, String>{
  'auth.invalid_credentials.v1': 'بيانات تسجيل الدخول غير صحيحة.',
  'auth.username_taken.v1': 'اسم المستخدم مستخدم بالفعل.',
  'auth.invalid_or_expired_token.v1': 'انتهت صلاحية تسجيل الدخول أو لم يعد صالحًا.',
  'auth.invalid_signup_ticket.v1': 'انتهت صلاحية التسجيل عبر Google أو لم يعد صالحًا.',
  'auth.signup_ticket_missing.v1': 'تعذر العثور على تذكرة التسجيل.',
  'assignment.none_active.v1': 'لا توجد علاقة تدريب نشطة.',
  'assignment.invite_invalid.v1': 'رمز الدعوة للتدريب مع مدرب غير صالح أو انتهت صلاحيته.',
  'assignment.self_assignment.v1': 'لا يمكنك تعيين نفسك مدربًا لك.',
  'assignment.already_assigned.v1': 'لديك علاقة تدريب نشطة بالفعل.',
  'assignment.consent_required.v1': 'اقبل علاقة التدريب صراحةً للمتابعة.',
  'assignment.roster_full.v1': 'قائمة اللاعبين لدى المدرب ممتلئة. اطلب دعوة جديدة لاحقًا.',
  'assignment.coach_roster_full.v1':
      'قائمة اللاعبين ممتلئة. أنهِ علاقة تدريب قبل إصدار دعوة أخرى.',
  'assignment.coach_capability_required.v1': 'تتطلب هذه العملية صلاحية المدرب.',
  'assignment.coach_profile_required.v1': 'أكمل إعداد ملف المدرب قبل إصدار الدعوات.',
  'assignment.invite_lifetime_invalid.v1': 'يجب أن تكون مدة الدعوة بالدقائق أكبر من صفر.',
  'assignment.not_participant.v1': 'لا تملك صلاحية إدارة علاقة التدريب هذه.',
  'assignment.already_ended.v1': 'انتهت علاقة التدريب هذه بالفعل.',
  'assignment.program_draft_exists.v1': 'توجد مسودة برنامج تدريبي مفتوحة لعلاقة التدريب هذه بالفعل.',
  'assignment.program_draft_changed.v1': 'تغيرت مسودة البرنامج أثناء إنشائها. أعد المحاولة.',
  'assignment.program_draft_invalid.v1': 'راجع تفاصيل البرنامج التدريبي وحاول مجددًا.',
  'assignment.check_in_invalid.v1': 'تعذر تسجيل التواصل. راجع البيانات وحاول مجددًا.',
  'assignment.not_found.v1': 'لم يُعثر على الإسناد.',
  'assignment.program_draft_not_found.v1': 'لم يُعثر على مسودة البرنامج التدريبي.',
  'assignment.notice_not_found.v1': 'لم يُعثر على الإشعار.',
  'assignment.request_invalid.v1': 'تعذر تنفيذ طلب علاقة التدريب. راجع البيانات وحاول مجددًا.',
  'program.no_active.v1': 'لا يوجد برنامج تدريبي نشط.',
  'program.coach_controls.v1': 'يتحكم مدربك في برنامجك التدريبي. اطلب منه إجراء التغييرات.',
  'program.substitution.day_not_found.v1': 'هذا اليوم غير موجود في برنامجك التدريبي الحالي.',
  'program.substitution.source_not_on_day.v1': 'هذا التمرين غير موجود في ذلك اليوم من برنامجك الحالي.',
  'program.substitution.replacement_is_source.v1': 'اختر تمرينًا بديلًا مختلفًا.',
  'program.substitution.replacement_not_found.v1': 'لم يُعثر على التمرين البديل.',
  'program.substitution.replacement_already_on_day.v1': 'التمرين البديل موجود بالفعل في اليوم المستهدف.',
  'program.substitution.restore_version_not_found.v1': 'لم يُعثر على إصدار البرنامج المطلوب استعادته.',
  'program.substitution.changed.v1': 'تغير البرنامج منذ هذا الاستبدال. حدّث البرنامج ثم أعد المحاولة.',
  'program_request.invalid_kind.v1': 'اختر استبدال تمرين أو تغيير تقسيم التدريب.',
  'program_request.reason_required.v1': 'أضف سببًا للطلب.',
  'program_request.reason_too_long.v1': 'يجب ألا يتجاوز سبب الطلب $_limitPlaceholder.',
  'program_request.direct_change.v1': 'يتحكم مدربك في برنامجك التدريبي. أرسل طلب تغيير إليه.',
  'program_request.no_active_program.v1': 'لا يوجد برنامج تدريبي نشط لتغييره.',
  'program_request.target_incomplete.v1': 'اختر اليوم والتمرين والتمرين البديل.',
  'program_request.same_replacement.v1': 'اختر تمرينًا بديلًا مختلفًا.',
  'program_request.day_not_in_program.v1': 'هذا اليوم غير موجود في برنامجك التدريبي الحالي.',
  'program_request.exercise_not_in_day.v1': 'هذا التمرين غير موجود في ذلك اليوم من برنامجك الحالي.',
  'program_request.replacement_not_found.v1': 'لم يُعثر على التمرين البديل.',
  'program_request.frequency_invalid.v1': 'يجب أن يتراوح عدد أيام التدريب أسبوعيًا بين 1 و5.',
  'program_request.split_too_long.v1': 'يجب ألا يتجاوز تفضيل تقسيم التدريب $_limitPlaceholder.',
  'program_request.not_found.v1': 'لم يُعثر على الطلب.',
  'program_request.not_pending.v1': 'لم يعد هذا الطلب قيد الانتظار.',
  'program_request.stale.v1': 'تغير البرنامج منذ إنشاء هذا الطلب. اطلب من اللاعب تحديثه.',
  'program_request.response_required.v1': 'أضف ردًا على الطلب.',
  'program_request.response_too_long.v1': 'يجب ألا يتجاوز الرد $_limitPlaceholder.',
  'program_request.selection_invalid.v1': 'تعذر اعتماد بعض طلبات تغيير البرنامج المحددة.',
  'intake.structured_active.v1': 'يوجد تسجيل منظم جارٍ بالفعل. أكمله قبل بدء تسجيل آخر.',
  'intake.in_progress.v1': 'يجري إنشاء البرنامج التدريبي لهذا التسجيل. انتظر ثم حاول مجددًا.',
  'coach.ai_unavailable.v1': 'مساعد المدرب غير متاح حاليًا.',
  'media.unavailable.v1': 'تعذر تحميل الوسائط حاليًا. حاول مجددًا.',
  'media.not_found.v1': 'لم يُعثر على الوسائط المطلوبة.',
  'google.invalid_token.v1': 'تعذر التحقق من بيانات Google.',
  'google.linked_elsewhere.v1': 'حساب Google هذا مرتبط بالفعل بحساب MAYOS آخر.',
  'google.different_account.v1': 'يوجد حساب Google مختلف مرتبط بهذا الحساب. افصله أولًا.',
  'google.unlink_password_required.v1':
      'عيّن كلمة مرور قبل فصل Google لتتمكن من تسجيل الدخول.',
  'recovery.invalid_or_expired_code.v1': 'رمز التحقق غير صالح أو انتهت صلاحيته.',
  'recovery.code_send_limit.v1': 'تعذر إرسال رمز التحقق الآن. حاول مجددًا لاحقًا.',
  'recovery.invalid_or_expired_token.v1':
      'رابط إعادة تعيين كلمة المرور غير صالح أو انتهت صلاحيته.',
  'coach_invite.invalid_code.v1': 'رمز دعوة تفعيل دور المدرب غير صالح أو انتهت صلاحيته.',
};

const String _limitPlaceholder = 'الحد المحدد';

String _ltr(Object value) => '\u2066$value\u2069';

String _formatMessageNumber(double value) {
  final String fixed = value.toStringAsFixed(1);
  return fixed.endsWith('.0') ? fixed.substring(0, fixed.length - 2) : fixed;
}
