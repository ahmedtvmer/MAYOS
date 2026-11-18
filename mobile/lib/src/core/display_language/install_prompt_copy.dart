class InstallPromptCopy {
  const InstallPromptCopy(this.languageCode);

  final String languageCode;
  bool get _ar => languageCode.toLowerCase().startsWith('ar');

  String get title => _ar ? 'تثبيت MAYOS' : 'Install MAYOS';
  String get benefit => _ar
      ? 'افتح MAYOS من شاشتك الرئيسية كتطبيق — دون الحاجة إلى متجر تطبيقات.'
      : 'Open MAYOS from your home screen like an app — no app store needed.';
  String get install => _ar ? 'تثبيت' : 'Install';
  String get gotIt => _ar ? 'حسنًا' : 'Got it';
  String get notNow => _ar ? 'ليس الآن' : 'Not now';
  String get shareStep => _ar ? '١  اضغط على مشاركة' : '1  Tap Share';
  String get addStep => _ar
      ? '٢  اختر إضافة إلى الشاشة الرئيسية. تتطلب الإشعارات فتح التطبيق منها على iOS 16.4 أو أحدث.'
      : '2  Add to Home Screen. For notifications, open the app there on iOS 16.4 or later.';
  String get dismiss => _ar ? 'إغلاق' : 'Dismiss';
}
