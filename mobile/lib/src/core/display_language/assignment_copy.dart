import 'arabic_count.dart';

/// App-owned labels for the player side of a coaching assignment and program
/// requests. Coach and service prose is rendered directly by the screen.
class AssignmentCopy {
  const AssignmentCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get assignmentAccepted =>
      isArabic ? 'تم قبول علاقة التدريب.' : 'Assignment accepted.';
  String get endAssignmentQuestion =>
      isArabic ? 'إنهاء علاقة التدريب؟' : 'End assignment?';
  String get endAssignmentLead => isArabic
      ? 'سيفقد مدربك فورًا إمكانية الاطلاع على سجل تدريبك.'
      : 'Your coach will immediately lose access to your training history.';
  String get endAssignment =>
      isArabic ? 'إنهاء علاقة التدريب' : 'End assignment';
  String get assignmentEnded =>
      isArabic ? 'انتهت علاقة التدريب.' : 'Assignment ended.';
  String get programRequests =>
      isArabic ? 'طلبات البرنامج التدريبي' : 'Program requests';
  String get requestChange => isArabic ? 'طلب تغيير' : 'Request a change';
  String get noProgramRequests => isArabic
      ? 'لا توجد طلبات للبرنامج التدريبي بعد.'
      : 'No program requests yet.';
  String get cancelRequest => isArabic ? 'إلغاء الطلب' : 'Cancel request';
  String get reasonPrefix => isArabic ? 'السبب: ' : 'Reason: ';
  String get coachPrefix => isArabic ? 'المدرب: ' : 'Coach: ';
  String requestStatus(String status) => switch (status) {
        'pending' => isArabic ? 'قيد الانتظار' : 'Pending',
        'applied' => isArabic ? 'تم التطبيق' : 'Applied',
        'declined' => isArabic ? 'مرفوض' : 'Declined',
        'cancelled' => isArabic ? 'ملغى' : 'Cancelled',
        _ => status,
      };
  String programRequestDescription({
    required String kind,
    required String? exercise,
    required String? day,
    required String? replacement,
    required int? frequency,
    required String? preference,
  }) {
    if (!isArabic) {
      if (kind == 'exercise_substitution') {
        return 'Substitute $exercise on $day with $replacement';
      }
      final String split =
          preference == null || preference.isEmpty ? '' : ' ($preference)';
      return 'Change to $frequency days/week$split';
    }
    if (kind == 'exercise_substitution') {
      return 'طلب تبديل تمرين من المدرب: ${_ltr(exercise ?? '')} في ${_ltr(day ?? '')} إلى ${_ltr(replacement ?? '')}';
    }
    final String days = frequency == null
        ? ''
        : '${arabicCountPhrase(frequency, ArabicCountNoun.day, isolateCount: true)} في الأسبوع';
    final String split = preference == null || preference.isEmpty
        ? ''
        : ' (${_ltr(preference)})';
    return 'تغيير تقسيمة البرنامج إلى $days$split';
  }

  String get notices => isArabic ? 'الإشعارات' : 'Notices';
  String get markAllRead => isArabic ? 'تحديد الكل كمقروء' : 'Mark all read';
  String get checkIns => isArabic ? 'سجلات التواصل' : 'Check-ins';
  String get formerCoach => isArabic ? 'المدرب السابق' : 'Former coach';
  String coachUsername(String username) =>
      isArabic ? 'المدرب ${_ltr(username)}' : 'Coach $username';
  String get assignmentEndedStatus =>
      isArabic ? 'انتهت علاقة التدريب' : 'assignment ended';
  String get yourCoach => isArabic ? 'مدربك' : 'Your coach';
  String get activeAssignment =>
      isArabic ? 'علاقة التدريب نشطة' : 'Coaching assignment active';
  String get activeAssignmentAccess => isArabic
      ? 'أثناء نشاط علاقة التدريب، يمكن لمدربك الاطلاع على بيانات تدريبك الحالية والسابقة. يؤدي إنهاؤها إلى إلغاء إمكانية الاطلاع فورًا.'
      : 'While this assignment is active, your coach can view your current and historical training data. Ending it revokes that access immediately.';
  String get coachAssignment =>
      isArabic ? 'علاقة التدريب مع المدرب' : 'Coach assignment';
  String get inviteExplanation => isArabic
      ? 'أدخل رمز الدعوة من مدربك. لن يتمكن مدربك من الاطلاع على بيانات تدريبك إلا بعد موافقتك، وينتهي ذلك عند إنهاء أحدكما علاقة التدريب.'
      : 'Enter the invite code from your coach. Your coach can only see your training data after you accept, and access ends when either of you ends the assignment.';
  String get inviteCodeFromCoach =>
      isArabic ? 'رمز الدعوة من مدربك' : 'Invite code from your coach';
  String get previewAccess =>
      isArabic ? 'معاينة إمكانية الاطلاع' : 'Preview access';
  String coachWillBe(String name) =>
      isArabic ? 'سيكون مدربك $name' : 'Your coach will be $name';
  String get acceptAssignment =>
      isArabic ? 'قبول علاقة التدريب' : 'Accept assignment';
  String get enterInviteCode => isArabic
      ? 'أدخل رمز الدعوة من مدربك.'
      : 'Enter the invite code from your coach.';
  String get requestType => isArabic ? 'نوع الطلب' : 'Request type';
  String checkInChannel(String channel) => switch (channel) {
        'in_app' => isArabic ? 'داخل التطبيق' : 'In app',
        'in_person' => isArabic ? 'حضوري' : 'In person',
        'phone' => isArabic ? 'هاتف' : 'Phone',
        'video' => isArabic ? 'مرئي' : 'Video',
        'message' => isArabic ? 'رسالة' : 'Message',
        'email' => isArabic ? 'بريد إلكتروني' : 'Email',
        _ => isArabic ? 'أخرى' : 'Other',
      };
  String get programChangeRequest =>
      isArabic ? 'طلب تغيير البرنامج التدريبي' : 'Request a program change';
  String get exerciseSubstitutionRequest =>
      isArabic ? 'طلب تبديل تمرين من المدرب' : 'Exercise substitution';
  String get splitChange => isArabic ? 'تغيير تقسيمة البرنامج' : 'Split change';
  String get day => isArabic ? 'اليوم' : 'Day';
  String get exercise => isArabic ? 'التمرين' : 'Exercise';
  String get replacement => isArabic ? 'البديل' : 'Replacement';
  String get dayName => isArabic ? 'اسم اليوم' : 'Day name';
  String get currentExerciseId =>
      isArabic ? 'معرّف التمرين الحالي' : 'Current exercise id';
  String get replacementExerciseId =>
      isArabic ? 'معرّف التمرين البديل' : 'Replacement exercise id';
  String get daysPerWeek => isArabic ? 'أيام في الأسبوع' : 'Days per week';
  String get splitPreferenceOptional =>
      isArabic ? 'تفضيل التقسيمة (اختياري)' : 'Split preference (optional)';
  String get reason => isArabic ? 'السبب' : 'Reason';
  String get reasonRequired =>
      isArabic ? 'السبب مطلوب.' : 'A reason is required.';
  String get chooseSubstitutionValues => isArabic
      ? 'اختر اليوم والتمرين والبديل.'
      : 'Pick the day, the exercise, and its replacement.';
  String get submitRequest => isArabic ? 'إرسال الطلب' : 'Submit request';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';

  String _ltr(String value) => '\u2066$value\u2069';
}
