/// App-owned labels and confirmation copy for the player's profile editor.
class ProfileCopy {
  const ProfileCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get signInMethods => isArabic ? 'طرق تسجيل الدخول' : 'Sign-in methods';
  String get trainingProfile =>
      isArabic ? 'الملف التدريبي' : 'Training profile';
  String get profileLead => isArabic
      ? 'حدّث معلومات الملف التي تساعد على تخصيص تدريبك.'
      : 'Update the profile facts used to personalize your training.';
  String get currentGoal => isArabic ? 'الهدف الحالي' : 'Current goal';
  String get injuriesLimitations =>
      isArabic ? 'الإصابات أو القيود' : 'Injuries or limitations';
  String get weightKg => isArabic ? 'الوزن (\u2066kg\u2069)' : 'Weight (kg)';
  String get targetWeightKg => isArabic
      ? 'الوزن المستهدف (\u2066kg\u2069، اختياري)'
      : 'Target weight (kg, optional)';
  String get logWeight => isArabic ? 'تسجيل الوزن' : 'Log weight';
  String get trainingDaysPerWeek =>
      isArabic ? 'أيام التدريب في الأسبوع' : 'Training days per week';
  String get repPreference => isArabic ? 'تفضيل التكرارات' : 'Rep preference';
  String get equipmentAccess =>
      isArabic ? 'المعدات المتاحة' : 'Equipment access';
  String get saveProfile => isArabic ? 'حفظ الملف' : 'Save profile';
  String get trainingSchedule =>
      isArabic ? 'جدول التدريب' : 'Training schedule';
  String get scheduleLead => isArabic
      ? 'أيام التدريب المتوقعة والمنطقة الزمنية، بشكل منفصل عن برنامجك.'
      : 'Expected weekdays and timezone, separate from your program.';
  String get timezone => isArabic ? 'المنطقة الزمنية' : 'Timezone';
  String get saveSchedule => isArabic ? 'حفظ الجدول' : 'Save schedule';
  String get trainingPause =>
      isArabic ? 'إيقاف التدريب مؤقتًا' : 'Training pause';
  String pauseStart(String date) =>
      isArabic ? 'البداية: ${_ltr(date)}' : 'Start: $date';
  String pauseEnd(String date) =>
      isArabic ? 'النهاية: ${_ltr(date)}' : 'End: $date';
  String get schedulePause => isArabic ? 'جدولة التوقف' : 'Schedule pause';
  String get noScheduledPauses =>
      isArabic ? 'لا توجد فترات توقف مجدولة.' : 'No scheduled pauses.';
  String pauseRange(String start, String end) =>
      isArabic ? 'توقف: ${_ltr(start)} → ${_ltr(end)}' : 'Pause: $start → $end';
  String get dangerZone => isArabic ? 'منطقة الخطر' : 'Danger zone';
  String get dangerZoneLead => isArabic
      ? 'حذف الحساب يزيله نهائيًا ويمسح بياناته، بما فيها المسودات غير المتزامنة على هذا الجهاز. لا يمكن التراجع عن ذلك.'
      : 'Deleting your account permanently removes it and its active data, including unsynced drafts on this device. It cannot be undone.';
  String get deleteAccount => isArabic ? 'حذف الحساب' : 'Delete account';
  String get confirmProgramRebuild =>
      isArabic ? 'تأكيد إعادة إنشاء البرنامج' : 'Confirm program rebuild';
  String get rebuildsProgram => isArabic
      ? 'سيُعاد إنشاء برنامجك التدريبي.'
      : 'This rebuilds your program';
  String get continueAction => isArabic ? 'متابعة' : 'Continue';
  String get programRebuilt =>
      isArabic ? 'أُعيد إنشاء البرنامج التدريبي.' : 'Program rebuilt.';
  String get profileSaved => isArabic ? 'حُفظ الملف.' : 'Profile saved.';
  String get scheduleSaved =>
      isArabic ? 'حُفظ جدول التدريب.' : 'Training schedule saved.';
  String get pauseScheduled =>
      isArabic ? 'تمت جدولة التوقف.' : 'Pause scheduled.';
  String get pauseScheduledCoachNotified => isArabic
      ? 'تمت جدولة التوقف وإبلاغ مدربك.'
      : 'Pause scheduled; your coach was notified.';
  String get checkProfileAndRetry => isArabic
      ? 'تحقق من معلومات ملفك وحاول مجددًا.'
      : 'Check your profile details and try again.';
  String weightRange(String min, String max) => isArabic
      ? 'يجب أن يكون الوزن بين ${_ltr('$min kg')} و${_ltr('$max kg')}.'
      : 'Weight must be between $min and $max kg.';
  String chooseAllowed(String field) => isArabic
      ? 'اختر قيمة مسموحًا بها لـ$field.'
      : 'Choose an allowed $field.';
  String checkFieldAndRetry(String field) => isArabic
      ? 'تحقق من $field وحاول مجددًا.'
      : 'Check your $field and try again.';
  String get timezoneExample => isArabic
      ? 'أدخل منطقة زمنية بصيغة IANA، مثل Europe/London أو UTC.'
      : 'Enter an IANA timezone, e.g. Europe/London or UTC.';
  String get pauseMustStartToday => isArabic
      ? 'يجب أن يبدأ التوقف اليوم أو بعده.'
      : 'A pause must start today or later.';
  String get pauseMustEndAfterStart => isArabic
      ? 'يجب أن ينتهي التوقف في يوم بدايته أو بعده.'
      : 'A pause must end on or after it starts.';
  String pauseMaximumDays(int days) => isArabic
      ? 'يمكن أن يستمر التوقف $days يومًا كحد أقصى.'
      : 'A pause can last at most $days days.';
  String get confirmDeleteAccount =>
      isArabic ? 'حذف الحساب؟' : 'Delete account?';
  String get deleteAccountDetails => isArabic
      ? 'سيؤدي ذلك إلى حذف حسابك وبياناته النشطة نهائيًا: سجل التدريب، والبرنامج التدريبي، وعلاقة التدريب، والبريد الإلكتروني للاسترداد، وأي مسودات غير متزامنة على هذا الجهاز. لا يمكن التراجع عن ذلك.'
      : 'This permanently deletes your account and its active data: training history, program, coaching assignment, recovery email, and any unsynced drafts on this device. This cannot be undone.';
  String get googleOnlyDeleteProof => isArabic
      ? 'لا توجد كلمة مرور لهذا الحساب، لذا أكّد الحذف بتسجيل الدخول إلى Google. سيُطلب منك إثبات ملكية حساب Google المرتبط بحساب MAYOS هذا.'
      : 'There is no password on this account, so confirm by signing in with Google: you will be asked to prove the Google account connected to this MAYOS account.';
  String get password => isArabic ? 'كلمة المرور' : 'Password';
  String get cancel => isArabic ? 'إلغاء' : 'Cancel';
  String get currentPassword =>
      isArabic ? 'كلمة المرور الحالية' : 'Current password';
  String get newPassword => isArabic ? 'كلمة المرور الجديدة' : 'New password';
  String get confirmNewPassword =>
      isArabic ? 'تأكيد كلمة المرور الجديدة' : 'Confirm new password';
  String get enterCurrentPassword =>
      isArabic ? 'أدخل كلمة المرور الحالية.' : 'Enter your current password.';
  String get setPassword => isArabic ? 'تعيين كلمة مرور' : 'Set a password';
  String get choosePasswordForGoogle => isArabic
      ? 'اختر كلمة مرور لتسجيل الدخول دون Google. بعد تعيينها يمكنك فصل Google.'
      : 'Choose a password so you can sign in without Google. Once it is set you can disconnect Google.';
  String get setPasswordAction =>
      isArabic ? 'تعيين كلمة المرور' : 'Set password';
  String get passwordSetDisconnectGoogle => isArabic
      ? 'تم تعيين كلمة المرور. يمكنك الآن فصل Google.'
      : 'Password set. You can now disconnect Google.';
  String get changePassword =>
      isArabic ? 'تغيير كلمة المرور' : 'Change password';
  String get changePasswordSignsOut => isArabic
      ? 'سيؤدي تغيير كلمة المرور إلى تسجيل خروجك من كل الأجهزة.'
      : 'Changing your password signs you out of every device.';
  String get changePasswordAction =>
      isArabic ? 'تغيير كلمة المرور' : 'Change password';
  String get disconnectGoogleQuestion =>
      isArabic ? 'فصل Google؟' : 'Disconnect Google?';
  String get disconnectGoogleLead => isArabic
      ? 'لن تتمكن بعد ذلك من تسجيل الدخول إلى Google. ستبقى كلمة المرور طريقة أخرى لتسجيل الدخول.'
      : 'You will no longer be able to sign in with Google. Your password stays as the other way to sign in.';
  String get disconnect => isArabic ? 'فصل' : 'Disconnect';
  String get googleConnected =>
      isArabic ? 'تم ربط حساب Google.' : 'Google account connected.';
  String get googleDisconnected =>
      isArabic ? 'تم فصل Google.' : 'Google disconnected.';
  String get passwordTitle => isArabic ? 'كلمة المرور' : 'Password';
  String get passwordSet => isArabic ? 'تم تعيين كلمة المرور' : 'Password set';
  String get noPasswordYet =>
      isArabic ? 'لم تُعيّن كلمة مرور بعد' : 'No password yet';
  String get google => 'Google';
  String get connected => isArabic ? 'متصل' : 'Connected';
  String get notConnected => isArabic ? 'غير متصل' : 'Not connected';
  String get setPasswordFirst =>
      isArabic ? 'عيّن كلمة مرور أولًا' : 'Set a password first';
  String get disconnectGoogle => isArabic ? 'فصل Google' : 'Disconnect Google';
  String get connectGoogle => isArabic ? 'الاتصال بـ Google' : 'Connect Google';
  String get retry => isArabic ? 'إعادة المحاولة' : 'Retry';
  String get none => isArabic ? 'لا شيء' : 'None';
  String weekday(int day) {
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
    return (isArabic ? arabic : english)[day - 1];
  }

  String profileFieldName(String field, String englishFallback) =>
      switch (field) {
        'current_goal' => isArabic ? 'الهدف الحالي' : englishFallback,
        'injuries_or_limitations' =>
          isArabic ? 'الإصابات أو القيود' : englishFallback,
        'weight_kg' => isArabic ? 'الوزن' : englishFallback,
        'weekly_frequency' =>
          isArabic ? 'عدد أيام التدريب أسبوعيًا' : englishFallback,
        'equipment_access' => isArabic ? 'المعدات' : englishFallback,
        'rep_preference' => isArabic ? 'تفضيل التكرارات' : englishFallback,
        _ => englishFallback,
      };
  String equipmentValue(String value) => switch (value) {
        'Commercial gym' => isArabic ? 'صالة رياضية تجارية' : value,
        'Home gym' => isArabic ? 'معدات منزلية' : value,
        'Bodyweight only' => isArabic ? 'وزن الجسم فقط' : value,
        _ => value,
      };

  String repPreferenceValue(String value) => switch (value) {
        'balanced' => isArabic ? 'متوازن' : 'Balanced',
        'low' => isArabic ? 'منخفض' : 'Low',
        'high' => isArabic ? 'مرتفع' : 'High',
        _ => value,
      };

  String _ltr(String value) => '\u2066$value\u2069';
}
