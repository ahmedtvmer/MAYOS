class InstallPromptCopy {
  const InstallPromptCopy(this.languageCode);

  final String languageCode;
  bool get _ar => languageCode.toLowerCase().startsWith('ar');

  String get title => _ar ? 'تثبيت MYOS' : 'Install MYOS';
  String get benefit => _ar
      ? 'افتح MYOS من شاشتك الرئيسية كتطبيق — دون الحاجة إلى متجر تطبيقات.'
      : 'Open MYOS from your home screen like an app — no app store needed.';
  String get install => _ar ? 'تثبيت' : 'Install';
  String get gotIt => _ar ? 'حسنًا' : 'Got it';
  String get notNow => _ar ? 'ليس الآن' : 'Not now';
  String get shareStep => _ar ? '١  اضغط على مشاركة' : '1  Tap Share';
  String get addStep => _ar ? '٢  اختر إضافة إلى الشاشة الرئيسية' : '2  Add to Home Screen';
  String get dismiss => _ar ? 'إغلاق' : 'Dismiss';
}
