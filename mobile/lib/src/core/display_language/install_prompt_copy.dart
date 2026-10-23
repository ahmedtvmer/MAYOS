class InstallPromptCopy {
  const InstallPromptCopy(this.languageCode);

  final String languageCode;
  bool get _ar => languageCode.toLowerCase().startsWith('ar');

  String get button => _ar ? 'تثبيت MYOS' : 'Install MYOS';
  String get hint => _ar
      ? 'تثبيت MYOS: اضغط على مشاركة، ثم إضافة إلى الشاشة الرئيسية.'
      : 'Install MYOS: tap Share, then Add to Home Screen.';
  String get dismiss => _ar ? 'إغلاق' : 'Dismiss';
}
