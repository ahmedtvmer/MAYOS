import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models.dart';
import '../../../router.dart';
import 'tour_targets.dart';

/// The shared Feature list used by the Tour and later discovery surfaces.
const int tourCurrentVersion = 1;
const int currentFeatureRelease = 6;
const int kReleaseShareCard = 3;
const int kReleasePrCelebration = 3;
const int kReleaseDurationCheck = 4;

bool isTourEligible(Account account, {int currentVersion = tourCurrentVersion}) =>
    account.tourSeenVersion < currentVersion &&
    (currentVersion == 1 || account.tourCreatedVersion >= currentVersion);

class FeatureEntry {
  const FeatureEntry({
    required this.id,
    required this.titleEn,
    required this.sentenceEn,
    required this.titleAr,
    required this.sentenceAr,
    required this.target,
    required this.location,
    required this.release,
    required this.audience,
    this.requiresProgramControl = false,
  });

  final String id;
  final String titleEn;
  final String sentenceEn;
  final String titleAr;
  final String sentenceAr;
  final String target;
  final TourTargetLocation location;
  final int release;
  final String audience;
  final bool requiresProgramControl;
}

List<String> validateFeatureEntries(
  List<FeatureEntry> entries, {
  required Set<String> validTargetIds,
}) {
  final List<String> errors = <String>[];
  final Set<String> seenIds = <String>{};
  for (final FeatureEntry entry in entries) {
    if (!seenIds.add(entry.id)) errors.add('${entry.id}: duplicate id');
    if (entry.titleEn.trim().isEmpty) errors.add('${entry.id}: titleEn is empty');
    if (entry.sentenceEn.trim().isEmpty) errors.add('${entry.id}: sentenceEn is empty');
    if (entry.titleAr.trim().isEmpty) errors.add('${entry.id}: titleAr is empty');
    if (entry.sentenceAr.trim().isEmpty) errors.add('${entry.id}: sentenceAr is empty');
    if (!validTargetIds.contains(entry.target)) {
      errors.add('${entry.id}: unknown target ${entry.target}');
    }
    if (entry.release < 0) errors.add('${entry.id}: release is negative');
    if (entry.audience != 'lifter') errors.add('${entry.id}: audience is not lifter');
  }
  return errors;
}

const List<FeatureEntry> featureList = <FeatureEntry>[
  FeatureEntry(
    id: 'home',
    titleEn: 'Home',
    sentenceEn: 'See your next workout and start training.',
    titleAr: 'الرئيسية',
    sentenceAr: 'اطّلع على تمرينك التالي وابدأ التدريب.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'program',
    titleEn: 'Program',
    sentenceEn: 'Edit a day, add exercises, or Replace a movement.',
    titleAr: 'البرنامج التدريبي',
    sentenceAr: 'عدّل يومًا، وأضف تمارين، أو استبدل حركة بخيار آخر.',
    target: 'program',
    location: TourShellTabLocation(tabIndex: 1),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant',
    titleEn: 'Assistant',
    sentenceEn: 'Ask about your training, changes to your program, or what you ate on a recent day.',
    titleAr: 'المساعد',
    sentenceAr: 'اسأل عن تدريبك أو تغييرات برنامجك التدريبي أو ما أكلته في يوم قريب.',
    target: 'assistant',
    location: TourShellTabLocation(tabIndex: 0),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'nutrition',
    titleEn: 'Nutrition',
    sentenceEn: 'Review your targets, log water, and track body weight.',
    titleAr: 'التغذية',
    sentenceAr: 'راجع أهدافك وسجّل الماء وتابع وزن جسمك.',
    target: 'nutrition',
    location: TourShellTabLocation(tabIndex: 2),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'food_log',
    titleEn: 'Food log',
    sentenceEn: 'Search foods, log grams or local portions, Quick add calories and Macros, create a Personal food, or copy a meal from yesterday; your Nutrition adherence is worked out after each day unless you answer yourself.',
    titleAr: 'سجل الطعام',
    sentenceAr: 'ابحث عن الأطعمة وسجّلها بالجرام أو بالحصة المحلية، أو استخدم الإضافة السريعة، أو أنشئ طعامًا خاصًا، أو انسخ وجبة من أمس، ويُحسب التزامك الغذائي بعد نهاية اليوم ما لم تُجب بنفسك.',
    target: 'food_log',
    location: TourShellTabLocation(tabIndex: 2),
    release: 5,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'meal_setup',
    titleEn: 'Meal setup and Food restrictions',
    sentenceEn: 'Choose Meal slots, training time and Food restrictions, generate meals from reviewed Staple foods with target differences, swap foods in your own plan or follow meals and notes set by your coach, and log a planned meal with one tap.',
    titleAr: 'إعداد الوجبات والقيود الغذائية',
    sentenceAr: 'اختر وجباتك ووقت تدريبك وقيودك الغذائية، وأنشئ وجبات من أطعمة أساسية معتمدة مع توضيح الفرق عن الأهداف وبدّل الأطعمة في خطتك أو اتبع وجبات وملاحظات حددها مدربك، وسجّل الوجبة المخططة بلمسة واحدة.',
    target: 'meal_setup',
    location: TourShellTabLocation(tabIndex: 2),
    release: 6,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'food_swap_requests',
    titleEn: 'Food swap requests',
    sentenceEn: 'Ask your coach to swap a food in your Nutrition plan, and open your request history from Nutrition to see each status and reply.',
    titleAr: 'طلبات تبديل الطعام',
    sentenceAr: 'اطلب من مدربك تبديل طعام في خطة التغذية، وافتح سجل طلباتك من التغذية لمتابعة حالة كل طلب ورد المدرب.',
    target: 'food_swap_requests',
    location: TourShellTabLocation(tabIndex: 2),
    release: 6,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant_meals',
    titleEn: 'Ask about planned meals',
    sentenceEn: 'Ask the assistant to explain your planned meals or suggest which food to swap, then use the swap action in Nutrition or send your coach a Food swap request.',
    titleAr: 'اسأل عن وجباتك المخططة',
    sentenceAr: 'اطلب من المساعد شرح وجباتك المخططة أو اقتراح طعام لتبديله، ثم استخدم إجراء تبديل الطعام في التغذية أو أرسل طلب تبديل إلى مدربك.',
    target: 'assistant',
    location: TourShellTabLocation(tabIndex: 0),
    release: 6,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'progress',
    titleEn: 'Progress',
    sentenceEn: 'Explore your charts and review Checkpoint feedback.',
    titleAr: 'التقدم',
    sentenceAr: 'تابع مخططاتك وراجع ملاحظات محطات التقدم.',
    target: 'progress',
    location: TourShellTabLocation(tabIndex: 3),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'profile',
    titleEn: 'Profile',
    sentenceEn: 'Review Weak points, Movements to avoid, and equipment in Profile; '
        'change language in Settings.',
    titleAr: 'الملف الشخصي',
    sentenceAr: 'راجع نقاط الضعف والحركات التي يجب تجنبها والمعدات في الملف الشخصي، '
        'وغيّر اللغة من الإعدادات.',
    target: 'profile',
    location: TourRouteLocation(profilePath),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'feature_guide',
    titleEn: 'Feature guide',
    sentenceEn: 'Find the Feature guide and replay this Tour from Profile.',
    titleAr: 'دليل الميزات',
    sentenceAr: 'افتح دليل الميزات أو أعد الجولة من الملف الشخصي.',
    target: 'feature_guide',
    location: TourRouteLocation(profilePath),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'brand-mayos',
    titleEn: 'MYOS is now MAYOS',
    sentenceEn: "Same app, same training — we're now called MAYOS.",
    titleAr: 'MYOS أصبح MAYOS',
    sentenceAr: 'نفس التطبيق ونفس التدريب، أصبح اسمنا الآن MAYOS.',
    target: 'brand_mayos',
    location: TourShellTabLocation(tabIndex: 0),
    release: 2,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'duration_check',
    titleEn: 'Workout duration check',
    sentenceEn: 'Confirm an unusually short or long workout before saving.',
    titleAr: 'تأكيد مدة الحصة',
    sentenceAr: 'أكّد مدة الحصة إذا كانت قصيرة أو طويلة بشكل غير معتاد قبل حفظها.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: kReleaseDurationCheck,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'workout_share_card',
    titleEn: 'Share workout card',
    sentenceEn: 'Preview your dated workout card, then share or save it.',
    titleAr: 'مشاركة بطاقة الحصة',
    sentenceAr: 'عاين بطاقة تمرينك بتاريخها، ثم شاركها أو احفظها.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: kReleaseShareCard,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'pr_celebration',
    titleEn: 'Personal record celebration',
    sentenceEn: 'See your personal record celebration after you finish a workout.',
    titleAr: 'الاحتفال برقم قياسي شخصي',
    sentenceAr: 'شاهد احتفالك برقم قياسي شخصي بعد إنهاء الحصة.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: kReleasePrCelebration,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'weak_points',
    titleEn: 'Weak points',
    sentenceEn: 'Choose muscles you want your Training program to focus on.',
    titleAr: 'نقاط الضعف',
    sentenceAr: 'اختر العضلات التي تريد أن يركز عليها برنامجك التدريبي.',
    target: 'whats_new_weak_points',
    location: TourRouteLocation(profilePath),
    release: 1,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant_why',
    titleEn: 'Ask the assistant why',
    sentenceEn: 'Ask why an exercise or training decision is in your program.',
    titleAr: 'اسأل المساعد عن السبب',
    sentenceAr: 'اسأل عن سبب وجود تمرين أو قرار تدريبي في برنامجك.',
    target: 'whats_new_assistant_why',
    location: TourRouteLocation(chatPath),
    release: 1,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'add_exercises',
    titleEn: 'Add exercises in the Program tab',
    sentenceEn: 'Add exercises to a training day from the Program tab.',
    titleAr: 'أضف تمارين من تبويب البرنامج',
    sentenceAr: 'أضف تمارين إلى يوم تدريبي من تبويب البرنامج.',
    target: 'whats_new_add_exercises',
    location: TourShellTabLocation(tabIndex: 1),
    release: 1,
    audience: 'lifter',
    requiresProgramControl: true,
  ),
  FeatureEntry(
    id: 'edit_program_chat',
    titleEn: 'Edit your program from chat',
    sentenceEn: 'Tell the assistant how you want to change your Training program.',
    titleAr: 'عدّل برنامجك عبر المحادثة',
    sentenceAr: 'أخبر المساعد بالتغييرات التي تريدها في برنامجك التدريبي.',
    target: 'whats_new_edit_program_chat',
    location: TourRouteLocation(chatPath),
    release: 1,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'movements_to_avoid',
    titleEn: 'Movements to avoid',
    sentenceEn: 'Choose movements your Training program should avoid.',
    titleAr: 'حركات يجب تجنبها',
    sentenceAr: 'اختر الحركات التي يجب أن يتجنبها برنامجك التدريبي.',
    target: 'whats_new_movements_to_avoid',
    location: TourRouteLocation(profilePath),
    release: 1,
    audience: 'lifter',
  ),
];

final Provider<List<FeatureEntry>> featureEntriesProvider =
    Provider<List<FeatureEntry>>((ref) => featureList);

class ProgramFeatureAvailability {
  const ProgramFeatureAvailability({this.accountId, this.playerControlsProgram});

  final String? accountId;
  final bool? playerControlsProgram;
}

final StateProvider<ProgramFeatureAvailability> programFeatureAvailabilityProvider =
    StateProvider<ProgramFeatureAvailability>(
        (ref) => const ProgramFeatureAvailability());

bool isFeatureAvailableForAccount(
  FeatureEntry entry,
  String? accountId,
  ProgramFeatureAvailability availability,
) =>
    !entry.requiresProgramControl ||
    (availability.accountId == accountId &&
        availability.playerControlsProgram == true);

const List<String> tourV1StopIds = <String>[
  'home',
  'program',
  'assistant',
  'nutrition',
  'progress',
  'profile',
  'feature_guide',
];
const int tourV1StopCount = 7;
