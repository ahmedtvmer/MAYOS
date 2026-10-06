import '../app_failure.dart';
import '../password_policy.dart';
import '../checkpoint_ordinal.dart';
import '../effort.dart';
import '../exercise_filters.dart';
import '../personal_records.dart';
import 'arabic_count.dart';
import 'message_resolver.dart';

/// Small hand-written app catalog entry point. Product copy is added here as
/// each surface joins the account Display language workflow.
const supportedDisplayLanguages = <String>{'en', 'ar'};

bool isSupportedDisplayLanguage(Object? value) =>
    value is String && supportedDisplayLanguages.contains(value);

String normalizeDisplayLanguage(Object? value) =>
    isSupportedDisplayLanguage(value) ? value! as String : 'en';

String exerciseNameOrFallback(String? name, String languageCode) {
  final String? normalizedName = name?.trim();
  if (normalizedName != null && normalizedName.isNotEmpty) return normalizedName;
  return MayosCopy(languageCode).exerciseFallbackName;
}

class MayosCopy {
  const MayosCopy(this.languageCode);
  final String languageCode;
  bool get isArabic => languageCode == 'ar';
  String get home => isArabic ? 'الرئيسية' : 'Home';
  String get program => isArabic ? 'البرنامج التدريبي' : 'Program';
  String get progress => isArabic ? 'التقدم' : 'Progress';
  String get assistant => isArabic ? 'المساعد' : 'Assistant';
  String get requestFromCoach =>
      isArabic ? 'طلب من المدرب' : 'Request from coach';
  String get askAssistant => isArabic ? 'اسأل المساعد' : 'Ask the assistant';
  String get openAssistant => isArabic ? 'فتح المساعد' : 'Open assistant';
  String get wantDifferentProgramAskAssistant => isArabic
      ? 'هل تريد برنامجًا تدريبيًا مختلفًا؟ اسأل المساعد.'
      : 'Want a different program? Ask the assistant.';
  String get coachManagesProgram => isArabic
      ? 'يدير مدربك هذا البرنامج التدريبي.'
      : 'Your coach manages this program.';
  String coachPreparingProgram(String coachName) => isArabic
      ? 'مدربك $coachName يُعدّ برنامجك التدريبي. ستتدرب على برنامج مبدئي حتى ذلك الحين.'
      : "Your coach, $coachName, is preparing your program. You're on a starting program until then.";
  String get programChangeRequestSent => isArabic
      ? 'أُرسل طلب تغيير البرنامج التدريبي إلى مدربك.'
      : 'Your program change request was sent to your coach.';
  String get back => isArabic ? 'رجوع' : 'Back';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';
  String get clear => isArabic ? 'مسح' : 'Clear';
  String get send => isArabic ? 'إرسال' : 'Send';
  String get understood => isArabic ? 'فهمت' : 'I understand';
  String get beforeYouStart => isArabic ? 'قبل أن تبدأ' : 'Before you start';
  String get clearChatHistory =>
      isArabic ? 'مسح سجل المحادثة' : 'Clear chat history';
  String get clearChatHistoryQuestion =>
      isArabic ? 'هل تريد مسح سجل المحادثة؟' : 'Clear chat history?';
  String get clearChatHistoryConfirmation => isArabic
      ? 'سيؤدي هذا إلى حذف سجل محادثتك مع المساعد نهائيًا.'
      : 'This permanently deletes your assistant chat history.';
  String get sessionDebrief => isArabic ? 'ملخص الحصة' : 'Session debrief';
  String get assistantReplying =>
      isArabic ? 'المساعد يرد…' : 'Assistant is replying…';
  String get messageAssistant =>
      isArabic ? 'أرسل رسالة إلى المساعد' : 'Message your assistant';
  String chatCharactersLeft(int count) => isArabic
      ? 'المتبقي: ${arabicCountPhrase(
          count,
          ArabicCountNoun.character,
          isolateCount: true,
        )}'
      : '$count character${count == 1 ? '' : 's'} left';
  String get offline => isArabic ? 'غير متصل' : 'Offline';
  String get offlineBanner =>
      isArabic ? 'أنت غير متصل بالإنترنت' : "You're offline";
  String get offlineChatSaved => isArabic
      ? 'غير متصل — يعرض سجل المحادثة المحفوظ. يتطلب الإرسال اتصالًا بالإنترنت.'
      : 'Offline — showing saved chat history. Sending needs a connection.';
  String get chatNeedsConnection => isArabic
      ? 'يتطلب استخدام المحادثة اتصالًا بالإنترنت.'
      : 'Chat needs a connection.';
  String get chatReconnectRetry => isArabic
      ? 'المحادثة تتطلب اتصالًا. اتصل بالإنترنت ثم أعد المحاولة.'
      : 'Chat needs a connection. Reconnect and retry.';
  String get assistantDidNotFinish => isArabic
      ? 'لم يكمل المساعد الرد. يُرجى إعادة المحاولة.'
      : 'The assistant did not finish. Please retry.';
  String get clearingHistoryNeedsConnection => isArabic
      ? 'يتطلب مسح السجل اتصالًا بالإنترنت.'
      : 'Clearing history needs a connection.';
  String get askAssistantAboutTraining => isArabic
      ? 'اسأل المساعد عن التدريب أو الأسلوب أو برنامجك التدريبي.'
      : 'Ask your assistant about training, technique, or your program.';
  String get acceptDisclosureToStartChatting => isArabic
      ? 'وافق على الإفصاح لبدء المحادثة.'
      : 'Accept the disclosure to start chatting.';
  String get hostedChatDisclosure => isArabic
      ? 'يرد على المحادثة نموذج ذكاء اصطناعي مستضاف. تُرسل رسالتك وسياق التدريب اللازم للإجابة إلى مزود النموذج. قد يتضمن النص الحر تفاصيل تكشف هويتك، لذا لا تكتب ما لا ترغب في معالجته هناك.'
      : 'Chat is answered by a hosted AI model. Your message and the training context needed to answer it are sent to that model provider. Free text can contain identifying details, so do not include anything you do not want processed there.';
  String get acceptDisclosureToEnableChat => isArabic
      ? 'وافق على الإفصاح أعلاه لتفعيل المحادثة.'
      : 'Accept the disclosure above to enable chat.';
  String get enableCoaching => isArabic ? 'تفعيل التدريب' : 'Enable coaching';
  String get coachCode => isArabic ? 'رمز المدرب من MAYOS' : 'MAYOS coach code';
  String get enterCoachCode => isArabic
      ? 'أنا مدرب — أدخل رمز المدرب'
      : "I'm a coach — enter coach code";
  String get skipForNow => isArabic ? 'تخطي الآن' : 'Skip for now';
  String get createMyProgram =>
      isArabic ? 'إنشاء برنامجي التدريبي' : 'Create my program';
  String get aboutYou => isArabic ? 'عنك' : 'About you';
  String get training => isArabic ? 'التدريب' : 'Training';
  String get healthAndRecovery =>
      isArabic ? 'الصحة والتعافي' : 'Health & recovery';
  String get startIntake => isArabic ? 'بدء الإجابة' : 'Start intake';
  String get setupOwnTraining =>
      isArabic ? 'إعداد تدريبك' : 'Set up your own training';
  String get setupLead => isArabic
      ? 'يحتاج وضع اللاعب إلى إجابات قصيرة لإعداد برنامجك التدريبي. ستبقى مهامك التدريبية كما هي.'
      : 'Player mode needs a short intake before it can build your program. Your coaching stays as it is.';
  String get backToCoachMode =>
      isArabic ? 'العودة إلى وضع المدرب' : 'Back to Coach mode';
  String get playerMode => isArabic ? 'وضع اللاعب' : 'Player mode';
  String get coachMode => isArabic ? 'وضع المدرب' : 'Coach mode';
  String get switchMode => isArabic ? 'تبديل الوضع' : 'Switch mode';
  String get ownTraining => isArabic ? 'تدريبك الشخصي' : 'Your own training';
  String get rosterAlertsProfile => isArabic
      ? 'قائمة اللاعبين والتنبيهات والملف الشخصي'
      : 'Your roster, alerts, and profile';
  String accountMode(bool coach) => isArabic
      ? 'الحساب والوضع. الوضع الحالي: ${coach ? 'وضع المدرب' : 'وضع اللاعب'}'
      : 'Account and mode. Current: ${coach ? 'Coach' : 'Player'} mode';
  String get checkpointReview =>
      isArabic ? 'مراجعة محطة التقدم' : 'Checkpoint review';
  String get checkpointLabel => isArabic ? 'محطة تقدم' : 'Checkpoint';
  String get openYourReview => isArabic ? 'افتح المراجعة' : 'Open your review';
  String get noActiveProgram =>
      isArabic ? 'لا يوجد برنامج تدريبي نشط' : 'No active program';
  String get generateProgramForNextSession => isArabic
      ? 'أنشئ برنامجًا تدريبيًا لعرض حصتك التالية هنا.'
      : 'Generate a program to see your next session here.';
  String get goToProgram =>
      isArabic ? 'الانتقال إلى البرنامج التدريبي' : 'Go to Program';
  String get thisWeek => isArabic ? 'هذا الأسبوع' : 'This week';
  String get personalRecords =>
      isArabic ? 'الأرقام القياسية الشخصية' : 'Personal records';
  String get logWorkout => isArabic ? 'تسجيل حصة تدريبية' : 'Log workout';
  String get substituteExercise =>
      isArabic ? 'تبديل التمرين' : 'Substitute exercise';
  String get substituteExerciseQuestion =>
      isArabic ? 'هل تريد تبديل التمرين؟' : 'Substitute exercise?';
  String get substitute => isArabic ? 'تبديل' : 'Substitute';
  String get substitutionUndone =>
      isArabic ? 'تم التراجع عن تبديل التمرين.' : 'Substitution undone.';
  String get undo => isArabic ? 'تراجع' : 'Undo';
  String get moreExerciseActions =>
      isArabic ? 'المزيد من الخيارات للتمرين' : 'More actions for exercise';
  String get checkpoints => isArabic ? 'محطات التقدم' : 'Checkpoints';
  String get noCheckpointsYet =>
      isArabic ? 'لا توجد محطات تقدم بعد.' : 'No Checkpoints yet.';
  String get strength => isArabic ? 'القوة' : 'Strength';
  String get volume => isArabic ? 'الحجم التدريبي' : 'Volume';
  String get estimatedOneRepMax =>
      isArabic ? 'الحد الأقصى التقديري لتكرار واحد' : 'Estimated 1RM';
  String get recentSessions => isArabic ? 'الحصص الأخيرة' : 'Recent sessions';
  String get viewExercise => isArabic ? 'عرض التمرين' : 'View exercise';
  String get countedSets =>
      isArabic ? 'مجموعات محسوبة لكل عضلة' : 'Weighted sets';
  String get days => isArabic ? 'أيام' : 'days';
  String get day => isArabic ? 'يوم' : 'day';
  String alsoReplaceOnOtherDays(int count) => isArabic
      ? 'استبدل أيضًا في ${arabicCountPhrase(count, ArabicCountNoun.day, afterPreposition: true)} ${count == 2 ? 'آخرين' : count >= 11 ? 'آخر' : count == 1 ? 'آخر' : 'أخرى'}'
      : 'Also replace on $count other days';
  String lastDaysCountedSetsPerMuscle(int count) => isArabic
      ? 'آخر ${arabicCountPhrase(count, ArabicCountNoun.day, afterPreposition: true)} · $workingSetsPerMuscle'
      : 'Last $count days · $workingSetsPerMuscle';
  String get allLoggedSessions =>
      isArabic ? 'كل الحصص المسجلة' : 'all logged sessions';
  String get backTooltip => isArabic ? 'رجوع' : 'Back';
  String get connectionFailure => isArabic
      ? 'يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء.'
      : 'This needs a connection. Nothing was changed.';
  String get unavailableLink => isArabic
      ? 'تعذر فتح هذا الرابط في المتصفح.'
      : 'Could not open this link in your browser.';
  String get watchExerciseVideo => isArabic ? 'مشاهدة فيديو التمرين' : 'Watch exercise video';
  String get unavailablePrivacyPolicy => isArabic
      ? 'تعذر فتح سياسة الخصوصية في المتصفح.'
      : 'Could not open the privacy policy in your browser.';
  String get omittedImage => isArabic ? 'صورة محذوفة' : 'Image omitted';
  String get pageNotFound => isArabic ? 'الصفحة غير موجودة' : 'Page not found';
  String get pageMissingLead => isArabic
      ? 'الصفحة التي تبحث عنها غير موجودة أو نُقلت.'
      : 'The page you are looking for does not exist or has moved.';
  String get goToHome => isArabic ? 'الانتقال إلى الرئيسية' : 'Go to home';
  String get brandTagline =>
      isArabic ? 'تقدّمٌ مدروس.' : 'Progress, Engineered.';
  String get noPlanAvailable => isArabic
      ? 'لا تتوفر خطة لهذا الحساب.'
      : 'No plan is available for this account.';
  String get playerPlanLabel => isArabic ? 'اللاعب' : 'Lifter';
  String get coachPlanLabel => isArabic ? 'المدرب' : 'Coach';
  String get ongoingPlanNotTrial => isArabic
      ? 'خطة مستمرة — ليست فترة تجريبية.'
      : 'Ongoing plan — not a trial.';
  String get includedFeatures =>
      isArabic ? 'ما الذي تتضمنه' : "What's included";
  String get automaticTrainingProgram =>
      isArabic ? 'برنامج تدريبي تلقائي' : 'Automatic training program';
  String get weeklyVolumeAndRecords => isArabic
      ? 'لوحة الحجم التدريبي والأرقام القياسية الأسبوعية'
      : 'Weekly volume and personal-record dashboard';
  String get coachingAssignmentBenefit =>
      isArabic ? 'علاقة تدريب مع مدربك' : 'Coaching assignment with your coach';
  String get coachProfileAndInvites => isArabic
      ? 'الملف الشخصي للمدرب ودعوات اللاعبين'
      : 'Coach profile and player invites';
  String get activeRosterWithStatus => isArabic
      ? 'قائمة اللاعبين النشطة وحالة علاقات التدريب'
      : 'Active roster with assignment status';
  String get canEndAssignments => isArabic
      ? 'إنهاء علاقات التدريب في أي وقت'
      : 'End or revoke assignments at any time';

  /// Renders typed app failures in one place and preserves server details.
  String failureMessage(FailureMessage failure) => switch (failure) {
        ServerFailureMessage serverFailure => resolveStructuredMessage(
            messageCode: serverFailure.messageCode,
            messageParams: serverFailure.messageParams,
            englishFallback: serverFailure.safeEnglishFallback,
            displayLanguage: languageCode,
          ),
        AppFailureMessage(:final id, :final englishMessage, :final value) =>
          !isArabic
              ? englishMessage
              : switch (id) {
                  AppFailureId.cannotReachService =>
                    'تعذر الاتصال بالخدمة. تحقق من اتصالك بالإنترنت.',
                  AppFailureId.serviceUnavailable =>
                    'الخدمة غير متاحة. حاول مجددًا.',
                  AppFailureId.requestFailed =>
                    'فشل الطلب (\u2066$value\u2069).',
                  AppFailureId.serviceRejected => 'رفضت الخدمة هذا الطلب.',
                  AppFailureId.mutationNeedsConnection => connectionFailure,
                  AppFailureId.invalidServiceData =>
                    'أعادت الخدمة بيانات بصيغة غير صالحة.',
                  AppFailureId.recoveryEmailNotConfirmed =>
                    'تعذر تأكيد البريد الإلكتروني للاسترداد. حاول مجددًا.',
                  AppFailureId.programVersionMismatch =>
                    'سُجلت هذه الحصة على إصدار أقدم من البرنامج.',
                  AppFailureId.coachProgramChanged =>
                    'تغيّر برنامج اللاعب. راجعه ثم أعد اعتماده.',
                  AppFailureId.invalidCheckInData =>
                    'أعادت الخدمة بيانات سجلات التواصل بصيغة غير صالحة.',
                  AppFailureId.invalidAssignmentNotices =>
                    'أعادت الخدمة بيانات الإشعارات بصيغة غير صالحة.',
                  AppFailureId.invalidProgramRequestData =>
                    'أعادت الخدمة بيانات طلبات البرنامج التدريبي بصيغة غير صالحة.',
                  AppFailureId.invalidProfileData =>
                    'أعادت الخدمة بيانات الملف الشخصي بصيغة غير صالحة.',
                  AppFailureId.invalidTrainingScheduleData =>
                    'أعادت الخدمة بيانات جدول التدريب بصيغة غير صالحة.',
                  AppFailureId.profileUpdateRequired =>
                    'تحتاج الخدمة إلى تحديث قبل تعديل هذا الملف. حاول مجددًا لاحقًا.',
                  AppFailureId.passwordResetFallback => resetPasswordFallback,
                  AppFailureId.chatAccountNotSignedIn => youAreNotSignedIn,
                  AppFailureId.chatReconnectRetry => chatReconnectRetry,
                  AppFailureId.assistantDidNotFinish => assistantDidNotFinish,
                  AppFailureId.clearingHistoryNeedsConnection =>
                    clearingHistoryNeedsConnection,
                  AppFailureId.draftNotSignedIn => 'لم تسجل الدخول.',
                  AppFailureId.draftUnavailable => 'لم تعد هذه الحصة متاحة.',
                  AppFailureId.draftMustBeSynced =>
                    'لا يمكن تصحيح إلا الحصص المتزامنة.',
                  AppFailureId.unexpectedSyncStatus =>
                    'أعادت الخدمة حالة غير متوقعة (\u2066$value\u2069).',
                  AppFailureId.googleUseWebButton =>
                    'استخدم زر تسجيل الدخول عبر Google للمتابعة.',
                  AppFailureId.googleNotConfigured =>
                    'تسجيل الدخول عبر Google غير مهيأ في هذا الإصدار.',
                  AppFailureId.googleUnavailable =>
                    'تسجيل الدخول عبر Google غير متاح على هذا الجهاز.',
                  AppFailureId.googleFailed =>
                    'فشل تسجيل الدخول عبر Google. حاول مجددًا.',
                  AppFailureId.googleMissingToken =>
                    'لم يُعِد Google رمز تسجيل الدخول. حاول مجددًا.',
                  AppFailureId.googleCannotReach =>
                    'تعذر الاتصال بـ Google. تحقق من اتصالك وحاول مجددًا.',
                  AppFailureId.googleDeleteCancelled =>
                    'أُلغي تسجيل الدخول عبر Google. لم يُحذف حسابك.',
                },
      };
  String warmupPrescription(int sets, int reps, int restSeconds) => isArabic
      ? '${_ltr('$sets × $reps')} · ${restTime(restSeconds)}'
      : '$sets × $reps · rest ${restSeconds}s';
  String get deloadApplied =>
      isArabic ? 'تم تطبيق تخفيف التدريب' : 'Deload applied';
  String get deloadSuggested =>
      isArabic ? 'اقتُرح تخفيف التدريب' : 'Deload suggested';
  String get fatigueSignalDetected =>
      isArabic ? 'ظهرت إشارة إلى الإرهاق.' : 'Fatigue signal detected.';
  String deloadChangeSummary({
    required bool applied,
    required bool suggested,
    required double volumeMultiplier,
    required double? intensityCapRpe,
  }) {
    final List<String> changes = <String>[];
    if (volumeMultiplier < 1.0) {
      final int targetVolume = (volumeMultiplier * 100).round();
      changes.add('خُفضت المجموعات إلى ${_ltr('$targetVolume%')} من البرنامج');
    }
    if (intensityCapRpe != null) {
      changes.add(
        'ضُبط الجهد عند RIR ${_ltr(minRirLabel(intensityCapRpe))}',
      );
    }
    if (changes.isEmpty) {
      return applied
          ? 'لم تُطبق تغييرات على المجموعات أو RIR.'
          : 'لم تُقترح تغييرات على المجموعات أو RIR. أُبلغ مدربك.';
    }
    final String action = applied ? 'تم التطبيق' : 'عند التطبيق';
    final String coachNote = suggested ? ' أُبلغ مدربك.' : '';
    return '$action: ${changes.join(' · ')}.$coachNote';
  }

  String pendingWorkoutDrafts(int count) => isArabic
      ? '${arabicCountPhrase(count, ArabicCountNoun.workoutDraft)} بانتظار المزامنة'
      : '$count ${count == 1 ? 'workout draft' : 'workout drafts'} waiting to sync';
  String daysInWeek(int value) => isArabic
      ? '${arabicCountPhrase(value, ArabicCountNoun.day)} في الأسبوع'
      : '$value ${value == 1 ? 'day' : 'days'} per week';
  String moreActionsForExercise(String exerciseName) => isArabic
      ? 'المزيد من الخيارات للتمرين $exerciseName'
      : 'More actions for $exerciseName';
  String onboardingProgress(int answered, int total) => isArabic
      ? 'التقدم: أُجيب عن $answered من $total'
      : 'Progress: $answered of $total answered';
  String dayCount(int count) =>
      isArabic ? arabicCountPhrase(count, ArabicCountNoun.day) : '$count days';
  String programFrequency(int count) => isArabic
      ? '${arabicCountPhrase(count, ArabicCountNoun.day)} في الأسبوع'
      : '$count ${count == 1 ? 'day' : 'days'}/week';
  String get reviewing => isArabic ? 'مراجعة' : 'Review';
  String get continueAction => isArabic ? 'متابعة' : 'Continue';
  String greetingFor(DateTime now) => isArabic
      ? (now.hour < 5
          ? 'مساء الخير'
          : now.hour < 12
              ? 'صباح الخير'
              : now.hour < 17
                  ? 'طاب يومك'
                  : 'مساء الخير')
      : (now.hour < 5
          ? 'Good evening'
          : now.hour < 12
              ? 'Good morning'
              : now.hour < 17
                  ? 'Good afternoon'
                  : 'Good evening');
  String get noSetsLastWeek => isArabic
      ? 'لم تُسجل مجموعات خلال آخر ${arabicCountPhrase(7, ArabicCountNoun.day)}.'
      : 'No sets logged in the last 7 days.';
  String get noPersonalRecords =>
      isArabic ? 'لا توجد أرقام قياسية شخصية بعد.' : 'No personal records yet.';
  String personalRecordType(String type) =>
      switch (PrRecordKind.fromRecordType(type)) {
        PrRecordKind.weight => isArabic ? 'أثقل وزن' : 'Heaviest weight',
        PrRecordKind.e1rm => isArabic ? 'أفضل e1RM' : 'Best e1RM',
        PrRecordKind.mostReps =>
          isArabic ? 'أكبر عدد من التكرارات' : 'Most reps',
        null => type,
      };
  String personalRecordReps(int count) => isArabic
      ? arabicCountPhrase(count, ArabicCountNoun.repetition, isolateCount: true)
      : '$count reps';
  String get loadHomeFailed =>
      isArabic ? 'تعذر تحميل الصفحة الرئيسية.' : 'Could not load your home.';
  String get offlineSavedProgram => isArabic
      ? 'غير متصل — يعرض البرنامج التدريبي المحفوظ.'
      : 'Offline — showing your saved program.';
  String get noSetsRecordedForExercise => isArabic
      ? 'لا توجد مجموعات مسجلة لهذا التمرين بعد. سجّل حصة تدريبية لبدء متابعة التقدم.'
      : 'No sets recorded for this exercise yet. Log a workout to start a trend.';
  String countedSetsMetric(
    num total, {
    bool roundNearInteger = false,
  }) {
    final num displayTotal =
        roundNearInteger && (total - total.roundToDouble()).abs() < 0.05
            ? total.roundToDouble()
            : total;
    final String count = _formatCount(displayTotal);
    if (!isArabic) return '$count weighted sets';
    if (displayTotal == displayTotal.roundToDouble()) {
      final int integerCount = displayTotal.round();
      if (integerCount == 1) return 'مجموعة محسوبة واحدة لكل عضلة';
      if (integerCount == 2) return 'مجموعتان محسوبتان لكل عضلة';
      return '${arabicCountPhrase(integerCount, ArabicCountNoun.group, isolateCount: true)} محسوبة لكل عضلة';
    }
    return '${_ltr(count)} مجموعة محسوبة لكل عضلة';
  }

  String get noTrainingHistory =>
      isArabic ? 'لا يوجد سجل تدريب بعد' : 'No training history yet';
  String get homeHistoryLead => isArabic
      ? 'سجّل حصة تدريبية لعرض تقدم القوة والحجم التدريبي لكل تمرين هنا.'
      : 'Log a workout and your strength trend, volume, and per-exercise history will show here.';
  String get noActiveProgramYet => isArabic
      ? 'لا يوجد برنامج تدريبي نشط بعد. أكمل إعدادك لإنشاء برنامج.'
      : 'No active program yet. Complete onboarding to build one.';
  String get everyExerciseMatchInDay => isArabic
      ? 'كل النتائج موجودة بالفعل في هذا اليوم.'
      : 'Every match is already in this day.';
  String get everyExerciseMatchInWorkout => isArabic
      ? 'كل النتائج موجودة بالفعل في هذه الحصة.'
      : 'Every match is already in this workout.';
  String get offlineProgramBanner => isArabic
      ? 'غير متصل — يعرض البرنامج المحفوظ'
      : 'Offline — showing saved program';
  String get warmup => isArabic ? 'الإحماء' : 'Warm-up';
  String get workingSets => isArabic ? 'مجموعات التدريب' : 'Working sets';
  String get cardio => isArabic ? 'تمارين اللياقة' : 'Cardio';
  String get formerCoach => isArabic ? 'المدرب السابق' : 'Former coach';
  String get publishedByCoach =>
      isArabic ? 'نشره مدربك' : 'Published by your coach';
  String get suggestedSubstitutes =>
      isArabic ? 'التمارين البديلة المقترحة' : 'Suggested substitutes';
  String get searchExerciseCatalog =>
      isArabic ? 'ابحث في مكتبة التمارين' : 'Search the exercise catalog';
  String get primaryMuscle => isArabic ? 'العضلة الأساسية' : 'Primary muscle';
  String primaryMuscleFilterLabel(int selectedCount) => selectedCount == 0
      ? primaryMuscle
      : '$primaryMuscle ($selectedCount)';
  String primaryMuscleLabel(String muscle) {
    for (final PrimaryMuscle primaryMuscle in primaryMuscles) {
      if (primaryMuscle.apiValue == muscle) {
        return isArabic ? primaryMuscle.arabicLabel : muscle;
      }
    }
    return muscle;
  }
  String get done => isArabic ? 'تم' : 'Done';
  String get addUnplannedExercise =>
      isArabic ? 'إضافة تمرين غير مخطط' : 'Add unplanned exercise';
  String get search => isArabic ? 'بحث' : 'Search';
  String get typeExerciseName =>
      isArabic ? 'أدخل اسم تمرين للبحث.' : 'Type an exercise name to search.';
  String get noMatchingExercise =>
      isArabic ? 'لم يُعثر على تمرين مطابق.' : 'No matching exercise found.';
  String noMuscleExerciseMatched(String muscle) => isArabic
      ? 'لم يُعثر على تمرين لعضلة \u2066$muscle\u2069.'
      : 'No $muscle exercise matched.';
  String muscleFilterLabel(String muscle) =>
      isArabic ? 'العضلة: \u2066$muscle\u2069' : 'Muscle: $muscle';
  String get clearMuscleFilter =>
      isArabic ? 'مسح مرشح العضلة' : 'Clear the muscle filter';
  String warmupSetCount(int count) => isArabic
      ? arabicCountPhrase(
          count,
          ArabicCountNoun.warmupSet,
          isolateCount: true,
        )
      : '$count ${count == 1 ? 'warm-up set' : 'warm-up sets'}';
  String get programNeedsRefresh => isArabic
      ? 'تغير برنامجك. حدّث الصفحة قبل تبديل التمرين.'
      : 'Your program changed. Refresh before substituting.';
  String get programAuthorityChanged => isArabic
      ? 'تغيرت صلاحية تعديل البرنامج مجددًا. حاول مرة أخرى.'
      : 'Program authority changed again. Try once more.';
  String get programChangedChooseAgain => isArabic
      ? 'تغير البرنامج. اختر التمرين والبديل مرة أخرى.'
      : 'The program changed. Choose the exercise and replacement again.';
  String get authorityChangedDirectSwap => isArabic
      ? 'تغيرت صلاحية تعديل البرنامج. جارٍ تبديل التمرين مباشرة.'
      : 'Program authority changed. Continuing with direct substitution.';
  String get authorityChangedRequestCoach => isArabic
      ? 'تغيرت صلاحية تعديل البرنامج. جارٍ إرسال طلب إلى مدربك.'
      : 'Program authority changed. Opening a request for your coach.';
  String substitutionRequestSent(String oldExercise, String newExercise) =>
      isArabic
          ? 'طُلب من مدربك تبديل $oldExercise بـ $newExercise.'
          : 'Your coach has been asked to replace $oldExercise with $newExercise.';
  String substitutionApplied(String oldExercise, String newExercise) => isArabic
      ? 'تم تبديل $oldExercise بـ $newExercise.'
      : '$oldExercise replaced with $newExercise.';
  String noSetsForExercise(String name) => isArabic
      ? 'لا توجد مجموعات مسجلة لهذا التمرين بعد. سجّل حصة تدريبية لبدء متابعة التقدم.'
      : 'No sets recorded for $name yet. Log a workout to start a trend.';
  String get oneSessionTrendNeedsMore => isArabic
      ? 'سُجلت حصة واحدة فقط. يلزم تسجيل حصتين على الأقل لمتابعة التقدم.'
      : 'Only one session logged. A trend needs at least two sessions.';
  String get bodyWeight => isArabic ? 'وزن الجسم' : 'Body weight';
  String get targetWeight => isArabic ? 'الوزن المستهدف' : 'Target weight';
  String targetWeightLabel(String value) => isArabic
      ? '$targetWeight · ${_ltr('$value kg')}'
      : '$targetWeight · $value kg';
  String chartReferenceValue(String label, String value, String unit) =>
      isArabic ? '$label: ${_ltr('$value $unit')}' : '$label: $value $unit';
  String get logWeight => isArabic ? 'تسجيل الوزن' : 'Log weight';
  String get weightHistoryEmpty => isArabic
      ? 'سجّل وزنك لبدء متابعة التغيّر عبر الوقت.'
      : 'Log your weight to start tracking changes over time.';
  String get addWeightEntry => isArabic ? 'إضافة وزن اليوم' : 'Add today’s weight';
  String get weightEntryTitle => isArabic ? 'تسجيل الوزن' : 'Log today’s weight';
  String weightEntrySaved(String date) => isArabic
      ? 'تم تسجيل الوزن بتاريخ \u2066$date\u2069.'
      : 'Weight logged for $date.';
  String get weightKg => isArabic ? 'الوزن (\u2066kg\u2069)' : 'Weight (kg)';
  String weightRange(String minimum, String maximum) => isArabic
      ? 'يجب أن يكون الوزن بين ${_ltr('$minimum kg')} و${_ltr('$maximum kg')}.'
      : 'Weight must be between $minimum and $maximum kg.';
  String countedSetsLogged(int days) => isArabic
      ? 'لم تُسجل مجموعات محسوبة لكل عضلة خلال آخر ${arabicCountPhrase(days, ArabicCountNoun.day, afterPreposition: true)}.'
      : 'No weighted sets logged in the last $days days.';
  String get countedSetsExplanation => isArabic
      ? 'تُحسب مجموعة التدريب بقيمة 1 للعضلة الأساسية و0.5 لكل عضلة مساعدة.'
      : 'Primary muscle counts 1 per working set, each secondary 0.5.';
  String get logToSeeHistory => isArabic
      ? 'سجّل حصة تدريبية لعرض تقدم القوة والحجم التدريبي وسجل كل تمرين هنا.'
      : 'Log a workout and your strength trend, volume, and per-exercise records will appear here.';
  String chartNoSessions(String metric, String exercise) => isArabic
      ? 'لا توجد حصص مسجلة لتمرين $exercise في مقياس $metric.'
      : '$metric for $exercise: no sessions.';
  String chartOneSession(String metric, String exercise, String date,
          String value, String unit) =>
      isArabic
          ? '$metric لتمرين $exercise: حصة واحدة بتاريخ $date، $value $unit.'
          : '$metric for $exercise: 1 session on $date, $value $unit.';
  String chartManySessions(String metric, String exercise, int count,
          String first, String last, String value, String unit) =>
      isArabic
          ? '$metric لتمرين $exercise: ${arabicCountPhrase(count, ArabicCountNoun.session)} من $first إلى $last، وآخر قيمة $value $unit.'
          : '$metric for $exercise, $count sessions from $first to $last, latest $value $unit.';
  String get session => isArabic ? 'الحصة' : 'Session';
  String repetitionValue(String value, String reps,
      {bool includeRepsUnit = false, String weightUnit = 'kg'}) {
    final String measuredWeight =
        weightUnit.isEmpty ? value : '$value $weightUnit';
    if (!isArabic) {
      return '$measuredWeight × $reps${includeRepsUnit ? ' reps' : ''}';
    }
    final int? count = int.tryParse(reps);
    final String repetitionLabel = count == null
        ? '${_ltr(reps)} تكرارات'
        : arabicCountPhrase(
            count,
            ArabicCountNoun.repetition,
            isolateCount: true,
          );
    return '${_ltr(measuredWeight)} × $repetitionLabel';
  }

  String get estimatedOneRepMaxShort => 'e1RM';
  String dayHeading(int order, String name) =>
      isArabic ? 'اليوم $order: $name' : 'Day $order: $name';
  String nextSessionLabel(int? weekday) {
    if (weekday == null) return isArabic ? 'الحصة التالية' : 'Next session';
    const List<String> englishWeekdays = <String>[
      'Mon',
      'Tue',
      'Wed',
      'Thu',
      'Fri',
      'Sat',
      'Sun',
    ];
    const List<String> arabicWeekdays = <String>[
      'الاثنين',
      'الثلاثاء',
      'الأربعاء',
      'الخميس',
      'الجمعة',
      'السبت',
      'الأحد',
    ];
    final String weekdayName =
        (isArabic ? arabicWeekdays : englishWeekdays)[weekday - 1];
    return '${isArabic ? 'الحصة التالية' : 'Next session'} · $weekdayName';
  }

  String shortDate(DateTime date) {
    const List<String> englishMonths = <String>[
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ];
    const List<String> arabicMonths = <String>[
      'يناير',
      'فبراير',
      'مارس',
      'أبريل',
      'مايو',
      'يونيو',
      'يوليو',
      'أغسطس',
      'سبتمبر',
      'أكتوبر',
      'نوفمبر',
      'ديسمبر',
    ];
    final String monthName =
        (isArabic ? arabicMonths : englishMonths)[date.month - 1];
    return isArabic ? '${date.day} $monthName' : '$monthName ${date.day}';
  }

  String suggestedSubstitutesFor(String names) => isArabic
      ? 'التمارين البديلة المقترحة: $names'
      : 'Suggested substitutes: $names';
  String get loadExerciseFailed =>
      isArabic ? 'تعذر تحميل التمرين.' : 'Could not load this exercise.';
  String get exerciseUnavailable =>
      isArabic ? 'هذا التمرين غير متاح.' : 'This exercise is not available.';
  String get exerciseFallbackName => exercise;
  String get exerciseMediaUnavailable =>
      isArabic ? 'وسائط التمرين غير متاحة' : 'Exercise media unavailable';
  String get enterCoachCodeLead =>
      isArabic ? 'أدخل رمز المدرب من MAYOS.' : 'Enter your MAYOS coach code.';
  String get loadCheckpointFailed => isArabic
      ? 'تعذر تحميل مراجعة محطة التقدم.'
      : 'Could not load this Checkpoint review.';
  String checkpointWorkout(int count) => isArabic
      ? 'حصتك التدريبية رقم $count'
      : 'Your ${checkpointOrdinal(count)} workout';
  String restTime(int seconds) => isArabic
      ? 'راحة ${arabicCountPhrase(seconds, ArabicCountNoun.second, afterPreposition: true, isolateCount: true)}'
      : 'rest ${seconds}s';
  String get category => isArabic ? 'الفئة' : 'Category';
  String get bodyPart => isArabic ? 'جزء الجسم' : 'Body part';
  String get equipment => isArabic ? 'المعدات' : 'Equipment';
  String get notes => isArabic ? 'ملاحظات' : 'Notes';
  String get noExerciseDetails => isArabic
      ? 'لا تتوفر تفاصيل لهذا التمرين.'
      : 'No details are available for this exercise.';
  String get noInstructionsForExercise => isArabic
      ? 'لا تتوفر تعليمات لهذا التمرين حاليًا.'
      : "Instructions aren't available for this exercise yet.";
  String get noExerciseHistory => isArabic
      ? 'لا يوجد سجل لهذا التمرين بعد. سجّل حصة تدريبية لعرضه هنا.'
      : 'No history for this exercise yet. Log a workout to see it here.';
  String get exercise => isArabic ? 'التمرين' : 'Exercise';
  String get reps => isArabic ? 'تكرارات' : 'reps';
  String get youAreNotSignedIn =>
      isArabic ? 'لم تسجل الدخول.' : 'You are not signed in.';
  String get beforeWeBegin => isArabic ? 'قبل أن نبدأ' : 'Before we begin';
  String get reviewSetup => isArabic ? 'راجع إعدادك' : 'Review your setup';
  String get reviewSetupLead => isArabic
      ? 'راجع إجاباتك. يمكنك تعديلها قبل أن ينشئ MAYOS برنامجك التدريبي الأول.'
      : 'Check your answers. You can edit anything before MAYOS builds your first program.';
  String get requiredAnswersMissing => isArabic
      ? 'ما زالت بعض الإجابات المطلوبة ناقصة.'
      : 'Some required answers are still missing.';
  String get hostedAIProcessing => isArabic
      ? 'معالجة عبر الذكاء الاصطناعي المستضاف'
      : 'Hosted AI processing';
  String get onboardingHostedDisclosure => isArabic
      ? 'يعتمد إعداد التدريب على مزود ذكاء اصطناعي مستضاف. تُرسل إجاباتك وسياق التدريب اللازم للرد لمعالجتهما. قد يتضمن النص الحر معلومات شخصية، لذا تجنب مشاركة ما لا ترغب في معالجته.'
      : 'Onboarding is powered by a hosted AI provider. The answers you type and the training context needed to respond are sent for processing. Free text you write may contain personal information, so avoid sharing anything you do not want processed.';
  String get onboardingPrivacyNote => isArabic
      ? 'لن يُرسل شيء حتى تتابع. يمكنك تغيير أي إجابة قبل إنشاء برنامجك.'
      : 'Nothing is sent until you continue. You can change any answer before your program is created.';
  String get setupLoadFailed =>
      isArabic ? 'تعذر تحميل إعدادك' : 'Could not load your setup';
  String get buildingYourProgram =>
      isArabic ? 'جارٍ إنشاء برنامجك التدريبي' : 'Building your program';
  String get answersSavedBuilding => isArabic
      ? 'قد يستغرق هذا بعض الوقت. حُفظت إجاباتك.'
      : 'This can take a moment. Your answers are saved.';
  String get genericError => isArabic ? 'حدث خطأ ما.' : 'Something went wrong.';
  String get programBeingGenerated => isArabic
      ? 'يجري إنشاء برنامج تدريبي بالفعل. انتظر قليلًا ثم أعد المحاولة.'
      : 'A program is already being generated. Give it a moment and retry.';
  String enterNumberBetween(String min, String max) => isArabic
      ? 'أدخل رقمًا بين $min و$max.'
      : 'Enter a number between $min and $max.';
  String get chooseOptionToContinue =>
      isArabic ? 'اختر خيارًا للمتابعة.' : 'Choose an option to continue.';
  String get writeAtLeastTwoCharacters =>
      isArabic ? 'اكتب حرفين على الأقل.' : 'Write at least 2 characters.';
  String get review => isArabic ? 'مراجعة' : 'Review';
  String get savedFromEarlierSetup =>
      isArabic ? 'حُفظت من إعدادك السابق' : 'Saved from your earlier setup';
  String get typeYourAnswer => isArabic ? 'اكتب إجابتك' : 'Type your answer';
  String get none => isArabic ? 'لا شيء' : 'None';
  String selectionSemantics(String title, String caption, bool selected) =>
      isArabic
          ? '$title. $caption ${selected ? 'محدد' : 'غير محدد'}'
          : '$title. $caption ${selected ? 'Selected' : 'Not selected'}';
  String get decrease => isArabic ? 'تقليل' : 'Decrease';
  String get increase => isArabic ? 'زيادة' : 'Increase';
  String get useStepper =>
      isArabic ? 'استخدم أزرار الزيادة والنقصان' : 'Use the stepper';
  String get typeAValue => isArabic ? 'أدخل قيمة' : 'Type a value';
  String get chooseWeeklyTrainingDays => isArabic
      ? 'اختر أيام التدريب الأسبوعية'
      : 'Choose your weekly training days';
  String get tapExampleToStart =>
      isArabic ? 'اضغط على مثال للبدء' : 'Tap an example to start';
  String get workingSetsPerMuscle =>
      isArabic ? 'مجموعات محسوبة لكل عضلة' : 'working sets per muscle';
  String get period => isArabic ? 'الفترة' : 'Period';
  String get rating => isArabic ? 'التقييم' : 'Rating';
  String get overview => isArabic ? 'نظرة عامة' : 'Overview';
  String get technique => isArabic ? 'الأسلوب' : 'Technique';
  String get history => isArabic ? 'السجل' : 'History';
  String get setsAndReps => isArabic ? 'المجموعات × التكرارات' : 'Sets × reps';
  String get intensity => isArabic ? 'الشدة' : 'Intensity';
  String get rest => isArabic ? 'الراحة' : 'Rest';
  String get settings => isArabic ? 'الإعدادات' : 'Settings';
  String get displayLanguage => isArabic ? 'لغة العرض' : 'Display language';
  String get english => isArabic ? 'الإنجليزية' : 'English';
  String get arabic => isArabic ? 'العربية' : 'Arabic';
  String get save => isArabic ? 'حفظ' : 'Save';
  String get languageSaved =>
      isArabic ? 'تم حفظ لغة العرض.' : 'Display language saved.';
  String get languageSaveFailed =>
      isArabic ? 'تعذر حفظ لغة العرض.' : 'Could not save Display language.';
  String get logIn => isArabic ? 'تسجيل الدخول' : 'Log in';
  String get signIn => isArabic ? 'تسجيل الدخول' : 'Sign in';
  String get signInLead => isArabic
      ? 'سجّل الدخول لمواصلة التدريب من حيث توقفت.'
      : 'Sign in to keep training and pick up where you left off.';
  String get createAccount => isArabic ? 'إنشاء حساب' : 'Create account';
  String get createAccountLink => isArabic ? 'إنشاء حساب' : 'Create an account';
  String get registerLead => isArabic
      ? 'أنشئ حساب MAYOS لبدء التدريب.'
      : 'Set up your MAYOS account to start training.';
  String get forgotPassword =>
      isArabic ? 'نسيت كلمة المرور' : 'Forgot password';
  String get forgotPasswordQuestion =>
      isArabic ? 'نسيت كلمة المرور؟' : 'Forgot password?';
  String get resetPassword =>
      isArabic ? 'إعادة تعيين كلمة المرور' : 'Reset password';
  String get resetPasswordLead => isArabic
      ? 'اختر كلمة مرور جديدة لحسابك.'
      : 'Choose a new password for your account.';
  String get resetPasswordFallback => isArabic
      ? 'تعذر إعادة تعيين كلمة المرور. اطلب رابطًا جديدًا.'
      : 'Could not reset the password. Request a new link.';
  String get recoveryEmail =>
      isArabic ? 'البريد الإلكتروني للاسترداد' : 'Recovery email';
  String get chooseUsername =>
      isArabic ? 'اختر اسم المستخدم' : 'Choose your username';
  String get chooseUsernameLead => isArabic
      ? 'اختر الاسم الذي ستتدرب به. يجب أن يكون متاحًا.'
      : 'Pick the name you want to train under. It must be free.';
  String get privacyPolicy => isArabic ? 'سياسة الخصوصية' : 'Privacy policy';
  String get passwordChanged => isArabic
      ? 'تم تغيير كلمة المرور. سجّل الدخول بكلمة المرور الجديدة.'
      : 'Password changed. Sign in with your new password.';
  String get username => isArabic ? 'اسم المستخدم' : 'Username';
  String get password => isArabic ? 'كلمة المرور' : 'Password';
  String get confirmPassword =>
      isArabic ? 'تأكيد كلمة المرور' : 'Confirm password';
  String get newPassword => isArabic ? 'كلمة المرور الجديدة' : 'New password';
  String get showPassword => isArabic ? 'إظهار كلمة المرور' : 'Show password';
  String get hidePassword => isArabic ? 'إخفاء كلمة المرور' : 'Hide password';
  String get passwordMismatch =>
      isArabic ? 'كلمتا المرور غير متطابقتين.' : 'Passwords do not match.';
  String get passwordLength => isArabic
      ? 'استخدم $kMinPasswordLength أحرف على الأقل.'
      : 'Use at least $kMinPasswordLength characters.';
  String get passwordLengthHint => isArabic
      ? '$kMinPasswordLength أحرف على الأقل'
      : 'At least $kMinPasswordLength characters';
  String get keepMeSignedIn =>
      isArabic ? 'إبقائي مسجلًا للدخول' : 'Keep me signed in';
  String get iHaveCoachInvite => isArabic
      ? 'لدي رمز دعوة لتفعيل دور المدرب'
      : 'I have a coach invite code';
  String get hideCoachInvite =>
      isArabic ? 'إخفاء رمز دعوة لتفعيل دور المدرب' : 'Hide coach invite code';
  String get coachInviteCode =>
      isArabic ? 'رمز دعوة لتفعيل دور المدرب' : 'Coach invite code';
  String get alreadyHaveAccount =>
      isArabic ? 'لدي حساب بالفعل' : 'I already have an account';
  String get sendResetLink =>
      isArabic ? 'إرسال رابط إعادة التعيين' : 'Send reset link';
  String get backToLogIn =>
      isArabic ? 'العودة إلى تسجيل الدخول' : 'Back to log in';
  String get backToSignIn =>
      isArabic ? 'العودة إلى تسجيل الدخول' : 'Back to sign in';
  String get email => isArabic ? 'البريد الإلكتروني' : 'Email';
  String get setNewPassword =>
      isArabic ? 'تعيين كلمة مرور جديدة' : 'Set new password';
  String get requestNewLink =>
      isArabic ? 'طلب رابط جديد' : 'Request a new link';
  String get resetCode => isArabic ? 'رمز إعادة التعيين' : 'Reset code';
  String get saveEmail => isArabic ? 'حفظ البريد الإلكتروني' : 'Save email';
  String get verifyRecoveryEmail =>
      isArabic ? 'تأكيد البريد الإلكتروني' : 'Verify email';
  String get verificationCode => isArabic ? 'رمز التأكيد' : 'Verification code';
  String get sendVerificationCode => isArabic ? 'إرسال الرمز' : 'Send code';
  String get resendVerificationCode =>
      isArabic ? 'إعادة إرسال الرمز' : 'Resend code';
  String get changeRecoveryEmail =>
      isArabic ? 'تغيير البريد الإلكتروني' : 'Change email';
  String get recoveryCodeSent => isArabic
      ? 'أرسلنا رمزًا إلى بريدك الإلكتروني للاسترداد.'
      : 'We sent a code to your recovery email.';
  String get recoveryCodeError => isArabic
      ? 'الرمز غير صالح أو منتهي الصلاحية. اطلب رمزًا جديدًا.'
      : 'That code is invalid or expired. Request a new code.';
  String get recoveryCodeSendError => isArabic
      ? 'تعذر إرسال الرمز. يُرجى المحاولة مرة أخرى.'
      : 'Could not send the code. Please try again.';
  String get logOut => isArabic ? 'تسجيل الخروج' : 'Log out';
  String get createSeparateAccount => isArabic
      ? 'إنشاء حساب منفصل على أي حال'
      : 'Create a separate account anyway';
  String get existingAccountTitle => isArabic
      ? 'لديك حساب MAYOS لهذا البريد الإلكتروني بالفعل.'
      : 'You already have a MAYOS account for this email.';
  String get existingAccountLead => isArabic
      ? 'سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
      : 'Log in with your password, then connect Google in Settings.';
  String get existingAccountNudge => isArabic
      ? 'لديك حساب MAYOS بالفعل؟ سجّل الدخول بكلمة المرور، ثم اربط Google من الإعدادات.'
      : 'Already have a MAYOS account? Log in with your password, then connect Google in Settings';
  String get recoveryEmailLead => isArabic
      ? 'أضف بريدًا إلكترونيًا للاسترداد لتتمكن من إعادة تعيين كلمة المرور إذا فقدتها. سنرسل رمزًا لتأكيد ملكيتك لهذا العنوان.'
      : 'Add a recovery email so you can reset your password if you lose it. We will send a code to verify that you own this address.';
  String get recoveryEmailCodeLead => isArabic
      ? 'أدخل الرمز الذي أرسلناه إلى بريدك الإلكتروني للاسترداد.'
      : 'Enter the code we sent to your recovery email.';
  String get googleSignupIncomplete => isArabic
      ? 'تعذر إكمال تسجيل الدخول عبر Google، لذلك لم يتم إنشاء حساب.'
      : 'The Google sign-in could not be finished, so no account was created.';
  String get googleSignupExpired => isArabic
      ? 'انتهت صلاحية تسجيل الدخول عبر Google. يُرجى المحاولة مرة أخرى.'
      : 'Your Google sign-up expired. Please try again.';
  String get usernameFormatError => isArabic
      ? 'استخدم من 3 إلى 30 حرفًا من a–z و0–9 و_ و- (بحروف صغيرة).'
      : 'Use 3–30 characters from a–z, 0–9, _ and - (lowercase).';
  String get usernameTaken =>
      isArabic ? 'اسم المستخدم مستخدم بالفعل.' : 'That username is taken.';
  String get checkingAvailability =>
      isArabic ? 'جارٍ التحقق من التوفر…' : 'Checking availability…';
  String get usernameAvailable =>
      isArabic ? 'اسم المستخدم متاح.' : 'This username is free.';
  String get availabilityCheckFailed =>
      isArabic ? 'تعذر التحقق من التوفر.' : 'Could not check availability.';
  String get forgotEmailHint => isArabic
      ? 'أدخل بريد الاسترداد وسنرسل رابط إعادة التعيين. افتحه على هذا الجهاز لاختيار كلمة مرور جديدة.'
      : 'Enter your recovery email and we will send a reset link. Open it on this device to choose a new password.';
  String get resetRequestConfirmation => isArabic
      ? 'إذا كان هذا البريد الإلكتروني مرتبطًا بحساب، فسيصلك رابط إعادة التعيين قريبًا.'
      : 'If this email is linked to a ledger, a reset link is on its way.';
  String get noEmailHint => isArabic
      ? 'لم يصلك بريد؟ تحقق من العنوان،'
      : "Didn't get an email? Check the address,";
  String get signUp => isArabic ? 'أنشئ حسابًا' : 'sign up';
  String get forgotSettingsHint => isArabic
      ? 'أو سجّل الدخول وأضف بريدًا للاسترداد في الإعدادات.'
      : 'or log in and add a recovery email in Settings.';
  String get signInOr => isArabic ? 'أو' : 'or';
  String get homeScreenHint => isArabic
      ? 'أضف MAYOS: مشاركة ← إضافة إلى الشاشة الرئيسية.'
      : 'Add MAYOS: Share → Add to Home Screen.';
  String get dismissHomeScreenHint =>
      isArabic ? 'إخفاء تلميح الشاشة الرئيسية' : 'Dismiss Home Screen hint';
  String get googleName =>
      isArabic ? 'المتابعة مع Google' : 'Continue with Google';

  String _ltr(String value) => '\u2066$value\u2069';
}

String _formatCount(num value) => value == value.roundToDouble()
    ? value.round().toString()
    : value.toStringAsFixed(1);
