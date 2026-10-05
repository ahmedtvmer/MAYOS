import 'arabic_count.dart';
import 'catalog.dart' show exerciseNameOrFallback;

/// App-owned labels for the player side of a coaching assignment and program
/// requests. Coach and service prose is rendered directly by the screen.
class AssignmentCopy {
  const AssignmentCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get assignmentAccepted =>
      isArabic ? 'تم قبول علاقة التدريب.' : 'Assignment accepted.';
  String get leaveCoachQuestion =>
      isArabic ? 'مغادرة المدرب؟' : 'Leave coach?';
  String get leaveCoachLead => isArabic
      ? 'مغادرتك لمدربك تلغي وصوله إلى سجل تدريبك فورًا.'
      : 'Leaving your coach immediately revokes their access to your training '
          'history.';
  String get leaveCoach => isArabic ? 'مغادرة المدرب' : 'Leave coach';
  String get leaveCoachComplete =>
      isArabic ? 'غادرت مدربك.' : 'You left your coach.';
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
    final String from = exerciseNameOrFallback(exercise, languageCode);
    final String to = exerciseNameOrFallback(replacement, languageCode);
    if (!isArabic) {
      if (kind == 'exercise_substitution') {
        return 'Substitute $from on $day with $to';
      }
      final String split =
          preference == null || preference.isEmpty ? '' : ' ($preference)';
      return 'Change to $frequency days/week$split';
    }
    if (kind == 'exercise_substitution') {
      return 'طلب تبديل تمرين من المدرب: ${_ltr(from)} في ${_ltr(day ?? '')} إلى ${_ltr(to)}';
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
      isArabic ? 'انتهت علاقة التدريب' : 'coaching ended';
  String get yourCoach => isArabic ? 'مدربك' : 'Your coach';
  String get activeAssignmentAccess => isArabic
      ? 'أثناء نشاط علاقتك بمدربك، يمكنه الاطلاع على بيانات تدريبك الحالية والسابقة. مغادرتك لمدربك تلغي إمكانية الاطلاع فورًا.'
      : 'While you have a coach, they can view your current and historical '
          'training data. Leaving your coach revokes that access immediately.';
  String get myCoach => isArabic ? 'مدربي' : 'My coach';
  String get inviteExplanation => isArabic
      ? 'أدخل رمز الدعوة من مدربك. لن يتمكن مدربك من الاطلاع على بيانات تدريبك إلا بعد موافقتك، وينتهي وصوله عندما تغادر مدربك أو يغادر هو.'
      : 'Enter your coach’s invite code. Your coach can view your training data '
          'only after you accept, and access ends when either of you leaves the '
          'coaching relationship.';
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
  String get chooseFrequency =>
      isArabic ? 'اختر عدد أيام التدريب' : 'Choose days per week';
  String get splitPreferenceOptional =>
      isArabic ? 'تفضيل التقسيمة (اختياري)' : 'Split preference (optional)';
  String get reason => isArabic ? 'السبب' : 'Reason';
  String get reasonRequired =>
      isArabic ? 'السبب مطلوب.' : 'A reason is required.';
  String get reasonTooLong => isArabic
      ? 'يجب ألا يتجاوز السبب 500 حرف.'
      : 'The reason must be 500 characters or fewer.';
  String reasonCharacterCount(int current, int maximum) => isArabic
      ? '$current / $maximum حرفًا'
      : '$current / $maximum characters';
  String get chooseSubstitutionValues => isArabic
      ? 'اختر اليوم والتمرين والبديل.'
      : 'Pick the day, the exercise, and its replacement.';
  String get submitRequest => isArabic ? 'إرسال الطلب' : 'Submit request';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';

  String _ltr(String value) => '\u2066$value\u2069';
}
