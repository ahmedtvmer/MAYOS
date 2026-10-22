import 'arabic_count.dart';
import 'catalog.dart' show MyosCopy, exerciseNameOrFallback;
import 'message_copy.dart';
import 'message_resolution.dart';
import '../personal_records.dart';
import '../program_prescription.dart';
import '../program_load.dart';
import '../shared_program_text.dart';

/// App-owned coach mode labels. Server supplied notices, alert descriptions,
/// player notes, assistant replies, and checkpoint prose are rendered as sent.
class CoachCopy {
  const CoachCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get roster => isArabic ? 'قائمة اللاعبين' : 'Roster';
  String get alerts => isArabic ? 'التنبيهات' : 'Alerts';
  String get requests => isArabic ? 'الطلبات' : 'Requests';
  String get profile => isArabic ? 'الملف الشخصي' : 'Profile';
  String get allPlayers => isArabic ? 'كل اللاعبين' : 'All players';
  String get stalledFilter => isArabic ? 'المتوقفون' : 'Stalled';
  String get noStalledPlayers =>
      isArabic ? 'لا يوجد لاعبون متوقفون.' : 'No stalled players.';
  String get coachSettings => isArabic ? 'إعدادات المدرب' : 'Coach settings';
  String get stallThreshold => isArabic ? 'حد التوقف' : 'Stall threshold';
  String get stallThresholdDescription => isArabic
      ? 'حدّد عدد الأسابيع دون رقم قياسي شخصي لعرض اللاعب كمتوقف. التنبيه بعد 8 حصص لم يتغير.'
      : 'Weeks without a Personal record before a player is marked Stalled. The 8-session Coach alert is unchanged.';
  String stallThresholdOption(int weeks) => isArabic
      ? '${_ltr(weeks.toString())} أسابيع'
      : '$weeks week${weeks == 1 ? '' : 's'}';
  String get stallThresholdSaved =>
      isArabic ? 'تم حفظ حد التوقف.' : 'Stall threshold saved.';
  String requestPlayerDay(String player, String day) =>
      isArabic ? '${_ltr(player)} · ${_ltr(day)}' : '$player · $day';
  String get activeAssignments =>
      isArabic ? 'علاقات التدريب النشطة' : 'Active assignments';
  String get noAssignedPlayers =>
      isArabic ? 'لا يوجد لاعبون معينون بعد.' : 'No assigned players yet.';
  String get sharedProgramCoachOnly => isArabic
      ? 'مشاركة برنامج تدريبي متاحة للمدربين فقط.'
      : 'Sharing a program is available to Coaches only.';
  String get sharedProgramGoHome => isArabic ? 'الرئيسية' : 'Home';
  String get sharedProgramBackToRoster => isArabic
      ? 'العودة إلى قائمة المدرب'
      : 'Back to Coach roster';
  String get sharedProgramRetry =>
      isArabic ? 'إعادة المحاولة' : 'Retry';
  String get sharedProgramAssignmentsUnavailable => isArabic
      ? 'تعذّر تحميل قائمة اللاعبين. حاول مرة أخرى.'
      : 'Players could not be loaded. Please try again.';
  String get sharedProgramSignInRequired => isArabic
      ? 'سجّل الدخول إلى MYOS لمتابعة مشاركة البرنامج.'
      : 'Sign in to MYOS to continue sharing this program.';
  String get choosePlayerForSharedProgram => isArabic
      ? 'اختر اللاعب الذي سيُستورد له البرنامج.'
      : 'Choose the Player to import this program for.';
  String get textImportUnavailable => isArabic
      ? 'استيراد النص غير متاح حاليًا.'
      : 'Text import is unavailable right now.';
  String get sharedProgramUnavailable => isArabic
      ? 'تعذّر فتح النص المشارك. أعد مشاركته من التطبيق الآخر.'
      : 'The shared text could not be opened. Share it again from the other app.';
  String sharedProgramRefusal(SharedProgramTextError error) => switch (error) {
        SharedProgramTextError.fileTooLarge => isArabic
            ? 'حجم الملف أكبر من 1 ميجابايت.'
            : 'The text file is larger than 1 MiB.',
        SharedProgramTextError.unsupportedFileType => isArabic
            ? 'شارك ملفًا بامتداد .txt لاستيراد البرنامج.'
            : 'Share a .txt file to import a program.',
        SharedProgramTextError.invalidUtf8 => isArabic
            ? 'ترميز ملف .txt غير صالح.'
            : 'The .txt file is not valid UTF-8.',
        SharedProgramTextError.fileReadFailed => isArabic
            ? 'تعذّرت قراءة الملف المشارك.'
            : 'The shared file could not be read.',
      };
  String get revokeAssignmentQuestion =>
      isArabic ? 'إنهاء علاقة التدريب؟' : 'Revoke assignment?';
  String revokeAssignmentLead(String player) => isArabic
      ? 'سيفقد ${_ltr(player)} إمكانية التدريب معك فورًا ولن تتمكن من الاطلاع على بياناته.'
      : '$player will lose coaching immediately and can no longer be seen by you.';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';
  String get revoke => isArabic ? 'إنهاء العلاقة' : 'Revoke';
  String assignmentRevoked(String player) =>
      isArabic ? 'انتهت علاقة التدريب مع ${_ltr(player)}.' : 'Revoked $player.';
  String get disableCoachingQuestion =>
      isArabic ? 'إيقاف وضع المدرب؟' : 'Disable coaching?';
  String get disableCoachingLead => isArabic
      ? 'ستنتهي كل علاقات التدريب فورًا وسيُزال دور المدرب. ستبقى بيانات تدريبك كلاعب محفوظة.'
      : 'Every assignment ends immediately and your coach capability is removed. Your own player training data is kept.';
  String get disableCoaching =>
      isArabic ? 'إيقاف وضع المدرب' : 'Disable coaching';
  String coachingDisabled(int ended) => isArabic
      ? 'تم إيقاف وضع المدرب. انتهت ${_count(ended, ArabicCountNoun.assignment)}.'
      : 'Coaching disabled. $ended assignment(s) ended.';
  String get acknowledge => isArabic ? 'تأكيد الاطلاع' : 'Acknowledge';
  String get resolve => isArabic ? 'حل التنبيه' : 'Resolve';
  String get showResolved =>
      isArabic ? 'عرض التنبيهات المحلولة' : 'Show resolved';
  String get noAlerts => isArabic ? 'لا توجد تنبيهات.' : 'No alerts to show.';
  String get noActiveAssignment =>
      isArabic ? 'لا توجد علاقة تدريب نشطة.' : 'No active assignment.';
  String resolvedBy(String username) {
    if (!isArabic) return 'Resolved by $username';
    final String label = switch (username) {
      'system' => 'النظام',
      'coach' => 'المدرب',
      _ => _ltr(username),
    };
    return 'حلّه $label';
  }

  String get alertNew => isArabic ? 'جديد' : 'New';
  String get alertAcknowledged =>
      isArabic ? 'تم تأكيد الاطلاع' : 'Acknowledged';
  String get alertResolved => isArabic ? 'تم الحل' : 'Resolved';
  String alertState(String state) => switch (state) {
        'new' => alertNew,
        'acknowledged' => alertAcknowledged,
        'resolved' => alertResolved,
        _ => isArabic ? 'حالة غير معروفة' : 'Unknown status',
      };
  String missedDays(int count) {
    if (!isArabic) return 'Missed ${count}d';
    final String suffix = count == 1
        ? ' فائت'
        : count == 2
            ? ' فائتان'
            : count >= 11 || count == 0
                ? ' فائتًا'
                : ' فائتة';
    return '${_count(count, ArabicCountNoun.day)}$suffix';
  }

  String stalledSessions(int count) => isArabic
      ? 'توقف التقدم: ${_count(count, ArabicCountNoun.trainingSession)}'
      : 'Stalled $count session${count == 1 ? '' : 's'}';
  String alertsCount(int count) => isArabic
      ? _count(count, ArabicCountNoun.alert)
      : '$count alert${count == 1 ? '' : 's'}';
  String requestsCount(int count) => isArabic
      ? _count(count, ArabicCountNoun.request)
      : '$count request${count == 1 ? '' : 's'}';
  String get followUpToday => isArabic ? 'المتابعة اليوم' : 'Follow-up today';
  String get followUpOverdue =>
      isArabic ? 'المتابعة متأخرة' : 'Follow-up overdue';
  String get rosterAttendance => isArabic ? 'الانتظام' : 'Attendance';
  String get rosterOnTrack => isArabic ? 'منتظم' : 'On track';
  String rosterAttendanceStatus(int missedDays) => missedDays == 0
      ? rosterOnTrack
      : isArabic
          ? this.missedDays(missedDays)
          : '$missedDays missed ${missedDays == 1 ? 'day' : 'days'}';
  String rosterNextFollowUp(String? date) => date == null
      ? (isArabic ? 'غير محدد' : 'Not scheduled')
      : isArabic
          ? _ltr(date)
          : date;
  String get rosterNextFollowUpLabel =>
      isArabic ? 'المتابعة القادمة' : 'Next follow-up';
  String get rosterFollowUpStatusLabel =>
      isArabic ? 'حالة المتابعة' : 'Follow-up status';
  String get rosterAlertsLabel => isArabic ? 'شارات التنبيه' : 'Alert badges';
  String get noWorkoutsYet =>
      isArabic ? 'لم يسجل حصصًا بعد' : 'No workouts yet';
  String get revoking => isArabic ? 'جارٍ إنهاء العلاقة…' : 'Revoking…';
  String rosterSubtitle({required String? lastWorkout, String? program}) {
    if (lastWorkout == null) return noWorkoutsYet;
    return lastWorkoutForRoster(lastWorkout, program: program);
  }

  String lastWorkoutForRoster(String date, {String? program}) => isArabic
      ? 'آخر حصة تدريبية ${_ltr(date)}${program == null || program.isEmpty ? '' : ' · ${_ltr(program)}'}'
      : 'Last workout $date${program == null || program.isEmpty ? '' : ' · $program'}';
  String lastWorkout(String date, {String? program}) => isArabic
      ? 'آخر حصة تدريبية: ${_ltr(date)}${program == null || program.isEmpty ? '' : ' · ${_ltr(program)}'}'
      : 'Last workout $date${program == null || program.isEmpty ? '' : ' · $program'}';

  String get assistant => isArabic ? 'المساعد' : 'Assistant';
  String get askAssistant => isArabic ? 'اسأل المساعد' : 'Ask assistant';
  String get askAboutRoster =>
      isArabic ? 'اسأل عن قائمة اللاعبين' : 'Ask about the roster';
  String get rosterAssistantLead => isArabic
      ? 'اسأل عن اللاعبين الذين يحتاجون إلى متابعة، أو التوقف، أو الالتزام بالتدريب.'
      : 'Ask which players need attention, have stalled, or are keeping up with training.';
  String get rosterAssistantPrivacyNote => isArabic
      ? 'يتلقى النموذج المستضاف لقطة إشارات قائمة اللاعبين وسؤالك وسجل هذه المحادثة فقط. لا تتضمن اللقطة أسماء اللاعبين أو بيانات التواصل أو أرقام الحسابات وعلاقات التدريب أو الملاحظات أو النصوص الحرة أو محادثات اللاعب. لا تُحفظ المحادثة.'
      : 'The hosted model receives only the Roster signal snapshot, your question, and this conversation history. The snapshot excludes player names, contact details, Account or Assignment ids, notes, free text, and Player chat. This conversation is not saved.';
  String get rosterQuestionHint => isArabic
      ? 'مثال: من يحتاج إلى متابعة اليوم؟'
      : 'For example: Who needs my attention today?';
  String get rosterAssistantDisabled => isArabic
      ? 'مساعد قائمة اللاعبين غير متاح لأن بوابة الخصوصية والتقييم لم تُفعّل.'
      : 'Roster questions are unavailable because the privacy and evaluation gate is not enabled.';
  String get rosterAssistantUpgrade => isArabic
      ? 'ترتيب قائمة اللاعبين حسب الحاجة متاح. أسئلة الذكاء الاصطناعي عن القائمة تتطلب Coach Pro.'
      : 'The Roster urgency order is available. AI roster questions require Coach Pro.';
  String get rosterUrgencyOrderHeading =>
      isArabic ? 'ترتيب قائمة اللاعبين حسب الحاجة' : 'Roster urgency order';
  String rosterUrgencyPlayer(int rank, String player) =>
      isArabic ? '${_ltr(rank.toString())}. ${_ltr(player)}' : '$rank. $player';
  String rosterUrgencySignals({
    required int alerts,
    required int requests,
    required int missedDays,
    required int stallSessions,
  }) =>
      isArabic
          ? 'التنبيهات: ${_ltr(alerts.toString())} · الطلبات: ${_ltr(requests.toString())} · '
              'أيام التدريب الفائتة المتتالية: ${_ltr(missedDays.toString())} · '
              'الحصص دون رقم قياسي شخصي: ${_ltr(stallSessions.toString())}'
          : 'Alerts: $alerts · requests: $requests · missed-day streak: $missedDays · '
              'sessions without a Personal record: $stallSessions';
  String get rosterAssistantNoHistory => isArabic
      ? 'اسأل سؤالًا عن أرقام التدريب المجمّعة للاعبين الذين سجّلوا الإفصاح.'
      : 'Ask about the combined training signals for players who have recorded the disclosure.';
  String get askAboutOnePlayer =>
      isArabic ? 'اسأل عن لاعب واحد' : 'Ask about one player';
  String get assistantPickerLead => isArabic
      ? 'اختر لاعبًا من علاقة تدريب نشطة لفتح المساعد الخاص به.'
      : 'Choose a player on an active assignment to open their assistant.';
  String get chooseAssignedPlayer => isArabic
      ? 'اختر لاعبًا من علاقات التدريب النشطة'
      : 'Choose an active player';
  String get openPlayerAssistant =>
      isArabic ? 'فتح مساعد اللاعب' : 'Open player assistant';
  String get coachAiDisabled => isArabic
      ? 'مساعد المدرب غير متاح لأن الذكاء الاصطناعي للمدرب متوقف في هذا النشر.'
      : 'The Coach AI assistant is unavailable because Coach AI is turned off for this deployment.';
  String get loadingPlayers =>
      isArabic ? 'جارٍ تحميل اللاعبين…' : 'Loading players…';
  String get openAlerts => isArabic ? 'التنبيهات المفتوحة' : 'Open alerts';
  String assistantNoHistory(String player) => isArabic
      ? 'اسأل عن أرقام تدريب ${_ltr(player)}: مجموعات التدريب، والحصص، والأرقام القياسية، والجدول.'
      : 'Ask about $player\'s training figures: volume, sessions, records, and schedule.';
  String get assistantThinking => isArabic ? 'جارٍ التفكير…' : 'Thinking…';
  String assistantNote(String player) => isArabic
      ? 'يتلقى النموذج المستضاف اسم ${_ltr(player)} (والاسم المفضل إن وُجد)، واسمك كمدرب ونبذتك، '
          'وهدف اللاعب ومستوى خبرته والمعدات المتاحة واتجاهات وزن الجسم و\u2066e1RM\u2069، '
          'والإصابات النشطة وتوصيات الطبيب بشأن التمرين كما أبلغ بها اللاعب (الوصف والملاحظات حتى 300 حرف لكل منها)، '
          'وآخر 5 ملاحظات تواصل كتبتها (حتى 300 حرف لكل ملاحظة). '
          'قد تحتوي الملاحظات والإصابات والنبذة على تفاصيل تكشف الهوية. لا تُحفظ المحادثة.'
      : "The hosted model receives $player's name (preferred name if set), "
          "your coach display name and bio, $player's goal, Experience level, Equipment access, "
          "bodyweight and e1RM trends, active injuries and the player's reports of physician advice on exercise clearances "
          '(descriptions and notes up to 300 characters each), and your last 5 check-in notes '
          '(up to 300 characters each). Notes, injury details, and your bio may contain '
          "identifying details. This exchange isn't saved.";
  String get askAboutPlayer =>
      isArabic ? 'اسأل عن هذا اللاعب' : 'Ask about this player';
  String get send => isArabic ? 'إرسال' : 'Send';
  String get playerAssignmentEnded => isArabic
      ? 'لم تعد مدربًا لهذا اللاعب.'
      : 'You no longer coach this player';

  String get logCheckIn => isArabic ? 'تسجيل تواصل' : 'Log check-in';
  String checkInWithPlayer(String player) =>
      isArabic ? 'تسجيل تواصل مع ${_ltr(player)}' : 'Log check-in with $player';
  String datedToday(String date) =>
      isArabic ? 'تاريخ اليوم · ${_ltr(date)}' : 'Dated today · $date';
  String nextFollowUpLabel(String? date) => isArabic
      ? 'المتابعة القادمة: ${date == null ? notScheduled : _ltr(date)}'
      : 'Next follow-up: ${date ?? 'not scheduled'}';
  String get noteOptional => isArabic ? 'ملاحظة (اختيارية)' : 'Note (optional)';
  String get saveCheckIn => isArabic ? 'حفظ التواصل' : 'Save check-in';
  String get pickContactChannel =>
      isArabic ? 'اختر وسيلة التواصل.' : 'Pick a contact channel.';
  String get checkInRecorded =>
      isArabic ? 'تم تسجيل التواصل.' : 'Check-in recorded.';
  String get nextFollowUp => isArabic ? 'المتابعة القادمة' : 'Next follow-up';
  String get notScheduled => isArabic ? 'غير محدد' : 'not scheduled';
  String get noCheckIns =>
      isArabic ? 'لم يُسجل أي تواصل بعد.' : 'No check-ins recorded yet.';
  String checkInTitle(String date, String channel) =>
      isArabic ? '${_ltr(date)} · $channel' : '$date · $channel';
  String checkInChannel(String channel) {
    if (!isArabic) {
      return switch (channel) {
        'in_app' => 'In app',
        'in_person' => 'In person',
        'phone' => 'Phone',
        'video' => 'Video',
        'message' => 'Message',
        'email' => 'Email',
        _ => 'Other',
      };
    }
    return switch (channel) {
      'in_app' => 'داخل التطبيق',
      'in_person' => 'لقاء شخصي',
      'phone' => 'مكالمة هاتفية',
      'video' => 'مكالمة فيديو',
      'message' => 'رسالة',
      'email' => 'بريد إلكتروني',
      _ => 'أخرى',
    };
  }

  String get becomeCoach => isArabic ? 'كن مدربًا' : 'Become a coach';
  String get enterCoachCode =>
      isArabic ? 'أدخل رمز مدرب MYOS' : 'Enter your MYOS coach code';
  String get coachCodeLead => isArabic
      ? 'هذا الرمز من MYOS ويفعّل وضع المدرب في حسابك. يُستخدم مرة واحدة وتنتهي صلاحيته. إدخاله لا ينشئ علاقة تدريب مع مدرب.'
      : 'This code comes from MYOS and enables Coach mode on your own account. It is single-use and expires. Entering it does not assign you to a coach.';
  String get coachEnabled =>
      isArabic ? 'تم تفعيل دور المدرب.' : 'Coach capability enabled.';

  String get profileTitle => isArabic ? 'الملف الشخصي للمدرب' : 'Coach profile';
  String get profileLead => isArabic
      ? 'هذه المعلومات تعرّف اللاعبين بك بصفتك مدربًا.'
      : 'These details describe you as a coach.';
  String get displayName => isArabic ? 'الاسم المعروض' : 'Display name';
  String get specialization => isArabic ? 'التخصص' : 'Specialization';
  String get specializationHint => isArabic
      ? 'مثلًا: رفع الأثقال، بناء العضلات'
      : 'e.g. Powerlifting, Hypertrophy';
  String get bio => isArabic ? 'نبذة' : 'Bio';
  String get rosterCapacity =>
      isArabic ? 'سعة قائمة اللاعبين' : 'Roster capacity';
  String capacityRange(int min, int max) => isArabic
      ? 'من ${_ltr('$min')} إلى ${_ltr('$max')} لاعبًا.'
      : 'Between $min and $max players.';
  String get saveProfile => isArabic ? 'حفظ الملف الشخصي' : 'Save profile';
  String get coachProfileSaved =>
      isArabic ? 'تم حفظ ملف المدرب.' : 'Coach profile saved.';
  String get enterDisplayName =>
      isArabic ? 'أدخل اسمًا معروضًا.' : 'Enter a display name.';
  String displayNameMax(int max) => isArabic
      ? 'يجب ألا يتجاوز الاسم ${_ltr('$max')} حرفًا.'
      : 'Display name must be at most $max characters.';
  String get enterWholeNumber =>
      isArabic ? 'أدخل عددًا صحيحًا.' : 'Enter a whole number.';
  String capacityMustBe(int min, int max) => isArabic
      ? 'يجب أن تكون السعة بين ${_ltr('$min')} و${_ltr('$max')}.'
      : 'Capacity must be between $min and $max.';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get invitePlayer => isArabic ? 'دعوة لاعب للتدريب' : 'Invite a player';
  String get inviteExplanation => isArabic
      ? 'أنشئ رمز دعوة للتدريب مع مدرب لمرة واحدة وقدّمه للاعب. تنتهي صلاحيته، ولا يمكن استخدامه إلا عند توفر مكان في قائمة اللاعبين. سيظهر تاريخ الانتهاء بعد إنشاء الرمز.'
      : 'Create a single-use code and give it to one player. It expires and can only be redeemed while you have roster room; the exact expiry is shown when the code is issued.';
  String get createPlayerInvite =>
      isArabic ? 'إنشاء دعوة لاعب للتدريب' : 'Create player invite';
  String inviteExpires(String date) =>
      isArabic ? 'تنتهي الصلاحية ${_ltr(date)}' : 'Expires $date';
  String rosterSlotsFree(int remaining, int capacity) => isArabic
      ? 'المتاح في قائمة اللاعبين: ${_ltr('$remaining')} من ${_ltr('$capacity')}'
      : '$remaining of $capacity roster slots free';
  String get notices => isArabic ? 'الإشعارات' : 'Notices';
  String get markAllRead => isArabic ? 'تحديد الكل كمقروء' : 'Mark all read';
  String get resolvedAlerts =>
      isArabic ? 'التنبيهات المحلولة' : 'Resolved alerts';

  String get generateDraft => isArabic ? 'إنشاء مسودة' : 'Generate draft';
  String get cardioDays => isArabic ? 'أيام تمارين اللياقة' : 'Cardio days';
  String get cardioMinutesPerSession =>
      isArabic ? 'دقائق لكل حصة' : 'Minutes per session';
  String get cardioMinutesRange => isArabic
      ? 'أدخل عددًا صحيحًا من 1 إلى 600 دقيقة.'
      : 'Enter a whole number from 1 to 600 minutes.';
  String get cardioType => isArabic ? 'نوع تمارين اللياقة' : 'Cardio type';
  String get noCardio => isArabic ? 'بدون' : 'None';
  String get steadyCardio => isArabic ? 'مستمرة' : 'Steady';
  String get intervalCardio => isArabic ? 'متقطعة' : 'Intervals';
  String get customCardioNote => isArabic ? 'ملاحظة مخصصة' : 'Custom note';
  String get customCardioNoteText =>
      isArabic ? 'نص ملاحظة تمارين اللياقة' : 'Custom cardio note';
  String get customCardioNoteRequired =>
      isArabic ? 'أدخل ملاحظة تمارين اللياقة.' : 'Enter a custom cardio note.';
  String get programActions =>
      isArabic ? 'إجراءات البرنامج' : 'Program actions';
  String get programActionsSubtitle => isArabic
      ? 'إدارة البرنامج التدريبي لهذا اللاعب'
      : "Manage this Player's Training program";
  String get importProgramAction => isArabic ? 'استيراد' : 'Import';
  String get downloadProgramTemplateAction =>
      isArabic ? 'تنزيل القالب' : 'Download template';
  String get downloadProgramTemplate =>
      isArabic ? 'تنزيل قالب البرنامج' : 'Download program template';
  String get downloadProgramTemplateCsv =>
      isArabic ? 'تنزيل قالب CSV' : 'Download CSV template';
  String get chooseSpreadsheet =>
      isArabic ? 'اختيار ملف XLSX أو CSV' : 'Choose XLSX or CSV file';
  String get importPrivacyNote => isArabic
      ? 'يُستخدم الملف أو النص لإنشاء مسودة غير منشورة. لن تُرسل بيانات سجل اللاعب التدريبي.'
      : 'The file or pasted text creates an unpublished draft. The player’s Training ledger is not sent.';
  String get chooseSheet => isArabic ? 'اختر ورقة العمل' : 'Choose a sheet';
  String get chooseWeek => isArabic ? 'اختر الأسبوع' : 'Choose a week';
  String get reviewImport => isArabic ? 'مراجعة الاستيراد' : 'Review import';
  String importRowsSummary(int total, int valid) => isArabic
      ? 'الصفوف: ${_ltr('$total')} · الصالحة: ${_ltr('$valid')}'
      : 'Rows: $total · valid: $valid';
  String rowLabel(int row) => isArabic ? 'الصف ${_ltr('$row')}' : 'Row $row';
  String importPrescription(
          String day, int sets, int repsMin, int repsMax, double rir) =>
      isArabic
          ? '$day · ${_ltr('$sets')} مجموعات · ${_ltr('$repsMin-$repsMax')} تكرارات · RIR ${_ltr('$rir')}'
          : '$day · $sets sets · $repsMin-$repsMax reps · RIR $rir';
  String get createImportedDraft =>
      isArabic ? 'إنشاء مسودة البرنامج' : 'Create Program draft';
  String get createAsCoachExercise =>
      isArabic ? 'إنشاء كتمرين من إنشاء المدرب' : 'Create as your exercise';
  String get unresolvedExercise => isArabic
      ? 'اختر تمرينًا لهذه التسمية'
      : 'Choose a match for this exercise';
  String weeksNotImported(List<String> weeks, String? selectedWeek) => isArabic
      ? 'سيتم استيراد ${_ltr(selectedWeek ?? '')} فقط. لم تُستورد هذه الأسابيع: ${_ltr(weeks.join(', '))}.'
      : 'Only ${selectedWeek ?? 'one week'} will be imported. These weeks were not imported: ${weeks.join(', ')}.';
  String importWeeksIncluded(List<String> weeks) => isArabic
      ? 'سيتم استيراد الأسابيع: ${_ltr(weeks.join('، '))}.'
      : 'Weeks to import: ${weeks.join(', ')}.';
  String get importLayoutNeedsConfirmation => isArabic
      ? 'راجع تقسيم الأيام والأسابيع قبل إنشاء المسودة.'
      : 'Review the detected day and week layout before creating the draft.';
  String importLayoutSummary(
    List<String> days,
    List<String> weeks,
    Map<String, List<int>> rowsByWeek,
    List<int> unassigned,
  ) {
    final String dayText = days.isEmpty
        ? (isArabic ? 'غير محددة' : 'none detected')
        : days.join('، ');
    final String weekText = weeks.isEmpty
        ? (isArabic ? 'غير محددة' : 'none detected')
        : weeks.join(', ');
    final String assignments = <String>[
      for (final String week in weeks)
        isArabic
            ? '${_ltr(week)}: الصفوف ${_ltr((rowsByWeek[week] ?? <int>[]).join(', '))}'
            : '$week: rows ${(rowsByWeek[week] ?? <int>[]).join(', ')}',
      if (unassigned.isNotEmpty)
        isArabic
            ? 'غير محدد: الصفوف ${_ltr(unassigned.join(', '))}'
            : 'Unassigned: rows ${unassigned.join(', ')}',
    ].join(' · ');
    return isArabic
        ? 'الأيام المكتشفة: $dayText. الأسابيع المكتشفة: ${_ltr(weekText)}. توزيع الصفوف: ${assignments.isEmpty ? 'لا توجد صفوف' : assignments}.'
        : 'Days found: $dayText. Weeks found: $weekText. Row assignments: ${assignments.isEmpty ? 'no rows' : assignments}.';
  }

  String get confirmLayoutAndContinue =>
      isArabic ? 'تأكيد ومتابعة' : 'Confirm and continue';
  String get layoutNotRight => isArabic ? 'التنسيق غير صحيح' : 'Not right';
  String get layoutNotRightGuidance => isArabic
      ? 'ألغِ هذا الاستيراد وعدّل الورقة أو اختر ورقة عمل أخرى.'
      : 'Import cancelled. Adjust the sheet or choose another tab before trying again.';
  String get chooseAnotherSheet =>
      isArabic ? 'اختر ورقة عمل أخرى' : 'Choose another sheet';
  String get readAnotherSheet =>
      isArabic ? 'قراءة الورقة الأخرى' : 'Read another sheet';
  String get importLayoutConfirmTitle =>
      isArabic ? 'تأكيد تنسيق البرنامج' : 'Confirm the program layout';
  String get importNoValidRows => isArabic
      ? 'لا توجد صفوف صالحة للاستيراد بعد.'
      : 'There are no valid rows ready to import.';
  String programImportRowMessage(String code, int row, String column) =>
      _programImportPositionMessage(code, column, rowLabel(row));

  String programImportLineMessage(String code, int line, String column) =>
      _programImportPositionMessage(code, column, lineLabel(line));

  String _programImportPositionMessage(
      String code, String column, String positionLabel) {
    final String columnLabel = _importColumn(column);
    final String fallback =
        const MessageCopy('en').programImportMessage(code) ??
            (isArabic
                ? 'راجع هذه القيمة وصححها في المصدر.'
                : 'Review this value and correct it in the source.');
    final String explanation = resolveStructuredMessage(
      messageCode: code,
      messageParams: const <String, dynamic>{},
      englishFallback: fallback,
      displayLanguage: languageCode,
    );
    return '$positionLabel · $columnLabel: $explanation';
  }

  String get importReplaceTitle => isArabic
      ? 'استبدال مسودة البرنامج الحالية؟'
      : 'Replace the current Program draft?';
  String get importReplacePrompt => isArabic
      ? 'سيؤدي الاستيراد إلى استبدال المسودة الحالية وتعديلاتها المحفوظة.'
      : 'Importing will replace the current draft and its saved edits.';
  String get importReplaceAction =>
      isArabic ? 'استبدال المسودة' : 'Replace draft';
  String get importTemplateSaved => isArabic
      ? 'تم تجهيز قالب البرنامج للتنزيل.'
      : 'The Program template is ready to download.';
  String get importCancelled => isArabic ? 'إلغاء' : 'Cancel';
  String get importCreateFailure => isArabic
      ? 'تعذر إنشاء مسودة البرنامج من هذا الاستيراد.'
      : 'Could not create a Program draft from this import.';
  String programImportError(String? code,
      {Map<String, dynamic>? messageParams}) {
    if (code == 'assignment.program_draft_exists.v1') {
      return importReplacePrompt;
    }
    if (code == null) return importCreateFailure;
    final String? englishFallback =
        const MessageCopy('en').programImportMessage(
      code,
      maxCells: messageParams?['max_cells'] as int?,
    );
    if (englishFallback == null) return importCreateFailure;
    return resolveStructuredMessage(
      messageCode: code,
      messageParams: messageParams ?? const <String, dynamic>{},
      englishFallback: englishFallback,
      displayLanguage: languageCode,
    );
  }

  String _importColumn(String column) => switch (column) {
        'reps' => isArabic ? 'التكرارات' : 'reps',
        'rir' => 'RIR',
        'rpe' => 'RPE',
        'sets' => isArabic ? 'المجموعات' : 'sets',
        'load_kg' || 'load_pct_e1rm' => isArabic ? 'الحمل' : 'load',
        'week' => isArabic ? 'الأسبوع' : 'week',
        'day' => isArabic ? 'اليوم' : 'day',
        'day_name' => isArabic ? 'اسم اليوم' : 'day name',
        'order' => isArabic ? 'الترتيب' : 'order',
        'exercise' => isArabic ? 'التمرين' : 'exercise',
        'rest_seconds' => isArabic ? 'الراحة بالثواني' : 'rest',
        'tempo' => isArabic ? 'إيقاع الحركة' : 'tempo',
        'notes' => isArabic ? 'الملاحظات' : 'notes',
        _ => isArabic ? 'القيمة' : 'value',
      };
  // #433 English and Arabic display-language copy for pasted text import.
  String get programImportTitle =>
      isArabic ? 'استيراد برنامج تدريبي' : 'Import program';
  String get chooseProgramFileWithText =>
      isArabic ? 'اختيار ملف XLSX أو CSV أو TXT' : 'Choose XLSX, CSV or TXT file';
  String get uploadProgramFile => isArabic ? 'رفع ملف' : 'Upload file';
  String get pasteProgram => isArabic ? 'لصق البرنامج' : 'Paste program';
  String get pasteOnlyProgramReminder => isArabic
      ? 'الصق البرنامج فقط — دون أسماء أو أرقام هواتف أو محادثات.'
      : 'Paste only the program — no names, phone numbers or chat.';
  String programImportCharacterCount(int count, int limit) => isArabic
      ? '${_count(count, ArabicCountNoun.character)} / ${_count(limit, ArabicCountNoun.character)}'
      : '${_groupCount(count)} / ${_groupCount(limit)} characters';
  String programImportOverLimit(int limit) => isArabic
      ? 'اختصر النص إلى ${_count(limit, ArabicCountNoun.character)} كحد أقصى.'
      : 'Shorten the text to ${_groupCount(limit)} characters or fewer.';
  String lineLabel(int line) =>
      isArabic ? 'السطر ${_ltr('$line')}' : 'Line $line';

  String get generate => isArabic ? 'إنشاء' : 'Generate';
  String get split => isArabic ? 'التقسيمة' : 'Split';
  String splitOptionName(String splitId, int days, String fallback) {
    if (!isArabic) return fallback;
    return switch (splitId) {
      'auto' => days == 1 ? 'تلقائي (كامل الجسم)' : 'تلقائي',
      'full_body' => 'كامل الجسم',
      'upper_lower' => days == 3
          ? 'علوي / سفلي / علوي'
          : days == 5
              ? 'علوي / سفلي ×2 + علوي'
              : 'علوي / سفلي',
      'anterior_posterior' => 'أمامي / خلفي',
      'ppl' || 'ppl_x_ul' => splitId == 'ppl' ? 'PPL' : 'PPL × UL',
      'arnold' => 'أرنولد',
      'arnold_x_ul' => 'أرنولد × علوي / سفلي',
      _ => fallback,
    };
  }

  String get repRangePreference =>
      isArabic ? 'تفضيل نطاق التكرارات' : 'Rep range preference';
  String get replaceProgramDraftTitle => isArabic
      ? 'استبدال مسودة البرنامج التدريبي الحالية؟'
      : 'Replace the current Program draft?';
  String get replaceProgramDraftPrompt => isArabic
      ? 'سيؤدي إنشاء مسودة جديدة إلى استبدال مسودة البرنامج التدريبي الحالية، بما فيها أيامها. هل تريد المتابعة؟'
      : 'Generating a new draft will replace the current Program draft, including its days. Continue?';
  String get replaceProgramDraftAction =>
      isArabic ? 'استبدال المسودة' : 'Replace draft';
  String get program => isArabic ? 'البرنامج التدريبي' : 'Program';
  String get generatedAutomatically =>
      isArabic ? 'تم إنشاؤه تلقائيًا' : 'Generated automatically';
  String get publishedByYou => isArabic ? 'نشرته أنت' : 'Published by you';
  String get editedByPlayer =>
      isArabic ? 'عدّله اللاعب' : 'Edited by the player';
  String get pendingProgramDraft =>
      isArabic ? 'مسودة بانتظار المراجعة' : 'Draft pending';
  String programVersionChip(int version) =>
      isArabic ? 'إصدار ${_ltr('$version')}' : 'v$version';
  String get activeProgramStatus => isArabic ? 'نشط' : 'Active';
  String get trainingDaysSummary => isArabic ? 'أيام التدريب' : 'Training days';
  String get totalExercisesSummary =>
      isArabic ? 'إجمالي التمارين' : 'Total exercises';
  String get workingSetsSummary =>
      isArabic ? 'مجموعات التدريب' : 'Working sets';
  String programStatSemantics(int count, String label) =>
      isArabic ? '${_ltr('$count')} $label' : '$count $label';
  String get programNumberColumn => '#';
  String get programExerciseColumn => isArabic ? 'التمرين' : 'Exercise';
  String get programActionColumn => isArabic ? 'الحركة' : 'Action';
  String programActionDetail(String action) =>
      isArabic ? 'الحركة: $action' : 'Action: $action';
  String get programEquipmentColumn => isArabic ? 'المعدات' : 'Equipment';
  String get programSetsColumn => isArabic ? 'المجموعات' : 'Sets';
  String get programRepsColumn => isArabic ? 'التكرارات' : 'Reps';
  String get programRirColumn => 'RIR';
  String get programRestColumn => isArabic ? 'الراحة' : 'Rest';
  String programSetsCell(int sets, int warmupSets) {
    if (warmupSets == 0) return isArabic ? _ltr('$sets') : '$sets';
    final String value = isArabic
        ? '$sets (+$warmupSets إحماء)'
        : '$sets (+$warmupSets warm-up)';
    return isArabic ? _ltr(value) : value;
  }

  String programExerciseRepRange(int minimum, int maximum) {
    final String value =
        minimum == maximum ? '$minimum' : '$minimum – $maximum';
    return isArabic ? _ltr(value) : value;
  }

  String programRirCell(String label) => isArabic ? _ltr(label) : label;

  String programEquipmentValue(String equipment) =>
      isArabic ? _ltr(equipment) : equipment;

  String get missingProgramEquipment => '—';
  String get programDetailSeparator => ' · ';

  String programDaySummary(int exerciseCount, int setCount) => isArabic
      ? '${_count(exerciseCount, ArabicCountNoun.exercise)} • ${_count(setCount, ArabicCountNoun.trainingSet)}'
      : '$exerciseCount ${exerciseCount == 1 ? 'exercise' : 'exercises'} • $setCount ${setCount == 1 ? 'working set' : 'working sets'}';

  String showRemainingProgramExercises(int count) {
    if (!isArabic) {
      return 'Show remaining $count ${count == 1 ? 'exercise' : 'exercises'}';
    }
    final String suffix = switch (count) {
      1 => ' إضافي',
      2 => ' إضافيان',
      >= 3 && <= 10 => ' إضافية',
      _ => ' إضافيًا',
    };
    return 'عرض ${_count(count, ArabicCountNoun.exercise)}$suffix';
  }

  String compactProgramPrescription(
          ({
            String sets,
            String reps,
            String rir,
            String rest,
            String equipment
          }) prescription) =>
      isArabic
          ? '${_ltr(prescription.sets)} × ${_ltr(prescription.reps)} · '
              'RIR ${_ltr(prescription.rir)} · ${prescription.rest} · '
              '${prescription.equipment}'
          : '${prescription.sets} × ${prescription.reps} · '
              'RIR ${prescription.rir} · ${prescription.rest} · '
              '${prescription.equipment}';

  String get noActiveProgram =>
      isArabic ? 'لا يوجد برنامج تدريبي نشط.' : 'No active program.';
  String get editActiveProgram => isArabic ? 'تعديل' : 'Edit';
  String get approveProgramAsIs =>
      isArabic ? 'اعتماد البرنامج كما هو' : 'Approve as is';
  String get programDraftChoiceTitle => isArabic
      ? 'توجد مسودة للبرنامج التدريبي'
      : 'A Program draft already exists';
  String get programDraftChoicePrompt => isArabic
      ? 'يمكنك متابعة المسودة الحالية أو استبدالها بنسخة من البرنامج النشط.'
      : 'Continue the current draft or replace it with a copy of the active program.';
  String get continueProgramDraft =>
      isArabic ? 'متابعة المسودة' : 'Continue draft';
  String get replaceDraftWithActiveProgram =>
      isArabic ? 'استبدالها بالبرنامج النشط' : 'Replace with active program';
  String get confirmApproveProgramTitle =>
      isArabic ? 'اعتماد البرنامج كما هو؟' : 'Approve the current program?';
  String get approveProgramAsIsPrompt => isArabic
      ? 'سيُنشر البرنامج النشط كما هو بإصدار جديد. سيبدأ تطبيقه من الحصة التدريبية التالية للاعب.'
      : 'This publishes the active program unchanged as a new version. It applies from the player’s next workout.';
  String get confirmApproveProgram =>
      isArabic ? 'اعتماد ونشر' : 'Approve and publish';
  String get publishRequestsWillBeAddressed => isArabic
      ? 'يمكنك اختيار الطلبات التي عالجها البرنامج التدريبي الجديد.'
      : 'Choose which requests the new Training program addresses.';
  String get publishRequestResolveLabel =>
      isArabic ? 'معالجة الطلب' : 'Resolve';
  String publishRequestKind(String kind) => switch (kind) {
        'exercise_substitution' =>
          isArabic ? 'طلب تبديل تمرين من المدرب' : 'Substitution request',
        _ =>
          isArabic ? 'طلب تغيير البرنامج التدريبي' : 'Program change request',
      };
  String publishRequestDetails(String? exercise, String date) {
    final String dateText = _ltr(date);
    final String dateLabel =
        isArabic ? 'التاريخ: $dateText' : 'Date: $dateText';
    if (exercise == null || exercise.isEmpty) return dateLabel;
    return '$exercise · $dateLabel';
  }

  String activeProgramSince(String date) =>
      isArabic ? 'بدأ البرنامج في ${_ltr(date)}' : 'Active since $date';
  String programTempo(String tempo) =>
      isArabic ? 'الإيقاع: ${_ltr(tempo)}' : 'Tempo: $tempo';
  String programNotes(String notes) =>
      isArabic ? 'ملاحظات: $notes' : 'Notes: $notes';
  String get writeProgram =>
      isArabic ? 'اكتب برنامجًا تدريبيًا' : 'Write program';
  String get firstWeekName => isArabic ? 'الأسبوع 1' : 'Week 1';
  String weekNameNumber(int number) =>
      isArabic ? 'الأسبوع ${_ltr('$number')}' : 'Week $number';
  String weekTabLabel(int number, String name) =>
      isArabic ? '${_ltr('$number')} · $name' : '$number · $name';
  String get trainingDay => isArabic ? 'يوم التدريب' : 'Training day';
  String get firstTrainingDay => isArabic ? 'اليوم 1' : 'Day 1';
  String get customProgram =>
      isArabic ? 'برنامج تدريبي مخصص' : 'Custom program';
  String get dayName => isArabic ? 'اسم اليوم' : 'Day name';
  String get weekName => isArabic ? 'اسم الأسبوع' : 'Week name';
  String get addWeek => isArabic ? 'إضافة أسبوع' : 'Add week';
  String get duplicateWeek => isArabic ? 'نسخ الأسبوع' : 'Duplicate week';
  String get removeWeek => isArabic ? 'حذف الأسبوع' : 'Remove week';
  String get moveWeekUp => isArabic ? 'نقل الأسبوع لأعلى' : 'Move week up';
  String get moveWeekDown => isArabic ? 'نقل الأسبوع لأسفل' : 'Move week down';
  String trainingDayNumber(int number) =>
      isArabic ? 'يوم التدريب ${_ltr('$number')}' : 'Training day $number';
  String dayDuplicateName(String name) =>
      isArabic ? '$name (نسخة)' : '$name copy';
  String get addDay => isArabic ? 'إضافة يوم تدريب' : 'Add training day';
  String get duplicateDay => isArabic ? 'نسخ يوم التدريب' : 'Duplicate day';
  String get removeDay => isArabic ? 'حذف يوم التدريب' : 'Remove day';
  String get moveDayUp => isArabic ? 'نقل اليوم لأعلى' : 'Move day up';
  String get moveDayDown => isArabic ? 'نقل اليوم لأسفل' : 'Move day down';
  String get duplicateExerciseAction => isArabic ? 'نسخ التمرين' : 'Duplicate';
  String get swapExercise => isArabic ? 'تبديل التمرين' : 'Swap exercise';
  String get insertExerciseAbove =>
      isArabic ? 'إضافة تمرين قبل' : 'Insert exercise above';
  String get insertExerciseBelow =>
      isArabic ? 'إضافة تمرين بعد' : 'Insert exercise below';
  String get deleteExercise => isArabic ? 'حذف التمرين' : 'Delete';
  String get exerciseActions =>
      isArabic ? 'إجراءات التمرين' : 'Exercise actions';
  String get reorderExercise =>
      isArabic ? 'إعادة ترتيب التمرين' : 'Reorder exercise';
  String get addWarmupMovement =>
      isArabic ? 'إضافة حركة إحماء' : 'Add warm-up movement';
  String get removeWarmupMovement =>
      isArabic ? 'حذف حركة الإحماء' : 'Remove warm-up movement';
  String get insertWarmupAbove =>
      isArabic ? 'إضافة حركة إحماء قبل' : 'Insert above';
  String get insertWarmupBelow =>
      isArabic ? 'إضافة حركة إحماء بعد' : 'Insert below';
  String get warmupMovementActions =>
      isArabic ? 'إجراءات حركة الإحماء' : 'Warm-up movement actions';
  String get moveWarmupMovementUp =>
      isArabic ? 'نقل حركة الإحماء لأعلى' : 'Move warm-up movement up';
  String get moveWarmupMovementDown =>
      isArabic ? 'نقل حركة الإحماء لأسفل' : 'Move warm-up movement down';
  String get warmupMovementName =>
      isArabic ? 'اسم حركة الإحماء' : 'Warm-up movement';
  String get movementSets => isArabic ? 'المجموعات' : 'Sets';
  String get movementReps => isArabic ? 'التكرارات' : 'Reps';
  String get restSeconds => isArabic ? 'الراحة بالثواني' : 'Rest (seconds)';
  String get rampedWarmupSets => isArabic
      ? 'مجموعات الإحماء المتدرجة (${_ltr('${ProgramDraftPrescription.minWarmupSets}')}–${_ltr('${ProgramDraftPrescription.maxWarmupSets}')})'
      : 'Ramped warm-up sets (${ProgramDraftPrescription.minWarmupSets}–${ProgramDraftPrescription.maxWarmupSets})';
  String get tempo => isArabic ? 'الإيقاع (اختياري)' : 'Tempo (optional)';
  String get notesOptional =>
      isArabic ? 'ملاحظات (اختيارية)' : 'Notes (optional)';
  String get leaveUnsavedChangesTitle =>
      isArabic ? 'تغييرات غير محفوظة' : 'Unsaved changes';
  String get leaveUnsavedChangesPrompt => isArabic
      ? 'هل تريد مغادرة محرر البرنامج دون حفظ التغييرات؟'
      : 'Leave the program editor without saving your changes?';
  String get leaveWithoutSaving => isArabic ? 'مغادرة' : 'Leave';
  String get invalidWarmupSets => isArabic
      ? 'يجب أن تكون مجموعات الإحماء من ${_ltr('${ProgramDraftPrescription.minWarmupSets}')} إلى ${_ltr('${ProgramDraftPrescription.maxWarmupSets}')}.'
      : 'Warm-up sets must be from ${ProgramDraftPrescription.minWarmupSets} to ${ProgramDraftPrescription.maxWarmupSets}.';
  String get invalidMovementSets => isArabic
      ? 'تحتاج حركة الإحماء إلى ${_ltr('${ProgramDraftPrescription.minWarmupMovementSets}')} إلى ${_ltr('${ProgramDraftPrescription.maxWarmupMovementSets}')} مجموعات.'
      : 'Warm-up movements need ${ProgramDraftPrescription.minWarmupMovementSets} to ${ProgramDraftPrescription.maxWarmupMovementSets} sets.';
  String get invalidMovementReps => isArabic
      ? 'يجب أن تكون تكرارات حركة الإحماء من ${_ltr('${ProgramDraftPrescription.minWarmupMovementReps}')} إلى ${_ltr('${ProgramDraftPrescription.maxWarmupMovementReps}')}.'
      : 'Warm-up movement reps must be from ${ProgramDraftPrescription.minWarmupMovementReps} to ${ProgramDraftPrescription.maxWarmupMovementReps}.';
  String get invalidProgramDays => isArabic
      ? 'يجب أن يكون عدد أيام التدريب من ${_ltr('1')} إلى ${_ltr('${ProgramDraftPrescription.maxDays}')}.'
      : 'A program must have 1 to ${ProgramDraftPrescription.maxDays} training days.';
  String get tempoTooLong => isArabic
      ? 'يجب ألا يتجاوز الإيقاع ${_ltr('${ProgramDraftPrescription.maxTempoLength}')} حرفًا.'
      : 'Tempo must be at most ${ProgramDraftPrescription.maxTempoLength} characters.';
  String get notesTooLong => isArabic
      ? 'يجب ألا تتجاوز الملاحظات ${_ltr('${ProgramDraftPrescription.maxProgramNotesLength}')} حرفًا.'
      : 'Notes must be at most ${ProgramDraftPrescription.maxProgramNotesLength} characters.';
  String get cardioNote =>
      isArabic ? 'ملاحظة اللياقة (اختيارية)' : 'Cardio note (optional)';
  String get noTrainingDays => isArabic
      ? 'أضف يوم تدريب لبدء البرنامج.'
      : 'Add a training day to start the program.';
  String get invalidWholeNumber =>
      isArabic ? 'أدخل عددًا صحيحًا.' : 'Enter a whole number.';
  String get addExercise => isArabic ? 'إضافة تمرين' : 'Add exercise';
  String get createExercise => isArabic ? 'إنشاء تمرين' : 'Create exercise';
  String get yourExercise => isArabic ? 'تمرينك' : 'Your exercise';
  String get noMatchingExercise =>
      isArabic ? 'لا توجد تمارين مطابقة.' : 'No matching exercises.';
  String get exerciseName => isArabic ? 'اسم التمرين' : 'Exercise name';
  String get bodyPartTag => isArabic
      ? 'العضلة أو الجزء المستهدف (اختياري)'
      : 'Body part tag (optional)';
  String get equipmentTag =>
      isArabic ? 'المعدات (اختياري)' : 'Equipment tag (optional)';
  String get exerciseNoteOptional =>
      isArabic ? 'ملاحظة (اختيارية)' : 'Note (optional)';
  String get videoLinkOptional =>
      isArabic ? 'رابط الفيديو (اختياري)' : 'Video link (optional)';
  String get exerciseNameRequired =>
      isArabic ? 'أدخل اسم التمرين.' : 'Enter an exercise name.';
  String get videoLinkMustUseHttps => isArabic
      ? 'يجب أن يبدأ رابط الفيديو بـ https.'
      : 'The video link must use https.';
  String get saveExercise => isArabic ? 'حفظ التمرين' : 'Save exercise';
  String get workingSets => isArabic ? 'مجموعات التدريب' : 'Working sets';
  String get repsOrRange => isArabic ? 'التكرارات أو النطاق' : 'Reps or range';
  String get targetRir => isArabic ? 'RIR المستهدف' : 'Target RIR';
  String get saveDraft => isArabic ? 'حفظ المسودة' : 'Save draft';
  String get publishDraft => isArabic ? 'نشر البرنامج' : 'Publish program';
  String get confirmPublishDraft => isArabic
      ? 'نشر البرنامج التدريبي للاعب الآن؟ سيصبح البرنامج النشط.'
      : 'Publish this Training program now? It will become the active program.';
  String get discardDraft => isArabic ? 'حذف المسودة' : 'Discard draft';
  String get confirmDiscardDraft => isArabic
      ? 'حذف مسودة البرنامج التدريبي؟ لا يمكن التراجع عن ذلك.'
      : 'Discard this Program draft? This cannot be undone.';
  String get draftSaved => isArabic ? 'تم حفظ المسودة.' : 'Draft saved.';
  String get programTemplates =>
      isArabic ? 'قوالب البرامج التدريبية' : 'Program templates';
  String get programTemplatesLead => isArabic
      ? 'أنشئ قوالب برامج تدريبية قابلة لإعادة الاستخدام وعدّلها وانسخها وأرشفها.'
      : 'Build reusable Training program templates, then edit, duplicate or archive them.';
  String get noProgramTemplates => isArabic
      ? 'لا توجد قوالب برامج تدريبية بعد.'
      : 'No Program templates yet.';
  String get newProgramTemplate => isArabic ? 'قالب جديد' : 'New template';
  String get editProgramTemplate => isArabic ? 'تعديل القالب' : 'Edit template';
  String get writeTemplate => isArabic ? 'تحرير القالب' : 'Write template';
  String get templateName => isArabic ? 'اسم القالب' : 'Template name';
  String get templateDescription =>
      isArabic ? 'الوصف (اختياري)' : 'Description (optional)';
  String get templateNameRequired =>
      isArabic ? 'أدخل اسم القالب.' : 'Enter a template name.';
  String get saveTemplate => isArabic ? 'حفظ القالب' : 'Save template';
  String get saveAsTemplate => isArabic ? 'حفظ كقالب' : 'Save as template';
  String get saveAsTemplateNotesNotice => isArabic
      ? 'راجع ملاحظات التمارين وتعليمات البرنامج ووصفات تمارين اللياقة قبل الحفظ. لن يُحفظ النص إلا إذا أبقيته أو عدّلته.'
      : 'Review exercise notes, program instructions, and cardio prescriptions before saving. Text is copied only if you keep or edit it.';
  String get saveAsTemplateNotesHeading =>
      isArabic ? 'مراجعة النصوص والوصفات' : 'Review notes and prescriptions';
  String get saveAsTemplateNoNotes => isArabic
      ? 'لا توجد ملاحظات أو وصفات نصية لمراجعتها.'
      : 'There are no notes or text prescriptions to review.';
  String get programInstructions =>
      isArabic ? 'تعليمات البرنامج' : 'Program instructions';
  String get cardioPrescription =>
      isArabic ? 'وصفة تمارين اللياقة' : 'Cardio prescription';
  String get templateSaved => isArabic ? 'تم حفظ القالب.' : 'Template saved.';
  String get duplicateTemplate => isArabic ? 'نسخ' : 'Duplicate';
  String templateDuplicated(String name) =>
      isArabic ? 'تم نسخ ${_ltr(name)}.' : 'Duplicated $name.';
  String get archiveTemplate => isArabic ? 'أرشفة' : 'Archive';
  String get unarchiveTemplate => isArabic ? 'إلغاء الأرشفة' : 'Unarchive';
  String get templateArchived =>
      isArabic ? 'تمت أرشفة القالب.' : 'Template archived.';
  String get templateUnarchived =>
      isArabic ? 'تم إلغاء أرشفة القالب.' : 'Template unarchived.';
  String get archivedTemplates =>
      isArabic ? 'القوالب المؤرشفة' : 'Archived templates';
  String get showArchivedTemplates =>
      isArabic ? 'عرض المؤرشفة' : 'Show archived';
  String get hideArchivedTemplates =>
      isArabic ? 'إخفاء المؤرشفة' : 'Hide archived';
  String get assignTemplate => isArabic ? 'إسناد للاعبين' : 'Assign to players';
  String assignTemplateTitle(String name) => isArabic
      ? 'إسناد ${_ltr(name)}'
      : 'Assign $name';
  String get assignTemplateLead => isArabic
      ? 'اختر اللاعبين الذين سيتلقون نسخة مستقلة. يمكنك تعديل كل نسخة على حدة.'
      : 'Choose players to receive an independent copy. The coach can customise each copy.';
  String get existingDraftReplace => isArabic ? 'استبدال المسودة' : 'Replace draft';
  String get existingDraftKeep => isArabic ? 'تخطي المسودة الحالية' : 'Skip if a draft exists';
  String get assignSelectedPlayers => isArabic ? 'إسناد' : 'Assign';
  String get templateAssignmentResults => isArabic ? 'نتائج الإسناد' : 'Assignment results';
  String get templatePublishResults => isArabic ? 'نتائج النشر' : 'Publish results';
  String get customizeDraft => isArabic ? 'تعديل المسودة' : 'Customize draft';
  String get unknownPlayer => isArabic ? 'لاعب غير معروف' : 'Unknown player';
  String templatePlayerResult(String name, String status) {
    final String state = switch (status) {
      'assigned' => isArabic ? 'أُسندت المسودة' : 'Draft assigned',
      'replaced' => isArabic ? 'استُبدلت المسودة' : 'Draft replaced',
      'skipped' => isArabic ? 'أُبقيت المسودة الحالية' : 'Existing draft kept',
      'published' => isArabic ? 'نُشر البرنامج' : 'Program published',
      'invalid' => isArabic ? 'المسودة غير صالحة' : 'Draft needs correction',
      'no_draft' => isArabic ? 'لا توجد مسودة' : 'No draft found',
      _ => isArabic ? 'تعذر إكمال العملية' : 'Could not complete',
    };
    return isArabic ? '${_ltr(name)}: $state' : '$name: $state';
  }
  String resolvedProgramRequests(int count) => isArabic
      ? 'طلبات البرنامج التي حُلّت: ${_ltr(count.toString())}'
      : 'Program requests resolved: $count';
  String templateResultMessage(String code, String fallback) => switch (code) {
        'assignment.none_active.v1' => isArabic ? 'لا توجد علاقة تدريب نشطة.' : 'No active assignment.',
        'assignment.program_draft_not_found.v1' => isArabic ? 'لا توجد مسودة برنامج.' : 'Program draft not found.',
        'assignment.program_draft_changed.v1' => isArabic ? 'تغيرت المسودة قبل النشر.' : 'The draft changed before publication.',
        'program_request.selection_invalid.v1' => isArabic ? 'تعذر التحقق من طلبات البرنامج.' : 'Program requests could not be verified.',
        _ => fallback,
      };
  String get noPlayersToAssign =>
      isArabic ? 'لا يوجد لاعبون معينون بعد.' : 'No assigned players yet.';
  String templateAssignSummary(int assigned, int replaced, int skipped, int rejected) =>
      isArabic
          ? 'أُسند: ${_ltr(assigned.toString())} · استُبدل: ${_ltr(replaced.toString())} · بقي: ${_ltr(skipped.toString())} · رُفض: ${_ltr(rejected.toString())}'
          : 'Assigned: $assigned · Replaced: $replaced · Kept: $skipped · Rejected: $rejected';
  String get publishAll => isArabic ? 'نشر الكل' : 'Publish all';
  String get confirmPublishAll => isArabic
      ? 'نشر برامج اللاعبين المحددين الآن؟ سيصبح برنامج كل لاعب هو البرنامج النشط.'
      : "Publish each selected player's Program now? It will become their active program.";
  String publishAllSummary(int published, int invalid, int noDraft, int rejected) =>
      isArabic
          ? 'نُشر: ${_ltr(published.toString())} · غير صالح: ${_ltr(invalid.toString())} · بلا مسودة: ${_ltr(noDraft.toString())} · رُفض: ${_ltr(rejected.toString())}'
          : 'Published: $published · Invalid: $invalid · No draft: $noDraft · Rejected: $rejected';
  String fromTemplate(String name) =>
      isArabic ? 'من القالب: ${_ltr(name)}' : 'From template: $name';
  String get invalidSetCount => isArabic
      ? 'أدخل مجموعة تدريب واحدة على الأقل لكل تمرين.'
      : 'Enter at least one working set for each exercise.';
  String get invalidRepTarget => isArabic
      ? 'أدخل عددًا من ${_ltr('${ProgramDraftPrescription.minReps}')} إلى ${_ltr('${ProgramDraftPrescription.maxReps}')} أو نطاقًا مثل 6-8.'
      : 'Enter ${ProgramDraftPrescription.minReps}–${ProgramDraftPrescription.maxReps} reps or a range such as 6-8.';
  String get invalidRirTarget => isArabic
      ? 'يجب أن يكون RIR المستهدف بين ${_ltr('${ProgramDraftPrescription.minRir.toInt()}')} و${_ltr('${ProgramDraftPrescription.maxRir.toInt()}')}.'
      : 'Target RIR must be from ${ProgramDraftPrescription.minRir.toInt()} to ${ProgramDraftPrescription.maxRir.toInt()}.';
  String programDraftValidationMessage(String code) => switch (code) {
        'invalid_sets' => invalidSetCount,
        'invalid_reps' => invalidRepTarget,
        'invalid_rir' => invalidRirTarget,
        'unknown_exercise' => isArabic
            ? 'اختر تمرينًا من مكتبة التمارين.'
            : 'Choose an exercise from the Exercise library.',
        'empty_day' => isArabic
            ? 'أضف تمرينًا واحدًا على الأقل إلى يوم التدريب.'
            : 'Add at least one exercise to this training day.',
        'too_many_exercises' => isArabic
            ? 'يمكن أن يحتوي يوم التدريب على 14 تمرينًا كحد أقصى.'
            : 'A training day can have at most 14 exercises.',
        'invalid_warmup_sets' => invalidWarmupSets,
        'invalid_warmup_reps' => isArabic
            ? 'يجب أن تكون تكرارات الإحماء من ${_ltr('${ProgramDraftPrescription.minWarmupMovementReps}')} إلى ${_ltr('${ProgramDraftPrescription.maxWarmupMovementReps}')}'
            : 'Warm-up reps must be from ${ProgramDraftPrescription.minWarmupMovementReps} to ${ProgramDraftPrescription.maxWarmupMovementReps}.',
        'invalid_movement_sets' => invalidMovementSets,
        'invalid_movement_reps' => invalidMovementReps,
        'tempo_too_long' => tempoTooLong,
        'notes_too_long' => notesTooLong,
        'invalid_day_order' ||
        'invalid_weekly_frequency' ||
        'too_many_days' =>
          invalidProgramDays,
        _ => isArabic
            ? 'راجع هذا الحقل في البرنامج التدريبي.'
            : 'Check this Training program field.',
      };
  String get low => isArabic ? 'منخفض' : 'Low';
  String get balanced => isArabic ? 'متوازن' : 'Balanced';
  String get high => isArabic ? 'مرتفع' : 'High';
  String get daysPerWeek =>
      isArabic ? 'أيام التدريب أسبوعيًا' : 'Days per week';
  String get publish => isArabic ? 'نشر' : 'Publish';
  String programPublished(int? version, {int resolvedRequestCount = 0}) {
    final String published = isArabic
        ? 'نُشر إصدار البرنامج التدريبي ${_ltr('$version')}'
        : 'Published program version $version';
    if (resolvedRequestCount == 0) return published;
    final String addressed = isArabic
        ? 'تمت معالجة ${requestsCount(resolvedRequestCount)}'
        : 'Resolved ${requestsCount(resolvedRequestCount)}';
    return '$published · $addressed';
  }

  String get programRequests =>
      isArabic ? 'طلبات البرنامج التدريبي' : 'Program requests';
  String get noProgramRequests => isArabic
      ? 'لا توجد طلبات للبرنامج التدريبي بعد.'
      : 'No program requests yet.';
  String get noRecordedVolume =>
      isArabic ? 'لم تُسجل مجموعات تدريب بعد.' : 'No volume recorded yet.';
  String get trainingSchedule =>
      isArabic ? 'جدول التدريب' : 'Training schedule';
  String get expected => isArabic ? 'أيام التدريب المتوقعة' : 'Expected';
  String timezone(String value) =>
      isArabic ? 'المنطقة الزمنية: ${_ltr(value)}' : 'Timezone: $value';
  String pauseDates(String start, String end) => isArabic
      ? 'توقف التدريب: ${_ltr(start)} → ${_ltr(end)}'
      : 'Pause: $start → $end';
  String get latestSession => isArabic ? 'أحدث حصة تدريبية' : 'Latest session';
  String get recentSessions => isArabic ? 'الحصص الأخيرة' : 'Recent sessions';
  String get noSessions =>
      isArabic ? 'لم تُسجل حصص بعد.' : 'No sessions logged yet.';
  String sessionTotals(int sets, String volume) => isArabic
      ? '${_count(sets, ArabicCountNoun.trainingSet)} · إجمالي الوزن المرفوع ${_ltr('$volume kg')}'
      : '$sets sets · $volume kg';
  String warmupMovements(int count) => isArabic
      ? 'حركات الإحماء: ${_count(count, ArabicCountNoun.warmupMovement)}'
      : 'Warm-up: $count movements';
  String cardioMinutes(int? minutes) {
    if (!isArabic) return 'Cardio: $minutes min';
    return 'تمارين اللياقة: ${minutes == null ? 'غير محددة' : _count(minutes, ArabicCountNoun.minute)}';
  }

  String readiness(int score) =>
      isArabic ? 'الاستعداد ${_ltr('$score/5')}' : 'Readiness $score/5';
  String divergence(String kind, String exercise) {
    final String label = switch (kind) {
      'Skipped' => isArabic ? 'تم تخطيه' : 'Skipped',
      'Unplanned' => isArabic ? 'غير مخطط' : 'Unplanned',
      _ => kind,
    };
    return isArabic ? '$label: ${_ltr(exercise)}' : '$label: $exercise';
  }

  String get noPersonalRecords =>
      isArabic ? 'لا توجد أرقام قياسية شخصية بعد.' : 'No personal records yet.';
  String get checkpoints => isArabic ? 'محطات التقدم' : 'Checkpoints';
  String get noCheckpoints =>
      isArabic ? 'لا توجد محطات تقدم بعد.' : 'No Checkpoints yet.';
  String checkpointNumber(int number) =>
      MyosCopy(languageCode).checkpointAt(number);
  String checkpointPeriod(String start, String end) =>
      isArabic ? '${_ltr(start)} – ${_ltr(end)}' : '$start – $end';
  String recordHistory(String type, String value, int reps, String date) {
    final String label = recordTypeLabel(type);
    if (PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps) {
      return isArabic
          ? '$label · ${_count(reps, ArabicCountNoun.repetition)} (${_ltr(date)})'
          : '$label · ${_englishRepetitions(reps)} ($date)';
    }
    return isArabic
        ? '${_ltr(label)} · ${_ltr('$value kg')} × '
            '${_count(reps, ArabicCountNoun.repetition)} (${_ltr(date)})'
        : '$label · $value kg × ${_englishRepetitions(reps)} ($date)';
  }

  String weekday(int weekday) {
    const List<String> english = <String>[
      'Mon',
      'Tue',
      'Wed',
      'Thu',
      'Fri',
      'Sat',
      'Sun'
    ];
    const List<String> arabic = <String>[
      'الاثنين',
      'الثلاثاء',
      'الأربعاء',
      'الخميس',
      'الجمعة',
      'السبت',
      'الأحد'
    ];
    return (isArabic ? arabic : english)[weekday - 1];
  }

  String get exercises => isArabic ? 'التمارين' : 'Exercises';
  String get noExercisesLogged =>
      isArabic ? 'لم تُسجل تمارين بعد.' : 'No exercises logged yet.';
  String historyItemCount(int count) =>
      isArabic ? '(${_ltr('$count')})' : '($count)';
  String get noExerciseSets => isArabic
      ? 'لم تُسجل مجموعات لهذا التمرين.'
      : 'No recorded sets for this exercise.';
  String get records => isArabic ? 'الأرقام القياسية' : 'Records';
  String exerciseRecord(String type, String value, int reps, String date) =>
      isArabic
          ? '${_ltr(type)} · ${_ltr('$value kg')} × ${_count(reps, ArabicCountNoun.repetition)} (${_ltr(date)})'
          : '$type · $value kg × $reps reps ($date)';
  String get noRecordedCheckIns =>
      isArabic ? 'لم يُسجل أي تواصل بعد.' : 'No check-ins recorded yet.';
  String get logCheckInAction => isArabic ? 'تسجيل تواصل' : 'Log check-in';
  String get history => isArabic ? 'السجل' : 'History';
  String get checkIns => isArabic ? 'التواصل' : 'Check-ins';
  String requestsWithCount(int count) => isArabic
      ? '$requests (${_count(count, ArabicCountNoun.request)})'
      : 'Requests ($count)';
  String get pending => isArabic ? 'قيد الانتظار' : 'Pending';
  String get noPendingRequests =>
      isArabic ? 'لا توجد طلبات قيد الانتظار.' : 'No pending requests.';
  String get answered => isArabic ? 'تم الرد' : 'Answered';
  String get nothingAnswered =>
      isArabic ? 'لا توجد طلبات تم الرد عليها.' : 'Nothing answered yet.';
  String get requestUnavailable => isArabic
      ? 'لم يعد هذا الطلب متاحًا.'
      : 'This request is no longer available.';
  String get selectRequest =>
      isArabic ? 'اختر طلبًا لمراجعته.' : 'Select a request to review.';
  String get requestDetail => isArabic ? 'تفاصيل الطلب' : 'Request detail';
  String get requestAnswered =>
      isArabic ? 'تم الرد على هذا الطلب.' : 'This request has been answered.';
  String get applySwap => isArabic ? 'تطبيق التبديل' : 'Apply swap';
  String get applyAndRebuild =>
      isArabic ? 'تطبيق وإعادة إنشاء البرنامج' : 'Apply (rebuilds program)';
  String get reasonForDeclining => isArabic
      ? 'سبب الرفض (سيظهر للاعب)'
      : 'Reason for declining (shown to the player)';
  String get sentOnlyOnDecline => isArabic
      ? 'يُرسل عند الرفض فقط · حتى 500 حرف.'
      : 'Sent only with Decline · up to 500 characters.';
  String get decline => isArabic ? 'رفض' : 'Decline';
  String playerAsks(String player) =>
      isArabic ? 'يطلب ${_ltr(player)}' : '$player asks';
  String get wholeProgram => isArabic ? 'البرنامج كاملًا' : 'Whole program';
  String programVersion(int version) =>
      isArabic ? 'إصدار البرنامج ${_ltr('$version')}' : 'program v$version';
  String requestScope(String? day, int version) => isArabic
      ? '${day == null ? wholeProgram : _ltr(day)} · ${programVersion(version)}'
      : '${day ?? wholeProgram} · ${programVersion(version)}';
  String get requestApplied =>
      isArabic ? 'تم تطبيق طلب البرنامج التدريبي.' : 'Program request applied.';
  String get requestDeclined =>
      isArabic ? 'تم رفض طلب البرنامج التدريبي.' : 'Program request declined.';
  String get player => isArabic ? 'لاعب' : 'Player';
  String get you => isArabic ? 'أنت' : 'You';
  String get tapToReview => isArabic ? 'اضغط للمراجعة' : 'tap to review';
  String sentOn(String date) => isArabic
      ? 'أُرسل ${_ltr(date)} · $tapToReview'
      : 'Sent $date · $tapToReview';
  String programRequestTitle({
    required bool isSubstitution,
    required String? exerciseName,
    required String? day,
    required String? replacementName,
    required int? frequency,
    required String? preference,
  }) {
    final String from = exerciseNameOrFallback(exerciseName, languageCode);
    final String to = exerciseNameOrFallback(replacementName, languageCode);
    if (!isArabic) {
      if (isSubstitution) return '$from → $to';
      return 'Split change → $frequency days/week'
          '${preference == null || preference.isEmpty ? '' : ' · $preference'}';
    }
    if (isSubstitution) {
      return 'تبديل تمرين ${_ltr(from)} في ${_ltr(day ?? '')} إلى ${_ltr(to)}';
    }
    return 'تغيير تقسيمة البرنامج إلى ${_count(frequency ?? 0, ArabicCountNoun.day)} في الأسبوع'
        '${preference == null || preference.isEmpty ? '' : ' · ${_ltr(preference)}'}';
  }

  String get splitChange => isArabic ? 'تغيير تقسيمة البرنامج' : 'Split change';
  String get splitArrow => isArabic ? 'إلى' : '→';
  String youReplied(String response) =>
      isArabic ? 'ردك: ${_ltr(response)}' : 'You: $response';
  String requestStatus(String status) => switch (status) {
        'pending' => isArabic ? 'قيد الانتظار' : 'Pending',
        'applied' => isArabic ? 'تم التطبيق' : 'Applied',
        'declined' => isArabic ? 'مرفوض' : 'Declined',
        'cancelled' => isArabic ? 'ملغى' : 'Cancelled',
        _ => status,
      };

  String get noPlayersHistory =>
      isArabic ? 'لا يوجد سجل تدريب بعد.' : 'No training history yet.';
  String get coachingSince => isArabic ? 'يتدرب معك منذ' : 'Coaching since';
  String coachingSinceDate(String date) => isArabic ? _ltr(date) : date;
  String get lastSession => isArabic ? 'آخر حصة' : 'Last session';
  String get weeklyVolume => isArabic ? 'الحجم الأسبوعي' : 'Weekly volume';
  String get injuries => isArabic ? 'الإصابات' : 'Injuries';
  String get noInjuries =>
      isArabic ? 'لا توجد إصابات مسجلة.' : 'No injuries recorded.';
  String injuryStatus(String status) => switch (status) {
        'reported' => isArabic ? 'تم الإبلاغ' : 'Reported',
        'physician_seen' => isArabic ? 'تمت مراجعة طبيب' : 'Physician seen',
        'resolved' => isArabic ? 'تم التعافي' : 'Resolved',
        _ => status,
      };
  String clearanceVerdict(String verdict) => switch (verdict) {
        'cleared' => isArabic ? 'مسموح' : 'Cleared',
        'not_cleared' => isArabic ? 'غير مسموح' : 'Not cleared',
        'cleared_with_limits' =>
          isArabic ? 'مسموح بقيود' : 'Cleared with limits',
        _ => verdict,
      };
  String injuryArea(String? area) => switch (area) {
        'knee' => isArabic ? 'الركبة' : 'Knee',
        'hip' => isArabic ? 'الورك' : 'Hip',
        'lower_back' => isArabic ? 'أسفل الظهر' : 'Lower back',
        'shoulder' => isArabic ? 'الكتف' : 'Shoulder',
        'elbow' => isArabic ? 'الكوع' : 'Elbow',
        'wrist' => isArabic ? 'الرسغ' : 'Wrist',
        'ankle' => isArabic ? 'الكاحل' : 'Ankle',
        'neck' => isArabic ? 'الرقبة' : 'Neck',
        _ => isArabic ? 'غير محددة' : 'Unknown area',
      };
  String get sessionVolumeColumn =>
      isArabic ? 'إجمالي الوزن المرفوع (${_ltr('kg')})' : 'Volume (kg)';
  String get sessionDateColumn => isArabic ? 'التاريخ' : 'Date';
  String get sessionSplitColumn => isArabic ? 'التقسيمة' : 'Split';
  String get sessionFlagsColumn => isArabic ? 'العلامات' : 'Flags';
  String formatVolume(num volume) {
    final String fixed = volume.toStringAsFixed(1);
    final List<String> parts = fixed.split('.');
    final String whole = parts.first.replaceAllMapped(
      RegExp(r'\B(?=(\d{3})+(?!\d))'),
      (Match match) => ',',
    );
    final String formatted = parts.last == '0' ? whole : '$whole.${parts.last}';
    return isArabic ? _ltr(formatted) : formatted;
  }

  String get volumeUnit => isArabic ? _ltr('kg') : 'kg';
  String expectedDays(String value) =>
      isArabic ? 'أيام التدريب المتوقعة: $value' : 'Expected: $value';
  String sessionTitle(String split, String date) =>
      isArabic ? '${_ltr(split)} · ${_ltr(date)}' : '$split · $date';
  String latestSessionTotals(int sets, num volume) => isArabic
      ? '${_count(sets, ArabicCountNoun.trainingSet)} · إجمالي الوزن المرفوع ${formatVolume(volume)} $volumeUnit'
      : '$sets sets · ${formatVolume(volume)} $volumeUnit';
  String sessionExerciseCompact(int sets, int reps, num volume) => isArabic
      ? '${_count(sets, ArabicCountNoun.trainingSet)} · '
          '${_count(reps, ArabicCountNoun.repetition)} · '
          'إجمالي الوزن المرفوع ${formatVolume(volume)} $volumeUnit'
      : '$sets sets · $reps reps · ${formatVolume(volume)} $volumeUnit';
  String get noVolume =>
      isArabic ? 'لم تُسجل مجموعات تدريب بعد.' : 'No volume recorded yet.';
  String get personalRecordsTitle =>
      isArabic ? 'الأرقام القياسية الشخصية' : 'Personal records';
  String get recordTypeColumn => isArabic ? 'النوع' : 'Type';
  String get valueColumn => isArabic ? 'القيمة' : 'Value';
  String get dateColumn => isArabic ? 'التاريخ' : 'Date';
  String get weightColumn => isArabic ? 'الوزن' : 'Weight';
  String get e1rmColumn => 'e1RM';
  String recordTypeLabel(String type) =>
      switch (PrRecordKind.fromRecordType(type)) {
        PrRecordKind.weight => isArabic ? 'أقصى وزن' : 'Max weight',
        PrRecordKind.e1rm => 'e1RM',
        PrRecordKind.mostReps =>
          isArabic ? 'أكبر عدد من التكرارات' : 'Most reps',
        null => type,
      };

  String recordValueLabel(String type, String value, int reps) {
    if (PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps) {
      return isArabic
          ? _count(reps, ArabicCountNoun.repetition)
          : _englishRepetitions(reps);
    }
    return isArabic ? _ltr('$value kg') : '$value kg';
  }

  String recordRepsCell(int reps) => isArabic ? _ltr('$reps') : '$reps';

  String recordCompactSummary(
    String type,
    String value,
    int reps,
    String date,
  ) {
    final String recordType = recordTypeLabel(type);
    final String recordValue = recordValueLabel(type, value, reps);
    if (isArabic) {
      final String repetitions =
          PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps
              ? ''
              : ' · التكرارات: ${_count(reps, ArabicCountNoun.repetition)}';
      return 'النوع: $recordType · القيمة: $recordValue$repetitions · '
          'التاريخ: ${_ltr(date)}';
    }
    final String repetitions =
        PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps
            ? ''
            : ' · Reps: ${_englishRepetitions(reps)}';
    return 'Type: $recordType · Value: $recordValue$repetitions · Date: $date';
  }

  String recordSummary(String type, String value, int reps) {
    final String label = recordTypeLabel(type);
    if (PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps) {
      return isArabic
          ? '$label · ${_count(reps, ArabicCountNoun.repetition)}'
          : '$label · ${_englishRepetitions(reps)}';
    }
    return isArabic
        ? '${_ltr(label)} · ${_ltr('$value kg')} × '
            '${_count(reps, ArabicCountNoun.repetition)}'
        : '$label · $value kg × ${_englishRepetitions(reps)}';
  }

  String exerciseHistoryWeight(String weight, {required String weightUnit}) {
    final String value = weightUnit.isEmpty ? weight : '$weight $weightUnit';
    return isArabic && weightUnit.isNotEmpty ? _ltr(value) : value;
  }

  String exerciseHistoryCompactPoint(
    String date,
    String weight,
    int reps, {
    required String weightUnit,
    String? rir,
    String? e1rm,
  }) {
    final List<String> fields = <String>[
      isArabic ? '$dateColumn: ${_ltr(date)}' : '$dateColumn: $date',
      '$weightColumn: '
          '${exerciseHistoryWeight(weight, weightUnit: weightUnit)}',
      isArabic
          ? '$programRepsColumn: ${_count(reps, ArabicCountNoun.repetition)}'
          : '$programRepsColumn: $reps',
    ];
    if (rir != null) {
      fields.add(
        isArabic
            ? '$programRirColumn: ${_ltr(rir)}'
            : '$programRirColumn: $rir',
      );
    }
    if (e1rm != null) {
      fields.add(
        isArabic ? '$e1rmColumn: ${_ltr(e1rm)}' : '$e1rmColumn: $e1rm',
      );
    }
    return fields.join(' · ');
  }

  String _englishRepetitions(int reps) => '$reps ${reps == 1 ? 'rep' : 'reps'}';
  String historicalProgram(int captured, int current) => isArabic
      ? 'سُجلت الحصة على إصدار البرنامج ${_ltr('$captured')} (الحالي ${_ltr('$current')})'
      : 'Logged against program v$captured (current v$current)';
  String? historicalProgramIfNeeded(
    int? captured,
    int? current,
    bool isHistorical,
  ) =>
      isHistorical && captured != null && current != null
          ? historicalProgram(captured, current)
          : null;
  String correctedDate(String previous, String corrected) => isArabic
      ? 'تم تصحيح التاريخ من ${_ltr(previous)} إلى ${_ltr(corrected)}'
      : 'Date corrected from $previous to $corrected';
  String splitSubstitution(String frequency, String? preference) => isArabic
      ? 'تغيير تقسيمة البرنامج إلى ${_ltr(frequency)} أيام أسبوعيًا${preference == null || preference.isEmpty ? '' : ' · ${_ltr(preference)}'}'
      : 'Split change → $frequency days/week${preference == null || preference.isEmpty ? '' : ' · $preference'}';

  // #431
  String get copyInviteCode =>
      isArabic ? 'نسخ كود الدعوة' : 'Copy invite code';
  String get inviteCopied => isArabic
      ? 'تم نسخ رمز الدعوة. يمكنك مشاركته مع اللاعب.'
      : 'Invite code copied. You can share it with the player.';

  // #430 phone deep-link action.
  String get reviewRequest => isArabic ? 'مراجعة الطلب' : 'Review request';

  String _count(int count, ArabicCountNoun noun) {
    final String phrase = arabicCountPhrase(count, noun);
    final RegExpMatch? leading = RegExp(r'^[\d,]+').firstMatch(phrase);
    if (leading == null) return phrase;
    return '${_ltr(leading[0]!)}${phrase.substring(leading.end)}';
  }

  String _groupCount(int count) => count
      .toString()
      .replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');

  String _ltr(String value) => '\u2066$value\u2069';

  // #427: Player history table heading.
  String get muscleColumn => isArabic ? 'العضلة' : 'Muscle';

  // #428
  String get dayActions =>
      isArabic ? 'إجراءات يوم التدريب' : 'Training day actions';
  String get exerciseEditorDone => isArabic ? 'تم' : 'Done';
  // #323 set group editor copy.
  String get addBackoffSets => isArabic ? 'إضافة مجموعات خفض الحمل' : 'Add back-off sets';
  String get removeSetGroup => isArabic ? 'إزالة المجموعة' : 'Remove group';
  String get amrapLastSet => isArabic ? 'أكبر عدد ممكن من التكرارات' : 'AMRAP last set';
  String backoffGroupTitle(int count) => isArabic
      ? 'مجموعات خفض الحمل (${_ltr('$count')})'
      : 'Back-off sets ($count)';
  String get firstGroupLoadPercent => isArabic ? 'نسبة من حمل المجموعة الأولى' : '% of first group load';
  String get moveExerciseUp =>
      isArabic ? 'نقل التمرين لأعلى' : 'Move exercise up';
  String get moveExerciseDown =>
      isArabic ? 'نقل التمرين لأسفل' : 'Move exercise down';
  String exercisePrescriptionSummary({
    required String sets,
    required String reps,
    required String rir,
    required String warmupSets,
    required String rest,
  }) {
    final List<String> parts = <String>[];
    if (sets.isNotEmpty || reps.isNotEmpty) {
      parts.add(isArabic
          ? '${sets.isEmpty ? '' : '${_ltr(sets)} مجموعات'}${sets.isNotEmpty && reps.isNotEmpty ? ' × ' : ''}${reps.isEmpty ? '' : '${_ltr(reps)} تكرارات'}'
          : '${sets.isEmpty ? '' : '$sets sets'}${sets.isNotEmpty && reps.isNotEmpty ? ' × ' : ''}${reps.isEmpty ? '' : '$reps reps'}');
    }
    if (rir.isNotEmpty) {
      parts.add(isArabic ? 'RIR ${_ltr(rir)}' : '$rir RIR');
    }
    if (warmupSets.isNotEmpty) {
      parts.add(isArabic
          ? '${_ltr(warmupSets)} مجموعات إحماء متدرجة'
          : '$warmupSets ramped warm-up sets');
    }
    if (rest.isNotEmpty) {
      parts.add(isArabic
          ? 'راحة ${_ltr(rest)} ثانية'
          : '$rest seconds rest');
    }
    return parts.join(' · ');
  }

  // #297 load prescription editor.
  String get loadPrescription => isArabic ? 'الحمل' : 'Load';
  String get noLoad => isArabic ? 'بدون حمل محدد' : 'None';
  String get fixedLoadKg => isArabic ? 'وزن ثابت (kg)' : 'Fixed weight (kg)';
  String get loadPercentE1rm => isArabic ? 'نسبة من e1RM' : '% e1RM';
  String get invalidLoadPrescription => isArabic
      ? 'أدخل قيمة من ${ProgramLoad.formatValue(ProgramLoad.minimumPercentE1rm)} '
          'إلى ${ProgramLoad.formatValue(ProgramLoad.maximumPercentE1rm)} للحمل النسبي، أو وزنًا أكبر من '
          '${ProgramLoad.formatValue(ProgramLoad.minimumKg)}.'
      : 'Enter ${ProgramLoad.formatValue(ProgramLoad.minimumPercentE1rm)}–'
          '${ProgramLoad.formatValue(ProgramLoad.maximumPercentE1rm)} for a percentage, or a weight '
          'greater than ${ProgramLoad.formatValue(ProgramLoad.minimumKg)}.';
  String prescribedLoad({required String kind, required String value}) =>
      kind == 'kg'
          ? (isArabic ? '${_ltr(value)} kg' : '$value kg')
          : (isArabic ? '${_ltr(value)}% e1RM' : '$value% e1RM');
}
