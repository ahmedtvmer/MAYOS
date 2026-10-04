import 'arabic_count.dart';

/// App-owned settings labels, personalization copy, and logout prompts.
class SettingsCopy {
  const SettingsCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get appearance => isArabic ? 'المظهر' : 'Appearance';
  String get appearanceLead => isArabic
      ? 'اختر مظهر MAYOS. يتبع خيار النظام إعداد جهازك.'
      : 'Choose how MAYOS looks. System follows your device.';
  String get system => isArabic ? 'النظام' : 'System';
  String get light => isArabic ? 'فاتح' : 'Light';
  String get dark => isArabic ? 'داكن' : 'Dark';
  String get personalization => isArabic ? 'التخصيص' : 'Personalization';
  String get assistantStyle => isArabic ? 'أسلوب المساعد' : 'Assistant style';
  String get account => isArabic ? 'الحساب' : 'Account';
  String get username => isArabic ? 'اسم المستخدم' : 'Username';
  String get linkedSignIn => isArabic ? 'تسجيل الدخول المرتبط' : 'Linked sign-in';
  String get linkedSignInSubtitle => isArabic
      ? 'إدارة كلمة المرور وتسجيل الدخول باستخدام Google'
      : 'Manage your password and Google sign-in';
  String get trainingProfile => isArabic ? 'الملف التدريبي' : 'Training profile';
  String get lifterPlan => isArabic ? 'خطة اللاعب' : 'Lifter plan';
  String get coachProfile => isArabic ? 'ملف المدرب' : 'Coach profile';
  String get editCoachProfile =>
      isArabic ? 'تعديل ملف المدرب' : 'Edit coach profile';
  String get coachPlan => isArabic ? 'خطة المدرب' : 'Coach plan';
  String get notifications => isArabic ? 'الإشعارات' : 'Notifications';
  String get notificationSettings =>
      isArabic ? 'عرض الإشعارات' : 'View notifications';
  String get coachNotificationsSubtitle => isArabic
      ? 'تنبيهات انتهاء الصلاحية واللاعبين الذين يحتاجون إلى متابعة'
      : 'Expiry and attention alerts';
  String get recoveryEmail => isArabic ? 'البريد الإلكتروني للاسترداد' : 'Recovery email';
  String get recoveryEmailVerified => isArabic ? 'تم التحقق' : 'Verified';
  String get recoveryEmailNotVerified => isArabic ? 'لم يتم التحقق' : 'Not verified';
  String get recoveryEmailNotSet => isArabic ? 'لم يُضف بريد إلكتروني' : 'Not set';
  String get recoveryEmailPendingChange =>
      isArabic ? 'بانتظار التحقق' : 'Awaiting verification';
  String get recoveryEmailLoading => isArabic ? 'جارٍ التحميل…' : 'Loading…';
  String get recoveryEmailLoadFailed => isArabic
      ? 'تعذر تحميل البريد الإلكتروني للاسترداد.'
      : 'Could not load the recovery email.';
  String get change => isArabic ? 'تغيير' : 'Change';
  String get changeRecoveryEmail =>
      isArabic ? 'تغيير البريد الإلكتروني للاسترداد' : 'Change recovery email';
  String get currentRecoveryEmail =>
      isArabic ? 'البريد الإلكتروني الحالي' : 'Current recovery email';
  String get newRecoveryEmail =>
      isArabic ? 'البريد الإلكتروني الجديد' : 'New recovery email';
  String get sendRecoveryEmailCode =>
      isArabic ? 'إرسال رمز التحقق' : 'Send verification code';
  String get recoveryEmailCodeLead => isArabic
      ? 'سنرسل رمزًا من 6 أرقام إلى البريد الإلكتروني الجديد. سيظل البريد الحالي للاسترداد حتى تؤكد التغيير.'
      : 'We will send a 6-digit code to the new address. Your current recovery email stays in use until you confirm the change.';
  String get recoveryEmailCodeSent => isArabic
      ? 'أرسلنا رمزًا إلى البريد الإلكتروني الجديد.'
      : 'We sent a code to the new recovery email.';
  String get pendingRecoveryEmail =>
      isArabic ? 'البريد الإلكتروني قيد التحقق' : 'Address awaiting verification';
  String get recoveryEmailCode =>
      isArabic ? 'رمز التحقق المكوّن من 6 أرقام' : '6-digit verification code';
  String get verifyAndChangeRecoveryEmail =>
      isArabic ? 'تأكيد التغيير' : 'Verify and change email';
  String get useDifferentRecoveryEmail =>
      isArabic ? 'استخدام بريد إلكتروني آخر' : 'Use a different email';
  String get recoveryEmailChanged => isArabic
      ? 'تم تغيير البريد الإلكتروني للاسترداد.'
      : 'Recovery email changed.';
  String get recoveryEmailChangeFailed => isArabic
      ? 'تعذر تغيير البريد الإلكتروني للاسترداد. تحقق من العنوان والرمز وحاول مرة أخرى.'
      : 'Could not change the recovery email. Check the address or code and try again.';
  String get recoveryEmailAlreadyLinked => isArabic
      ? 'هذا البريد الإلكتروني مرتبط بحساب آخر.'
      : 'This email is already linked to another account.';
  String get recoveryEmailChangeSuccessLead => isArabic
      ? 'أصبح البريد الإلكتروني الجديد عنوانك الموثق للاسترداد.'
      : 'The new address is now your verified recovery email.';
  String get enableCoaching =>
      isArabic ? 'تفعيل وضع المدرب' : 'Enable coaching';
  String get enableCoachingSubtitle => isArabic
      ? 'أدخل رمز المدرب الصادر من المالك'
      : 'Redeem an owner-issued coach code';
  String get training => isArabic ? 'التدريب' : 'Training';
  String get assistant => isArabic ? 'المساعد' : 'Assistant';
  String get assistantSubtitle =>
      isArabic ? 'تحدث عن تدريبك' : 'Chat about your training';
  String get workoutDrafts => isArabic ? 'مسودات الحصص' : 'Workout drafts';
  String get workouts => isArabic ? 'الحصص التدريبية' : 'Workouts';
  String get workoutDraftsSubtitle => isArabic
      ? 'محفوظة على هذا الجهاز وتتم مزامنتها عند الاتصال'
      : 'Saved on this device, syncing when online';
  String get about => isArabic ? 'حول التطبيق' : 'About';
  String get privacyPolicy => isArabic ? 'سياسة الخصوصية' : 'Privacy policy';
  String get privacySubtitle => isArabic
      ? 'ما يجمعه MAYOS، ومن يمكنه الاطلاع عليه، وكيفية الحذف'
      : 'What MAYOS collects, who can see it, and deletion';
  String get productAnalytics =>
      isArabic ? 'تحليلات المنتج' : 'Product analytics';
  String get allowAnalytics =>
      isArabic ? 'السماح بتحليلات المنتج' : 'Allow product analytics';
  String get analyticsDescription => isArabic
      ? 'يستخدم MAYOS خدمة PostHog (في الاتحاد الأوروبي) لقياس استخدام الميزات عبر أحداث بمعرّف مستعار. لا تتضمن الأحداث نصوصًا تكتبها. يمكنك إيقاف ذلك في أي وقت.'
      : 'MAYOS uses PostHog (EU) to measure feature use through pseudonymous events. Events exclude text you write. You can turn this off at any time.';
  String get analyticsSaveFailed => isArabic
      ? 'تعذر حفظ تفضيل التحليلات. حاول مرة أخرى.'
      : 'Could not save your analytics preference. Please try again.';
  String get credits => isArabic ? 'الاعتمادات' : 'Credits';
  String get logOut => isArabic ? 'تسجيل الخروج' : 'Log out';
  String get styleLead => isArabic
      ? 'اختر طريقة صياغة ردود المساعد في المحادثة. تبقى الحقائق وقرارات التدريب والسلامة ولغة الرد كما هي.'
      : 'Choose how your assistant words its chat replies. Facts, training decisions, safety, and reply language stay the same.';
  String stylePresetLabel(String key) => switch (key) {
        'direct' => directPragmatic,
        'encouraging' => encouraging,
        'scientific' => scientific,
        'tough_love' => toughLove,
        'concise' => concise,
        _ => isArabic ? 'أسلوب آخر' : 'Assistant style',
      };
  String stylePresetDescription(String key) => switch (key) {
        'direct' => directPragmaticDescription,
        'encouraging' => encouragingDescription,
        'scientific' => scientificDescription,
        'tough_love' => toughLoveDescription,
        'concise' => conciseDescription,
        _ => isArabic ? 'وصف الأسلوب' : 'Style description',
      };
  String get directPragmatic => isArabic ? 'مباشر وعملي' : 'Direct & pragmatic';
  String get directPragmaticDescription =>
      isArabic ? 'واضح وعملي.' : 'Clear and practical.';
  String get encouraging => isArabic ? 'مشجع' : 'Encouraging';
  String get encouragingDescription =>
      isArabic ? 'يقدّر الجهد.' : 'Recognizes effort.';
  String get scientific => isArabic ? 'علمي' : 'Scientific';
  String get scientificDescription =>
      isArabic ? 'يعتمد على الأدلة والتعليل.' : 'Evidence and reasoning.';
  String get toughLove => isArabic ? 'حازم باحترام' : 'Tough-love';
  String get toughLoveDescription =>
      isArabic ? 'حازم ومحترم.' : 'Firm, respectful.';
  String get concise => isArabic ? 'موجز' : 'Concise';
  String get conciseDescription =>
      isArabic ? 'ردود قصيرة ومركزة.' : 'Brief, focused replies.';
  String get styleSaved =>
      isArabic ? 'حُفظ أسلوب المساعد.' : 'Assistant style saved.';
  String get styleLoadFailed => isArabic
      ? 'تعذر تحميل أسلوب المساعد.'
      : 'Could not load Assistant style.';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get saveStyle => isArabic ? 'حفظ الأسلوب' : 'Save style';
  String get optionalInstructions =>
      isArabic ? 'تعليمات اختيارية' : 'Optional instructions';
  String get instructionsExample => isArabic
      ? 'مثلًا: اشرح المصطلحات باختصار.'
      : 'For example: explain terms briefly.';
  String get wordingOnly =>
      isArabic ? 'تُستخدم لصياغة الردود فقط.' : 'Used for wording only.';
  String creditsBody(String requiredCredit) => isArabic
      ? 'تُنسب صور التمارين ومقاطع GIF في المكتبة وفق شروط استخدامها:\n\n'
          '${_ltr(requiredCredit)}\n\n'
          'تُعرض الوسائط بحجمها الأصلي وبحد أقصى ${_ltr('180 × 180')} مع هذا الاعتماد، بينما لا يزال ترخيص MAYOS الخاص من Gym visual قيد الانتظار.'
      : 'Exercise media (the catalog pictures and GIFs) is credited as '
          'required by its terms:\n\n'
          '$requiredCredit\n\n'
          'The media is shown at its native size, never larger than 180 × 180, '
          'with this credit, while MAYOS\'s own licence from Gym visual is '
          'pending.';
  String get couldNotOpenCredits =>
      isArabic ? 'تعذر فتح gymvisual.com.' : 'Could not open gymvisual.com.';
  String get close => isArabic ? 'إغلاق' : 'Close';
  String get unsyncedWorkouts =>
      isArabic ? 'حصص غير متزامنة' : 'Unsynced workouts';
  String unsyncedDraftWarning(int count) => isArabic
      ? 'لديك ${arabicCountPhrase(count, ArabicCountNoun.workoutDraft, isolateCount: true)} غير متزامنة. ستبقى على هذا الجهاز حتى تتم مزامنتها؛ تسجيل الخروج لن يحذفها.'
      : 'You have $count unsynced workout ${count == 1 ? 'draft' : 'drafts'}. They stay on this device until they sync; logging out will not delete them.';
  String get discardDraftsAndLogOut =>
      isArabic ? 'حذف المسودات وتسجيل الخروج' : 'Discard drafts and log out';
  String get keepDraftsAndLogOut =>
      isArabic ? 'الاحتفاظ بالمسودات وتسجيل الخروج' : 'Keep drafts and log out';
  String get discardUnfinishedWorkout =>
      isArabic ? 'حذف الحصة غير المكتملة؟' : 'Discard unfinished workout?';
  String get logoutDiscardsBrowserWorkout => isArabic
      ? 'سيؤدي تسجيل الخروج إلى حذف هذه الحصة من هذا المتصفح.'
      : 'Logging out will discard this workout from this browser.';
  String get discardAndLogOut =>
      isArabic ? 'حذف وتسجيل الخروج' : 'Discard and log out';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';

  String _ltr(String value) => '\u2066$value\u2069';
}
