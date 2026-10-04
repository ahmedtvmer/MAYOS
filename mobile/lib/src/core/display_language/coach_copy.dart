import 'arabic_count.dart';
import '../personal_records.dart';

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
  String requestPlayerDay(String player, String day) =>
      isArabic ? '${_ltr(player)} · ${_ltr(day)}' : '$player · $day';
  String get activeAssignments =>
      isArabic ? 'علاقات التدريب النشطة' : 'Active assignments';
  String get noAssignedPlayers =>
      isArabic ? 'لا يوجد لاعبون معينون بعد.' : 'No assigned players yet.';
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
  String resolvedBy(String username) =>
      isArabic ? 'حلّه ${_ltr(username)}' : 'Resolved by $username';
  String get alertNew => isArabic ? 'جديد' : 'New';
  String get alertAcknowledged =>
      isArabic ? 'تم تأكيد الاطلاع' : 'Acknowledged';
  String get alertResolved => isArabic ? 'تم الحل' : 'Resolved';
  String alertState(String state) => switch (state) {
        'new' => alertNew,
        'acknowledged' => alertAcknowledged,
        'resolved' => alertResolved,
        _ => state,
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
  String get openAlerts => isArabic ? 'التنبيهات المفتوحة' : 'Open alerts';
  String assistantNoHistory(String player) => isArabic
      ? 'اسأل عن أرقام تدريب ${_ltr(player)}: مجموعات التدريب، والحصص، والأرقام القياسية، والجدول.'
      : 'Ask about $player\'s training figures: volume, sessions, records, and schedule.';
  String get assistantThinking => isArabic ? 'جارٍ التفكير…' : 'Thinking…';
  String assistantNote(String player) => isArabic
      ? 'تستخدم الإجابات أرقام تدريب ${_ltr(player)}. لا يُحفظ شيء.'
      : "Answers use the player's training figures. Nothing is saved.";
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
      isArabic ? 'أدخل رمز مدرب MAYOS' : 'Enter your MAYOS coach code';
  String get coachCodeLead => isArabic
      ? 'هذا الرمز من MAYOS ويفعّل وضع المدرب في حسابك. يُستخدم مرة واحدة وتنتهي صلاحيته. إدخاله لا ينشئ علاقة تدريب مع مدرب.'
      : 'This code comes from MAYOS and enables Coach mode on your own account. It is single-use and expires. Entering it does not assign you to a coach.';
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
  String get invitePlayer => isArabic ? 'دعوة لاعب' : 'Invite a player';
  String get inviteExplanation => isArabic
      ? 'أنشئ رمزًا لمرة واحدة وقدّمه للاعب واحد. تنتهي صلاحيته، ولا يمكن استخدامه إلا عند توفر مكان في قائمة اللاعبين. سيظهر تاريخ الانتهاء بعد إنشاء الرمز.'
      : 'Create a single-use code and give it to one player. It expires and can only be redeemed while you have roster room; the exact expiry is shown when the code is issued.';
  String get createPlayerInvite =>
      isArabic ? 'إنشاء دعوة للاعب' : 'Create player invite';
  String inviteExpires(String date) =>
      isArabic ? 'تنتهي الصلاحية ${_ltr(date)}' : 'Expires $date';
  String rosterSlotsFree(int remaining, int capacity) => isArabic
      ? 'المتاح في قائمة اللاعبين: ${_ltr('$remaining')} من ${_ltr('$capacity')}'
      : '$remaining of $capacity roster slots free';
  String get notices => isArabic ? 'الإشعارات' : 'Notices';
  String get markAllRead => isArabic ? 'تحديد الكل كمقروء' : 'Mark all read';
  String get resolvedAlerts =>
      isArabic ? 'التنبيهات المحلولة' : 'Resolved alerts';

  String get publishProgram =>
      isArabic ? 'نشر برنامج تدريبي' : 'Publish program';
  String get splitOverrideOptional =>
      isArabic ? 'تقسيمة مخصصة (اختيارية)' : 'Split override (optional)';
  String get repPreference => isArabic ? 'تفضيل التكرارات' : 'Rep preference';
  String get low => isArabic ? 'منخفض' : 'Low';
  String get balanced => isArabic ? 'متوازن' : 'Balanced';
  String get high => isArabic ? 'مرتفع' : 'High';
  String get daysPerWeek =>
      isArabic ? 'أيام التدريب أسبوعيًا' : 'Days per week';
  String get publish => isArabic ? 'نشر' : 'Publish';
  String programPublished(int? version) => isArabic
      ? 'نُشر إصدار البرنامج التدريبي ${_ltr('$version')}'
      : 'Published program version $version';
  String get programRequests =>
      isArabic ? 'طلبات البرنامج التدريبي' : 'Program requests';
  String get noProgramRequests => isArabic
      ? 'لا توجد طلبات للبرنامج التدريبي بعد.'
      : 'No program requests yet.';
  String get noRecordedVolume =>
      isArabic ? 'لم تُسجل مجموعات تدريب بعد.' : 'No volume recorded yet.';
  String get weightedWorkingSets =>
      isArabic ? 'مجموعات محسوبة لكل عضلة' : 'Volume (weighted working sets)';
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
      isArabic ? 'محطة التقدم ${_ltr('$number')}' : 'Checkpoint $number';
  String checkpointPeriod(String start, String end) =>
      isArabic ? '${_ltr(start)} – ${_ltr(end)}' : '$start – $end';
  String recordHistory(String type, String value, int reps, String date) {
    if (PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps) {
      return isArabic
          ? 'أكبر عدد من التكرارات · ${_count(reps, ArabicCountNoun.repetition)} (${_ltr(date)})'
          : 'Most reps · $reps reps ($date)';
    }
    return isArabic
        ? '${_ltr(type)} · ${_ltr('$value kg')} × ${_count(reps, ArabicCountNoun.repetition)} (${_ltr(date)})'
        : '$type · $value kg × $reps reps ($date)';
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
    required String? exerciseId,
    required String? day,
    required String? replacementId,
    required int? frequency,
    required String? preference,
  }) {
    if (!isArabic) {
      if (isSubstitution) return '$exerciseId → $replacementId';
      return 'Split change → $frequency days/week'
          '${preference == null || preference.isEmpty ? '' : ' · $preference'}';
    }
    if (isSubstitution) {
      return 'تبديل تمرين ${_ltr(exerciseId ?? '')} في ${_ltr(day ?? '')} إلى ${_ltr(replacementId ?? '')}';
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
  String since(String date) => isArabic ? 'منذ ${_ltr(date)}' : 'Since $date';
  String get playerVolume =>
      isArabic ? 'مجموعات محسوبة لكل عضلة' : 'Volume (weighted working sets)';
  String volumeValue(String muscle, String value) =>
      isArabic ? '${_ltr(muscle)}: ${_ltr(value)}' : '$muscle: $value';
  String expectedDays(String value) =>
      isArabic ? 'أيام التدريب المتوقعة: $value' : 'Expected: $value';
  String sessionTitle(String split, String date) =>
      isArabic ? '${_ltr(split)} · ${_ltr(date)}' : '$split · $date';
  String setsAndVolume(int sets, String volume) => isArabic
      ? '${_count(sets, ArabicCountNoun.trainingSet)} · إجمالي الوزن المرفوع ${_ltr('$volume kg')}'
      : '$sets sets · $volume kg';
  String movementCount(int count) => isArabic
      ? 'حركات الإحماء: ${_count(count, ArabicCountNoun.warmupMovement)}'
      : 'Warm-up: $count movements';
  String get noVolume =>
      isArabic ? 'لم تُسجل مجموعات تدريب بعد.' : 'No volume recorded yet.';
  String get personalRecordsTitle =>
      isArabic ? 'الأرقام القياسية الشخصية' : 'Personal records';
  String recordSummary(String type, String value, int reps) {
    if (PrRecordKind.fromRecordType(type) == PrRecordKind.mostReps) {
      return isArabic
          ? 'أكبر عدد من التكرارات · ${_count(reps, ArabicCountNoun.repetition)}'
          : 'Most reps · $reps reps';
    }
    return isArabic
        ? '${_ltr(type)} · ${_ltr('$value kg')} × ${_count(reps, ArabicCountNoun.repetition)}'
        : '$type · $value kg × $reps reps';
  }
  String sessionExercise(String name, int sets, String volume) => isArabic
      ? '${_ltr(name)}: ${_count(sets, ArabicCountNoun.trainingSet)} · إجمالي الوزن المرفوع ${_ltr('$volume kg')}'
      : '$name: $sets sets · $volume kg';
  String exerciseHistoryPoint(String date, String weight, int reps,
          {String weightUnit = 'kg', String? rir, String? e1rm}) {
    final String value = weightUnit.isEmpty ? weight : '$weight $weightUnit';
    return isArabic
        ? '${_ltr(date)}: ${_ltr(value)} × ${_count(reps, ArabicCountNoun.repetition)}${rir == null ? '' : ' · RIR ${_ltr(rir)}'}${e1rm == null ? '' : ' (e1RM ${_ltr(e1rm)})'}'
        : '$date: $value × $reps${rir == null ? '' : ' @ RIR $rir'}${e1rm == null ? '' : ' (e1RM $e1rm)'}';
  }
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

  String _count(int count, ArabicCountNoun noun) {
    final String phrase = arabicCountPhrase(count, noun);
    final RegExpMatch? leading = RegExp(r'^\d+').firstMatch(phrase);
    if (leading == null) return phrase;
    return '${_ltr(leading[0]!)}${phrase.substring(leading.end)}';
  }

  String _ltr(String value) => '\u2066$value\u2069';
}
