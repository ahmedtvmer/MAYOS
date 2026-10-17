/// Shared user-facing copy for the daily assistant allowance.
///
/// Both the plan catalog and structured API errors use this class so their
/// allowance messages and UTC reset labels stay consistent.
class AiAllowanceCopy {
  const AiAllowanceCopy(this.languageCode);

  final String languageCode;
  bool get isArabic => languageCode == 'ar';

  String lifterDailyAllowance(int? requestLimit) => requestLimit == null
      ? (isArabic
          ? 'خلال الفترة التجريبية، يخضع استخدام المساعد لحد موارد يومي مشترك.'
          : 'During the trial, assistant use follows a shared daily resource limit.')
      : (isArabic
          ? 'حتى ${_ltr('$requestLimit')} إجابة مكتملة من المساعد يوميًا بتوقيت UTC.'
          : 'Up to $requestLimit complete assistant answers each UTC day.');

  String get resourceSafeguardDisclosure => isArabic
      ? 'قد يمنع حد يومي مستقل للموارد استخدام المساعد مع بقاء طلبات متاحة. قد تستهلك المحادثات الأطول والردود بالعربية موارد أكثر.'
      : 'A separate daily resource limit may stop assistant use while requests remain. Longer conversations and Arabic replies may use more resources.';

  String allowanceSummary(int remaining, String resetAt) => isArabic
      ? 'المتبقي من طلبات المساعد اليوم: ${_ltr('$remaining')}. يُعاد الضبط في ${_ltr(_resetAtLabel(resetAt))}.'
      : '$remaining assistant '
          '${remaining == 1 ? 'request remains' : 'requests remain'} today. '
          'Resets at ${_resetAtLabel(resetAt)}.';

  String requestsExhausted(String resetAt) => isArabic
      ? 'استنفدت طلبات المساعد لهذا اليوم. يُعاد الضبط في ${_ltr(_resetAtLabel(resetAt))}.'
      : 'You have used today’s assistant requests. Resets at ${_resetAtLabel(resetAt)}.';

  String resourceWarning(int remaining, String resetAt) => isArabic
      ? 'موارد المساعد تقترب من الحد اليومي. المتبقي من الطلبات: ${_ltr('$remaining')}. يُعاد الضبط في ${_ltr(_resetAtLabel(resetAt))}.'
      : 'Assistant resources are nearing today’s limit. $remaining '
          '${remaining == 1 ? 'request remains' : 'requests remain'}. '
          'Resets at ${_resetAtLabel(resetAt)}.';

  String resourceCutoff(int remaining, String resetAt) => isArabic
      ? 'وصلت إلى حد موارد المساعد اليومي. المتبقي من الطلبات: ${_ltr('$remaining')}. يُعاد الضبط في ${_ltr(_resetAtLabel(resetAt))}.'
      : 'You have reached today’s assistant resource limit. $remaining '
          '${remaining == 1 ? 'request remains' : 'requests remain'}. '
          'Resets at ${_resetAtLabel(resetAt)}.';

  String resourceCutoffError(int remaining, String resetAt) =>
      resourceCutoff(remaining, resetAt);

  String requestInProgress(int remaining, String resetAt) => isArabic
      ? 'طلبات المساعد المتبقية قيد التنفيذ الآن. المتبقي: ${_ltr('$remaining')}. يُعاد الضبط في ${_ltr(_resetAtLabel(resetAt))}.'
      : 'Your remaining daily assistant requests are in progress. $remaining remain. Resets at ${_resetAtLabel(resetAt)}.';

  String get answerTruncated => isArabic
      ? 'توقف الرد قبل اكتماله. حاول مرة أخرى.'
      : 'The answer was cut off before it finished. Please retry.';

  String _ltr(String value) => '\u2066$value\u2069';

  String _resetAtLabel(String value) {
    final DateTime? parsed = DateTime.tryParse(value);
    if (parsed == null) {
      return isArabic ? 'موعد إعادة الضبط' : 'the next UTC reset';
    }
    final DateTime reset = parsed.toUtc();
    return '${reset.year.toString().padLeft(4, '0')}-'
        '${reset.month.toString().padLeft(2, '0')}-'
        '${reset.day.toString().padLeft(2, '0')} 00:00 UTC';
  }
}
