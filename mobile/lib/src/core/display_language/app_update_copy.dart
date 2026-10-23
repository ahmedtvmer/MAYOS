class AppUpdateCopy {
  const AppUpdateCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String get newVersionAvailable =>
      isArabic ? 'يتوفر إصدار جديد' : 'New version available';
  String get refresh => isArabic ? 'تحديث' : 'Refresh';
  String get dismissUpdate =>
      isArabic ? 'إغلاق إشعار التحديث' : 'Dismiss update notice';
}
