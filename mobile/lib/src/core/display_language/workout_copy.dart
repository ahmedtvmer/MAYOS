import 'arabic_count.dart';
import '../training_status_projection.dart';

/// App-owned labels and messages used by the player workout logger.
class WorkoutCopy {
  const WorkoutCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get logWorkout => isArabic ? 'تسجيل حصة تدريبية' : 'Log workout';
  String logWorkoutTime(String time) =>
      isArabic ? 'تسجيل حصة تدريبية · $time' : 'Log workout · $time';
  String get discardWorkout => isArabic ? 'حذف الحصة' : 'Discard workout';
  String get finishWorkout => isArabic ? 'إنهاء الحصة' : 'Finish workout';
  String setsProgress(int done, int total) =>
      isArabic ? '${_ltr('$done/$total')} مجموعات' : '$done/$total sets';
  String get setShort => isArabic ? 'مجموعة' : 'SET';
  String get kilogramsShort => 'KG';
  String get repsShort => isArabic ? 'تكرارات' : 'REPS';
  String get warmup => isArabic ? 'الإحماء' : 'Warm-up';
  String get exercises => isArabic ? 'التمارين' : 'Exercises';
  String get warmupMovementTag => isArabic ? 'حركة إحماء' : 'Warm-up';
  String get unplanned => isArabic ? 'غير مخطط' : 'Unplanned';
  String get cardio => isArabic ? 'تمارين اللياقة' : 'Cardio';
  String get minutes => isArabic ? 'دقائق' : 'Minutes';
  String get restTime => isArabic ? 'مدة الراحة…' : 'Rest time…';
  String restNotificationTitle(String time) =>
      isArabic ? 'MAYOS · راحة ${_ltr(time)}' : 'MAYOS · Rest $time';
  String restNotificationLine({
    required String exerciseName,
    required int setNumber,
    String? lastLabel,
  }) =>
      isArabic
          ? 'التالي: ${_ltr(exerciseName)} · المجموعة ${_ltr('$setNumber')}'
              '${lastLabel == null ? '' : ' · السابق ${_ltr(lastLabel)}'}'
          : 'Next: $exerciseName · set $setNumber'
              '${lastLabel == null ? '' : ' · last $lastLabel'}';
  String get restCompleteNotification =>
      isArabic ? 'انتهت الراحة' : 'Rest complete';
  String get restTimerChannel => isArabic ? 'مؤقت الراحة' : 'Rest timer';
  String get restTimerChannelDescription => isArabic
      ? 'مؤقت الراحة الجاري أثناء الحصة التدريبية.'
      : 'The running rest countdown while a workout is in progress.';
  String get restEndChannelDescription => isArabic
      ? 'الصوت والاهتزاز عند انتهاء الراحة.'
      : 'The end-of-rest vibration and sound.';
  String returnToExercise(String name) =>
      isArabic ? 'العودة إلى ${_ltr(name)}' : 'Back to $name';
  String get restNotificationPermission => isArabic
      ? 'تحتاج تنبيهات الراحة إلى إذن لتصلك عند إطفاء الشاشة.'
      : 'Rest alerts need permission to reach you when your screen is off.';
  String get addSet => isArabic ? '+ أضف مجموعة' : '+ Add set';
  String get addExercise => isArabic ? 'إضافة تمرين' : 'Add exercise';
  String get addUnplannedExercise =>
      isArabic ? 'إضافة تمرين غير مخطط' : 'Add unplanned exercise';
  String get replaceExercise =>
      isArabic ? 'استبدال تمرين لهذه الحصة' : 'Replace exercise';
  String get removeExercise => isArabic ? 'إزالة التمرين' : 'Remove exercise';
  String get removeAction => isArabic ? 'إزالة' : 'Remove';
  String get undoReplace => isArabic ? 'تراجع عن الاستبدال' : 'Undo replace';
  String get exerciseMenu => isArabic ? 'خيارات التمرين' : 'Exercise menu';
  String get viewExerciseDetails =>
      isArabic ? 'عرض تفاصيل التمرين' : 'View exercise details';
  String exerciseDetails(String name) =>
      isArabic ? 'عرض تفاصيل التمرين: $name' : 'View $name details';
  String get pictureUnavailable =>
      isArabic ? 'تعذر عرض الصورة' : 'Picture unavailable';
  String get noPicture => isArabic ? 'لا توجد صورة' : 'No picture';
  String get markSetDone =>
      isArabic ? 'تحديد المجموعة كمكتملة' : 'Mark set done';
  String get markSetNotDone =>
      isArabic ? 'إلغاء تحديد المجموعة' : 'Mark set not done';
  String get markCardioDone =>
      isArabic ? 'تحديد اللياقة كمكتملة' : 'Mark Cardio done';
  String get markCardioNotDone =>
      isArabic ? 'إلغاء تحديد اللياقة' : 'Mark Cardio not done';
  String get weightKg => isArabic ? 'الوزن (kg)' : 'Weight (kg)';
  String get repetitions => isArabic ? 'التكرارات' : 'Reps';
  String get repsInReserve =>
      isArabic ? 'التكرارات المتبقية' : 'Reps in reserve';
  String keypadCaption(String exercise, int setNumber, String field) => isArabic
      ? '$exercise · مجموعة $setNumber · $field'
      : '$exercise · set $setNumber · $field';
  String get unrated => isArabic ? 'بلا تقييم' : 'Unrated';
  String get hideKeypad => isArabic ? 'إخفاء' : 'Hide';
  String get next => isArabic ? 'التالي' : 'Next';
  String get restOff => isArabic ? 'إيقاف' : 'Off';
  String restForExercise(String exercise) =>
      isArabic ? 'راحة · $exercise' : 'Rest · $exercise';
  String get skipRest => isArabic ? 'تخطي' : 'Skip';
  String get pictureTooltip => isArabic ? 'صورة التمرين' : 'Exercise picture';

  String get replaceQuestion =>
      isArabic ? 'استبدال التمرين؟' : 'Replace exercise?';
  String discardSetsQuestion(int count) => isArabic
      ? 'استبدال التمرين وحذف ${arabicCountPhrase(count, ArabicCountNoun.group, isolateCount: true)} المسجلة؟'
      : count == 1
          ? 'Replace and discard 1 logged set?'
          : 'Replace and discard $count logged sets?';
  String get loggedSetsCleared => isArabic
      ? 'ستُحذف المجموعات التي سجلتها لهذا التمرين.'
      : "The sets you've logged on this exercise will be cleared.";
  String get loggedSetsDiscarded => isArabic
      ? 'ستُحذف المجموعات التي سجلتها لهذا التمرين.'
      : "The sets you've logged on this exercise will be discarded.";
  String get reasonForCoach =>
      isArabic ? 'السبب لمدربك' : 'Reason for your coach';
  String get addReasonToContinue =>
      isArabic ? 'أضف سببًا للمتابعة.' : 'Add a reason to continue.';
  String get askCoachToMakePermanent => isArabic
      ? 'اطلب من مدربك تبديل التمرين في البرنامج'
      : 'Ask my coach to make this permanent';
  String get keepSwapInProgram =>
      isArabic ? 'تبديل التمرين في البرنامج' : 'Keep this swap in my program';
  String get sendRequest => isArabic ? 'إرسال الطلب' : 'Send request';
  String get sending => isArabic ? 'جارٍ الإرسال…' : 'Sending…';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';
  String get keepLogging => isArabic ? 'متابعة التسجيل' : 'Keep logging';
  String get replace => isArabic ? 'استبدال' : 'Replace';
  String setsWereRemoved(int count, {required bool undo}) => isArabic
      ? '${undo ? 'التراجع عن الاستبدال' : 'إزالة التمرين'} وحذف ${arabicCountPhrase(count, ArabicCountNoun.group, isolateCount: true)} المسجلة؟'
      : count == 1
          ? 'Remove and discard 1 logged set?'
          : 'Remove and discard $count logged sets?';
  String get askCoachPermanent => isArabic
      ? 'طلب تبديل تمرين من المدرب'
      : 'Ask my coach to make this permanent';
  String get keepProgramSwap =>
      isArabic ? 'تبديل تمرين في البرنامج' : 'Keep this swap in my program';
  String get confirmDiscardTitle =>
      isArabic ? 'حذف هذه الحصة؟' : 'Discard this workout?';
  String get discardSetsLost => isArabic
      ? 'ستفقد المجموعات التي سجلتها في هذه الحصة.'
      : "The sets you've logged in this workout will be lost.";
  String get discardBrowserSets => isArabic
      ? 'ستُحذف مجموعات هذه الحصة من هذا المتصفح.'
      : 'Its sets will be removed from this browser.';
  String get resume => isArabic ? 'استئناف' : 'Resume';
  String get discard => isArabic ? 'حذف' : 'Discard';
  String get unfinishedWorkout =>
      isArabic ? 'حصة غير مكتملة' : 'Unfinished workout';
  String get finishCurrentWorkout =>
      isArabic ? 'أنهِ حصتك الحالية' : 'Finish your current workout';
  String get resumeOrDiscardNewStart => isArabic
      ? 'هناك حصة قيد التسجيل على هذا الجهاز. استأنفها أو احذفها لبدء حصة جديدة.'
      : 'This device is already logging a workout. Resume it, or discard it to start a new one.';
  String get resumeOrDiscard => isArabic
      ? 'استأنف من حيث توقفت أو احذف هذه الحصة.'
      : 'Resume where you left off, or discard this workout.';
  String get started => isArabic ? 'بدأت' : 'started';
  String startedWorkoutLabel(String day, String startedAt) => isArabic
      ? '${_ltr(day)} · بدأت ${_ltr(startedAt)}'
      : '$day · started $startedAt';
  String get webWorkoutNoticeTitle =>
      isArabic ? 'تسجيل الحصص على الويب' : 'Logging workouts on web';
  String get webWorkoutNotice => isArabic
      ? 'تحتاج إلى اتصال بالإنترنت لإكمال الحفظ. تُحفظ الحصة غير المكتملة في هذا المتصفح فقط.'
      : 'You need a connection to finish saving. An unfinished workout is kept only in this browser.';
  String get continueLogging =>
      isArabic ? 'متابعة التسجيل' : 'Continue logging';
  String get onlyTickedSetsSaved => isArabic
      ? 'تُحفظ المجموعات المحددة فقط في الحصة.'
      : 'Only ticked sets are saved to the workout.';
  String untickedSetQuestion(int count) => isArabic
      ? 'لم تُحدد ${arabicCountPhrase(count, ArabicCountNoun.group, isolateCount: true)}.'
      : count == 1
          ? "1 set isn't ticked"
          : "$count sets aren't ticked";
  String get discardUntickedAndFinish => isArabic
      ? 'حذف غير المحدد وإنهاء الحصة'
      : 'Discard unticked sets and finish';
  String get saveDraftNotice =>
      isArabic ? 'حُفظت الحصة في المسودات.' : 'Workout saved to your drafts.';
  String get savedToHistory => isArabic
      ? 'حُفظت الحصة في سجل تدريبك.'
      : 'Workout saved to your training history.';
  String get workoutSummary => isArabic ? 'ملخص الحصة' : 'Workout summary';
  String get backToWorkout => isArabic ? 'العودة إلى الحصة' : 'Back to workout';
  String get saveWorkout => isArabic ? 'حفظ الحصة' : 'Save workout';
  String get done => isArabic ? 'تم' : 'Done';
  String get performedDate => isArabic ? 'تاريخ الحصة' : 'Performed date';
  String get readiness => isArabic ? 'الاستعداد' : 'Readiness';
  String readinessOutOfFive(int value) =>
      isArabic ? 'الاستعداد: ${_ltr('$value/5')}' : 'Readiness: $value/5';
  String get notesHint => isArabic
      ? 'ملاحظات (الضخامة، ألم المفاصل، الإرهاق)'
      : 'Notes (pumps, joint aches, fatigue)';
  String get personalRecords =>
      isArabic ? 'الأرقام القياسية الشخصية' : 'Personal records';
  String recordBadge(String kind) => isArabic
      ? 'رقم قياسي · ${kind == 'weight' ? 'kg' : 'e1RM'}'
      : kind == 'weight'
          ? 'PR kg'
          : 'PR e1RM';
  String recordCelebration(String exercise, String kind, String value) => isArabic
      ? '${_ltr(exercise)} · رقم قياسي ${kind == 'weight' ? '' : 'e1RM '}${_ltr('$value kg')}'
      : '$exercise · ${kind == 'weight' ? 'PR ' : 'PR e1RM '}$value kg';
  String checkpointWorkout(int number) => isArabic
      ? 'حصة تدريبية رقم ${_ltr('$number')}!'
      : 'Your ${_ordinal(number)} workout!';
  String get reviewWillAppear => isArabic
      ? 'ستظهر مراجعتك هنا.'
      : 'Your review will appear on your dashboard';
  String get exercisesDone => isArabic ? 'التمارين المكتملة' : 'Exercises done';
  String get workingSets =>
      isArabic ? 'مجموعات التدريب المحددة' : 'Ticked working sets';
  String get totalVolume => isArabic ? 'إجمالي الوزن المرفوع' : 'Total volume';
  String get duration => isArabic ? 'المدة' : 'Duration';
  String get minutesUnit => isArabic ? 'دقيقة' : 'min';
  String get recordWeight => isArabic ? 'الوزن' : 'Weight';
  String get workoutProgressBlocked =>
      isArabic ? 'سجّل مجموعة واحدة على الأقل' : 'Log at least one set';
  String get trainingDayUnavailableOffline => isArabic
      ? 'يوم التدريب هذا غير متاح دون اتصال.'
      : 'This training day is not available offline.';
  String dateWindowClamped(String started, String corrected) => isArabic
      ? 'بدأت هذه الحصة في $started، خارج فترة إدخال التاريخ المسموحة، لذلك ضُبط تاريخها إلى $corrected.'
      : 'This workout started on $started, outside the allowed entry window, so its performed date was set to $corrected.';
  String workoutProgress({
    required int exercisesDone,
    required int exercisesTotal,
    required int setsDone,
    required int setsTotal,
  }) =>
      isArabic
          ? '${_ltr('$exercisesDone/$exercisesTotal')} تمارين · ${_ltr('$setsDone/$setsTotal')} مجموعات'
          : '$exercisesDone/$exercisesTotal exercises · $setsDone/$setsTotal sets';
  String get timezoneUnavailable => isArabic
      ? 'تعذر تحديد المنطقة الزمنية لجهازك، لذلك لا يمكن تسجيل تاريخ الحصة. تحقق من إعداد المنطقة الزمنية وحاول مجددًا.'
      : 'Your device timezone could not be determined, so the workout date cannot be recorded truthfully. Check your device time-zone settings and try again.';
  String get programUnavailable => isArabic
      ? 'البرنامج التدريبي غير متاح. اتصل بالإنترنت لتحديثه قبل تسجيل هذه الحصة.'
      : 'Your program is unavailable. Reconnect to refresh it before logging this workout.';
  String get connectToRefresh => isArabic
      ? 'البرنامج التدريبي غير متاح دون اتصال. اتصل مرة واحدة لتحديثه قبل حفظ هذه الحصة.'
      : 'Your program is unavailable offline. Connect once to refresh it before saving this workout.';
  String get programRefreshBeforeSave => isArabic
      ? 'حدّث برنامجك التدريبي قبل حفظ هذه الحصة.'
      : 'Refresh your program before saving this workout.';
  String get reopenWorkoutToSave => isArabic
      ? 'افتح هذه الحصة من جديد وحاول حفظها.'
      : 'Reopen this workout and try saving again.';
  String get saveFailedNoLoss => isArabic
      ? 'تعذر حفظ الحصة. لم يُفقد شيء؛ حاول مجددًا.'
      : 'The workout could not be saved. Nothing was lost — try again.';
  String get couldNotReachMayos => isArabic
      ? 'تعذر الاتصال بـ MAYOS. حُفظت حصتك في هذا المتصفح.'
      : "Couldn't reach MAYOS. Your workout is kept in this browser.";
  String get mayosBusy => isArabic
      ? 'MAYOS مشغول الآن. حُفظت حصتك في هذا المتصفح.'
      : 'MAYOS is busy. Your workout is kept in this browser.';
  String get versionChanged => isArabic
      ? 'تغير البرنامج التدريبي منذ بدء هذه الحصة. بدّل التمرين من تبويب البرنامج.'
      : 'Your program changed since this workout started; substitute it from the Program tab';
  String get swapSaved => isArabic
      ? 'حُفظ الاستبدال في برنامجك التدريبي.'
      : 'The swap was saved to your program.';
  String get reasonBeforeCoachRequest => isArabic
      ? 'أضف سببًا قبل طلب التبديل من مدربك.'
      : 'Add a reason before asking your coach.';
  String get coachAskedPermanentSwap => isArabic
      ? 'أرسلت إلى مدربك طلب تبديل التمرين في البرنامج.'
      : 'Your coach was asked to make this swap permanent.';
  String get programChangedSubstituteFromTab => isArabic
      ? 'تغير البرنامج التدريبي. بدّل هذا التمرين من تبويب البرنامج.'
      : 'The program changed. Substitute this exercise from the Program tab.';
  String get coachNowControlsProgram => isArabic
      ? 'حُفظ استبدال التمرين في حصتك، لكن مدربك أصبح يتحكم في البرنامج. أضف سببًا لإرسال الطلب.'
      : 'Your workout swap is saved. Your coach now controls this program. Add a reason to send the request.';
  String get replacementNoLongerInProgram => isArabic
      ? 'لم يعد هذا التمرين ضمن يوم البرنامج التدريبي.'
      : 'is no longer in this program day.';
  String swapSavedButProgramUnchanged(String detail) => isArabic
      ? 'حُفظ استبدال التمرين لهذه الحصة، ولم يتغير البرنامج التدريبي. $detail'
      : 'The workout swap is saved, but the program was not changed. $detail';
  String get exerciseCatalogUnavailable => isArabic
      ? 'تعذر تحميل البرنامج التدريبي النشط.'
      : 'The active program could not be loaded.';
  String exerciseNoLongerInProgram(String name) => isArabic
      ? 'لم يعد $name ضمن يوم البرنامج التدريبي.'
      : '$name is no longer in this program day.';
  String removeSetsQuestion(int count) => isArabic
      ? 'إزالة التمرين وحذف ${arabicCountPhrase(count, ArabicCountNoun.group, isolateCount: true)} المسجلة؟'
      : count == 1
          ? 'Remove and discard 1 logged set?'
          : 'Remove and discard $count logged sets?';
  String undoReplaceSetsQuestion(int count) => isArabic
      ? 'التراجع عن الاستبدال وحذف ${arabicCountPhrase(count, ArabicCountNoun.group, isolateCount: true)} المسجلة؟'
      : count == 1
          ? 'Undo replace and discard 1 logged set?'
          : 'Undo replace and discard $count logged sets?';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get offlineCachedProgram => isArabic
      ? 'غير متصل: يعرض البرنامج التدريبي المحفوظ.'
      : 'Offline: showing your cached program.';
  String get noDraftsYet => isArabic ? 'لا توجد مسودات بعد.' : 'No drafts yet.';
  String draftsCounts(int pending, int synced) => isArabic
      ? '${_ltr('$pending')} بانتظار المزامنة · ${_ltr('$synced')} تمت مزامنتها'
      : '$pending pending · $synced synced';
  String get syncNow => isArabic ? 'مزامنة الآن' : 'Sync now';
  String get offlineDraftsExplanation => isArabic
      ? 'تظهر هنا الحصص التي تسجلها دون اتصال حتى تتم مزامنتها.'
      : 'Workouts you log offline appear here until they sync.';
  String workingSetCount(int count) => isArabic
      ? arabicCountPhrase(
          count,
          ArabicCountNoun.trainingSet,
          isolateCount: true,
        )
      : '$count working sets';
  String get editDate => isArabic ? 'تعديل التاريخ' : 'Edit date';
  String get correctDate => isArabic ? 'تصحيح التاريخ' : 'Correct date';
  String get discardDraft => isArabic ? 'حذف المسودة' : 'Discard draft';
  String get dateCorrected =>
      isArabic ? 'تم تصحيح التاريخ.' : 'Date corrected.';
  String draftStatus(String status) => isArabic
      ? switch (status) {
          'pending' => 'بانتظار المزامنة',
          'syncing' => 'بانتظار المزامنة',
          'synced' => 'تمت المزامنة',
          'needs_reconciliation' => 'تحتاج إلى مراجعة',
          _ => 'مسودة تدريبية',
        }
      : switch (status) {
          'pending' || 'syncing' => 'Pending',
          'synced' => 'Synced',
          'needs_reconciliation' => 'Needs attention',
          _ => status,
        };
  String historicalProgram(int captured, int current) => isArabic
      ? 'سُجلت الحصة على البرنامج التدريبي ${_ltr('v$captured')} (الحالي ${_ltr('v$current')})'
      : 'Logged against program v$captured (current v$current)';
  String get androidDraftsUnavailable => isArabic
      ? 'مسودات الحصص دون اتصال متاحة في تطبيق Android.'
      : 'Offline workout drafts are available in the Android app.';
  String previousPerformance(String values) =>
      isArabic ? 'السابق: ${_ltr(values)}' : 'Last: $values';
  String prescriptionSetCount(int count) {
    if (!isArabic) return count == 1 ? '1 set' : '$count sets';
    final String phrase = arabicCountPhrase(count, ArabicCountNoun.group);
    final RegExpMatch? leadingCount = RegExp(r'^\d+').firstMatch(phrase);
    if (leadingCount == null) return phrase;
    return '${_ltr(leadingCount[0]!)}${phrase.substring(leadingCount.end)}';
  }

  String prescriptionReps(int minimum, int maximum) => isArabic
      ? '${_ltr('$minimum–$maximum')} تكرارات'
      : '$minimum–$maximum reps';
  String prescriptionWeight(String value) =>
      isArabic ? _ltr('$value kg') : '$value kg';
  String prescriptionRir(String value) =>
      isArabic ? _ltr('RIR $value') : 'RIR $value';
  String prescriptionRest(String time, {bool numericTime = true}) =>
      isArabic ? 'راحة ${numericTime ? _ltr(time) : time}' : 'Rest $time';

  String trainingStatusLine(TrainingStatusSummaryLine line) {
    if (!isArabic) return line.englishText;
    return switch (line) {
      WeeklyStreakSummaryLine(:final weeks) =>
        'أسابيع الالتزام المتتالية: ${_ltr('$weeks')}',
      WeeklyCompletionSummaryLine(:final completed, :final target) =>
        'هذا الأسبوع: ${_ltr('$completed')} من ${_ltr('$target')} مكتملة',
      CheckpointProgressSummaryLine(:final remaining, :final checkpoint) =>
        '${_arabicCountWithIsolatedNumber(remaining, ArabicCountNoun.trainingSession)} للوصول إلى محطة التقدم رقم ${_ltr('$checkpoint')}',
      CheckpointReachedSummaryLine(:final number) => checkpointWorkout(number),
    };
  }

  String _arabicCountWithIsolatedNumber(int count, ArabicCountNoun noun) {
    final String phrase = arabicCountPhrase(count, noun);
    final RegExpMatch? leadingCount = RegExp(r'^\d+').firstMatch(phrase);
    if (leadingCount == null) return phrase;
    return '${_ltr(leadingCount[0]!)}${phrase.substring(leadingCount.end)}';
  }

  String _ltr(String value) => '\u2066$value\u2069';

  static String _ordinal(int number) {
    if (number % 100 >= 11 && number % 100 <= 13) return '${number}th';
    return '$number${switch (number % 10) {
      1 => 'st',
      2 => 'nd',
      3 => 'rd',
      _ => 'th'
    }}';
  }
}
