import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models.dart';
import '../../../router.dart';
import 'tour_targets.dart';

/// The shared Feature list used by the Tour and later discovery surfaces.
const int tourCurrentVersion = 1;
const int currentFeatureRelease = 9;
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
    id: 'reverse_curl_forearms',
    titleEn: 'Reverse curls for forearms',
    sentenceEn: 'New programs start forearm work with a reverse curl, and reverse curls now count as forearm work, not biceps.',
    titleAr: 'الكيرل العكسي للساعدين',
    sentenceAr: 'البرامج الجديدة تبدأ تمارين الساعدين بالكيرل العكسي، ويُحسب الكيرل العكسي الآن تمرينًا للساعدين وليس للعضلة ذات الرأسين.',
    target: 'program',
    location: TourShellTabLocation(tabIndex: 1),
    release: 9,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'xp_ranks',
    titleEn: 'XP, ranks and your weekly streak',
    sentenceEn: 'Earn XP for training the way your plan says, climb from Rookie to Legend, and keep a weekly streak with one workout a week.',
    titleAr: 'XP والرتب وسلسلتك الأسبوعية',
    sentenceAr: 'اكسب XP عندما تتدرب كما تقول خطتك، وارتقِ من مبتدئ إلى أسطورة، وحافظ على سلسلتك الأسبوعية بتمرين واحد في الأسبوع.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: 8,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'simpler_home',
    titleEn: 'A simpler Home',
    sentenceEn: "Home now opens on today's session, with your last workout to share and short Nutrition, Program, weekly sets and PR summaries below.",
    titleAr: 'رئيسية أبسط',
    sentenceAr: 'تبدأ الرئيسية الآن بحصة اليوم، مع آخر تمرين لمشاركته، وملخصات قصيرة للتغذية والبرنامج ومجموعات الأسبوع والأرقام القياسية.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: 8,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'ai_assistant_tab',
    titleEn: 'AI Assistant in the bottom bar',
    sentenceEn: 'Open the AI Assistant from the middle of the bottom bar; Checkpoint reviews now wait in Progress, marked with a dot.',
    titleAr: 'المساعد الذكي في الشريط السفلي',
    sentenceAr: 'افتح المساعد الذكي من منتصف الشريط السفلي؛ ومراجعات محطات التقدم تنتظرك الآن في التقدم مع نقطة تنبيه.',
    target: 'assistant',
    location: TourShellTabLocation(tabIndex: 0),
    release: 8,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'web_push',
    titleEn: 'Encouragement when it suits you',
    sentenceEn: 'Turn on training reminders, alerts and coach updates in the installed web app, with quiet hours you choose.',
    titleAr: 'تشجيع في الوقت المناسب لك',
    sentenceAr: 'شغّل تذكيرات التدريب والتنبيهات وتحديثات المدرب في تطبيق الويب المثبّت، مع ساعات هدوء تختارها.',
    target: 'push_notifications',
    location: TourRouteLocation(settingsPath),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'cable_y_raise_demo',
    titleEn: 'Cable Y-Raise demo',
    sentenceEn: 'See a still image and animated demo of the Cable Y-Raise.',
    titleAr: 'عرض Cable Y-Raise',
    sentenceAr: 'شاهد صورة ثابتة وصورة متحركة توضّحان تمرين Cable Y-Raise.',
    target: 'exercise_demo_media',
    location: TourRouteLocation('$exerciseDetailPath/mayos:3'),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'isolation_first_order',
    titleEn: 'A clearer exercise order',
    sentenceEn:
        'When a day allows, up to two isolation sets may come before a later compound for the same muscle; the main lift stays first in the day.',
    titleAr: 'ترتيب أوضح للتمارين',
    sentenceAr:
        'عندما يسمح اليوم، قد تسبق مجموعتا عزل على الأكثر تمرينًا مركبًا لاحقًا للعضلة نفسها؛ ويظل تمرين القوة الأساسي أولًا في اليوم.',
    target: 'program',
    location: TourShellTabLocation(tabIndex: 1),
    release: 7,
    audience: 'lifter',
    requiresProgramControl: true,
  ),
  FeatureEntry(
    id: 'assistant_feedback',
    titleEn: 'Rate assistant replies',
    sentenceEn:
        'Tap 👍 or 👎 under an assistant reply, add what went wrong from the '
        'menu, or report a reply so the team reviews it; your vote or report '
        'is private and hides a reported reply until you show it again.',
    titleAr: 'قيّم إجابات المساعد',
    sentenceAr:
        'اضغط 👍 أو 👎 تحت إجابة المساعد، وبيّن الخطأ من القائمة، أو أبلغ عن '
        'إجابة ليراجعها الفريق؛ تقييمك وإبلاغك خاصان، وتُخفى الإجابة المُبلّغ '
        'عنها حتى تعرضها مجددًا.',
    target: 'assistant_feedback_vote_buttons',
    location: TourRouteLocation(chatPath),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant_exercise_lookup',
    titleEn: 'Search exercises by the name you know',
    sentenceEn:
        'Search by nicknames, singular or plural forms, and common spelling variations; choose from close matches when a name could mean more than one exercise.',
    titleAr: 'ابحث عن التمرين بالاسم الذي تعرفه',
    sentenceAr:
        'ابحث بالأسماء البديلة والمفرد والجمع واختلافات الكتابة الشائعة، واختر من الخيارات الأقرب عندما يحتمل الاسم أكثر من تمرين.',
    target: 'whats_new_assistant_why',
    location: TourRouteLocation(chatPath),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'offline_start',
    titleEn: 'Open your saved training offline',
    sentenceEn:
        'After opening the installed app online once, reopen it without a '
        'connection to view saved Home, Program, workout targets and Nutrition '
        'data. During startup, a localized banner distinguishes a connection '
        'problem from a MAYOS service problem.',
    titleAr: 'افتح بيانات تدريبك المحفوظة دون اتصال',
    sentenceAr:
        'بعد فتح التطبيق المثبّت عبر الإنترنت مرة واحدة، أعد فتحه دون اتصال '
        'للاطّلاع على بيانات الرئيسية والبرنامج التدريبي وأهداف التمرين والتغذية '
        'المحفوظة. توضّح رسالة منفصلة أثناء البدء ما إذا كانت هناك مشكلة '
        'في الاتصال أو مشكلة في MAYOS.',
    target: 'home',
    location: TourShellTabLocation(tabIndex: 0),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant_volume',
    titleEn: 'Ask about training volume',
    sentenceEn:
        'Ask about weekly sets for lats, traps and other main muscle groups '
        'using each exercise’s credits, logged volume, and clearly labelled '
        'estimates with their basis.',
    titleAr: 'اسأل عن مجموعات التدريب',
    sentenceAr:
        'اسأل عن مجموعات اللاتس (الظهر العريض) والترابيس والمجموعات العضلية '
        'الرئيسية الأخرى، مع رصيد كل تمرين والحجم المسجل والتقديرات المعلّمة '
        'مع أساس حسابها.',
    target: 'whats_new_assistant_why',
    location: TourRouteLocation(chatPath),
    release: 6,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'set_effort',
    titleEn: 'Ease into each exercise',
    sentenceEn: 'New generated programs start each exercise with more reps in reserve when it has multiple sets; follow the RIR on each row.',
    titleAr: 'ابدأ كل تمرين بجهد أخف',
    sentenceAr: 'تبدأ البرامج التدريبية الجديدة كل تمرين بتكرارات أكثر في الاحتياط عند وجود عدة مجموعات؛ اتبع RIR في كل صف.',
    target: 'program',
    location: TourShellTabLocation(tabIndex: 1),
    release: 6,
    audience: 'lifter',
    requiresProgramControl: true,
  ),
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
    sentenceEn: 'Ask about your Program days, Exercises and working sets, program changes or recent food; profile answers use only the facts your question needs.',
    titleAr: 'المساعد',
    sentenceAr: 'اسأل عن أيام برنامجك التدريبي وتمارينه ومجموعاته، أو تغييرات برنامجك، أو طعامك مؤخرًا؛ وتستخدم إجابات الملف الشخصي البيانات المطلوبة لسؤالك فقط.',
    target: 'assistant',
    location: TourShellTabLocation(tabIndex: 0),
    release: 0,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'nutrition',
    titleEn: 'Nutrition',
    sentenceEn:
        'Review each day’s calories, meals and Food log, log water and Nutrition adherence together, and open Targets beside the date for your goals and weight.',
    titleAr: 'التغذية',
    sentenceAr:
        'راجع سعرات كل يوم ووجباته وسجل الطعام، وسجّل الماء والالتزام الغذائي معًا، وافتح الأهداف بجانب التاريخ لمراجعة أهدافك ووزنك.',
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
    sentenceEn:
        'Meals are on by default and shown in a day table with calories, protein, carbs and fat; choose Meal slots and training time, use Log beside meal names and Swap beside food names or request a Coach swap, and keep today’s meals in Food log history as soon as Meal setup is saved.',
    titleAr: 'إعداد الوجبات والقيود الغذائية',
    sentenceAr:
        'تُفعَّل الوجبات افتراضيًا وتظهر في جدول اليوم مع السعرات والبروتين والكربوهيدرات والدهون؛ حدّد عدد الوجبات ووقت التدريب، واستخدم التسجيل بجوار اسم الوجبة والتبديل بجوار اسم الطعام أو اطلب من مدربك التبديل، وتُحفظ وجبات اليوم في سجل الطعام بمجرد حفظ إعداد الوجبات.',
    target: 'meal_setup',
    location: TourShellTabLocation(tabIndex: 2),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'food_swap_requests',
    titleEn: 'Food swap requests',
    sentenceEn:
        'Ask your coach to swap a food in your Nutrition plan, and open request history from Targets or the Feature guide to see each status and reply.',
    titleAr: 'طلبات تبديل الطعام',
    sentenceAr:
        'اطلب من مدربك تبديل طعام في خطة التغذية، وافتح سجل الطلبات من الأهداف أو دليل الميزات لمتابعة حالة كل طلب ورد المدرب.',
    target: 'food_swap_requests',
    location: TourRouteLocation(foodSwapRequestsPath),
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
    id: 'assistant_personal_logs',
    titleEn: 'Ask about your Cardio and Nutrition logs',
    sentenceEn:
        'Ask about saved Cardio and Nutrition records for a day or recent period, including what you ate and the Nutrition targets saved for those days.',
    titleAr: 'اسأل عن سجل الكارديو والتغذية',
    sentenceAr:
        'اسأل عن سجل الكارديو والتغذية ليوم أو فترة قريبة، وأكلك، وأهداف التغذية المحفوظة لتلك الأيام.',
    target: 'assistant',
    location: TourShellTabLocation(tabIndex: 0),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'progress',
    titleEn: 'Progress',
    sentenceEn:
        'Explore your charts, including logged volume by main muscle group '
        'using each exercise’s credits, and review Checkpoint feedback.',
    titleAr: 'التقدم',
    sentenceAr:
        'تابع مخططاتك، ومنها الحجم المسجل حسب المجموعة العضلية الرئيسية ورصيد '
        'كل تمرين، وراجع ملاحظات محطات التقدم.',
    target: 'progress',
    location: TourShellTabLocation(tabIndex: 3),
    release: 6,
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
    sentenceEn: 'Confirm or correct an unusually short or long workout duration before saving.',
    titleAr: 'تأكيد مدة الحصة',
    sentenceAr: 'أكّد مدة الحصة أو صححها إذا كانت أقصر أو أطول من المعتاد قبل حفظها.',
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
    sentenceEn: 'Choose up to two muscles, including lats, traps and rear delts, for Focus work in your Training program; muscles in the same main group share credited Focus volume, forearms and adductors retain their extra work, and Volume reviews combine shared exercise changes within weekly limits.',
    titleAr: 'نقاط الضعف',
    sentenceAr: 'اختر حتى عضلتين، ومنها اللاتس والترابيس والأكتاف الخلفية، ليركز عليها برنامجك التدريبي؛ وتشترك العضلات في المجموعة الرئيسية نفسها في حجم التركيز المحتسب، ويحتفظ الساعد والعضلات المقربة بتمارينهما الإضافية، وتجمع مراجعات مجموعات التدريب تغييرات التمارين المشتركة ضمن الحدود الأسبوعية.',
    target: 'whats_new_weak_points',
    location: TourRouteLocation(profilePath),
    release: 7,
    audience: 'lifter',
  ),
  FeatureEntry(
    id: 'assistant_why',
    titleEn: 'Ask the assistant why',
    sentenceEn: 'Ask why an exercise or training decision is in your program, or bring up something you told the assistant in an older chat.',
    titleAr: 'اسأل المساعد عن السبب',
    sentenceAr: 'اسأل عن سبب وجود تمرين أو قرار تدريبي في برنامجك التدريبي، أو اذكر شيئًا قلته للمساعد في محادثة سابقة.',
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
    sentenceEn:
        'Tell the assistant to swap an exercise by name or make another supported change to your Training program.',
    titleAr: 'عدّل برنامجك عبر المحادثة',
    sentenceAr: 'اطلب من المساعد تبديل تمرين بالاسم أو إجراء تغيير آخر يدعمه في برنامجك التدريبي.',
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
