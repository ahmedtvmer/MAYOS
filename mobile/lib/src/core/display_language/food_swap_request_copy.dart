class FoodSwapRequestCopy {
  const FoodSwapRequestCopy(this.language);
  final String language;
  bool get arabic => language == 'ar';
  String get title => arabic ? 'طلبات تبديل الطعام' : 'Food swap requests';
  String get request => arabic ? 'اطلب تبديل هذا الطعام' : 'Request a Food swap';
  String get reason => arabic ? 'السبب (اختياري)' : 'Reason (optional)';
  String get send => arabic ? 'إرسال الطلب' : 'Send request';
  String get cancel => arabic ? 'إلغاء' : 'Cancel';
  String get reply => arabic ? 'رد المدرب' : 'Coach reply';
  String get replyHint => arabic ? 'الرد مطلوب عند الرفض، واختياري عند التطبيق.'
      : 'Required when declining; optional when applying.';
  String get replacement => arabic ? 'الطعام البديل' : 'Replacement food';
  String get grams => arabic ? 'الجرامات' : 'Grams';
  String get search => arabic ? 'ابحث عن طعام' : 'Search foods';
  String get apply => arabic ? 'تطبيق التبديل' : 'Apply Food swap';
  String get decline => arabic ? 'رفض مع الرد' : 'Decline with reply';
  String get retry => arabic ? 'إعادة المحاولة' : 'Retry';
  String get refresh => arabic ? 'تحديث الطلبات' : 'Refresh requests';
  String get empty => arabic ? 'لا توجد طلبات تبديل طعام بعد.' : 'No Food swap requests yet.';
  String get sent => arabic ? 'أُرسل طلبك إلى مدربك.' : 'Your request was sent to your coach.';
  String get invalid => arabic ? 'اختر طعامًا مختلفًا وحدد الجرامات. أضف ردًا عند الرفض.'
      : 'Choose a different food and enter grams. Add a reply when declining.';
  String get closeNote => arabic ? 'أُغلق الطلب لانتهاء علاقة التدريب.' : 'Closed because the Assignment ended.';
  String status(String status) => switch (status) {
    'pending' => arabic ? 'قيد الانتظار' : 'Pending',
    'applied' => arabic ? 'تم التطبيق' : 'Applied',
    'declined' => arabic ? 'مرفوض' : 'Declined',
    'closed' => arabic ? 'مغلق' : 'Closed',
    _ => status,
  };
  String target(Map<String, dynamic> target) {
    final String food = '${arabic ? target['food_name_ar'] ?? target['food_name'] : target['food_name']}';
    return '${arabic ? 'تبديل' : 'Swap'} $food · ${target['meal_name']}';
  }
}
