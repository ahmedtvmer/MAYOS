import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/arabic_count.dart';
import 'package:mayos_mobile/src/core/display_language/catalog.dart';
import 'package:mayos_mobile/src/core/display_language/controller.dart';
import 'package:mayos_mobile/src/core/models.dart';
import 'package:mayos_mobile/src/core/display_language/onboarding_copy.dart';
import 'package:mayos_mobile/src/core/display_language/store.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/ui/mayos_app_header.dart';
import 'package:mayos_mobile/src/core/ui/mayos_bottom_navigation.dart';
import 'package:mayos_mobile/src/features/player/onboarding/onboarding_widgets.dart';

class _ArabicLanguage extends DisplayLanguageController {
  _ArabicLanguage()
      : super(InMemoryDisplayLanguageStore(), systemLanguage: 'ar');
}

void main() {
  test('unknown onboarding codes use server labels instead of machine codes',
      () {
    const OnboardingCopy arabic = OnboardingCopy('ar');
    expect(
      arabic.question('future_field_42', serverLabel: 'Server question'),
      'Server question',
    );
    expect(arabic.question('future_field_42'), 'السؤال');
    final IntakeField futureField = IntakeField.fromJson(<String, dynamic>{
      'name': 'equipment_access',
      'type': 'enum',
      'option_descriptions': <String, String>{'future_value': 'Server choice'},
    });
    expect(arabic.option('equipment_access', 'future_value'), isNull);
    expect(
      onboardingOptionLabel(futureField, 'future_value', copy: arabic),
      'Server choice',
    );
    expect(arabic.option('equipment_access', 'Commercial gym'),
        'صالة رياضية تجارية');
    expect(arabic.option('equipment_access', 'Home gym'), 'معدات منزلية');
    expect(
        arabic.option('equipment_access', 'Bodyweight only'), 'وزن الجسم فقط');
    expect(
      arabic.reviewLabel('future_field_42', serverLabel: 'Server label'),
      'Server label',
    );
    expect(
      questionFor('future_field_42', serverLabel: 'Server question'),
      'Server question',
    );
    expect(questionFor('future_field_42'), 'Question');
    expect(
      const OnboardingCopy('en').option('equipment_access', 'Commercial gym'),
      'Commercial gym',
    );
    expect(
      const OnboardingCopy('en').option('equipment_access', 'Home gym'),
      'Home gym',
    );
    expect(
      const OnboardingCopy('en').option('equipment_access', 'Bodyweight only'),
      'Bodyweight only',
    );
    expect(const OnboardingCopy('en').unitFor('age'), 'years');
    expect(const OnboardingCopy('en').yearsValue('3'), '3 years');
    expect(const OnboardingCopy('ar').unitFor('age'), 'سنوات');
    expect(const OnboardingCopy('ar').yearsValue('1'), 'سنة واحدة');
    expect(const OnboardingCopy('ar').yearsValue('3'), '3 سنوات');
    expect(const OnboardingCopy('ar').yearsValue('11'), '11 سنة');
    expect(const OnboardingCopy('ar').yearsValue('2.5'), '2.5 سنة');
    expect(
      const MayosCopy('en').shortDate(DateTime(2026, 6, 3)),
      'Jun 3',
    );
    expect(
      const MayosCopy('ar').shortDate(DateTime(2026, 6, 3)),
      '3 يونيو',
    );
    expect(const MayosCopy('ar').nextSessionLabel(null), 'الحصة التالية');
    expect(
      const MayosCopy('ar').nextSessionLabel(3),
      'الحصة التالية · الأربعاء',
    );
  });

  test('Arabic count phrases use simple singular, dual, plural, and 11+ forms',
      () {
    expect(arabicCountPhrase(0, ArabicCountNoun.day), '0 أيام');
    expect(arabicCountPhrase(1, ArabicCountNoun.day), 'يوم واحد');
    expect(arabicCountPhrase(2, ArabicCountNoun.day), 'يومان');
    expect(arabicCountPhrase(3, ArabicCountNoun.day), '3 أيام');
    expect(arabicCountPhrase(11, ArabicCountNoun.day), '11 يومًا');
    expect(
        arabicCountPhrase(1, ArabicCountNoun.warmupSet), 'مجموعة إحماء واحدة');
    expect(arabicCountPhrase(2, ArabicCountNoun.warmupSet), 'مجموعتا إحماء');
    expect(arabicCountPhrase(3, ArabicCountNoun.warmupSet), '3 مجموعات إحماء');
    expect(arabicCountPhrase(11, ArabicCountNoun.warmupSet), '11 مجموعة إحماء');
    const MayosCopy arabic = MayosCopy('ar');
    expect(arabic.programFrequency(1), 'يوم واحد في الأسبوع');
    expect(arabic.programFrequency(2), 'يومان في الأسبوع');
    expect(arabic.programFrequency(3), '3 أيام في الأسبوع');
    expect(arabic.programFrequency(11), '11 يومًا في الأسبوع');
    expect(arabic.warmupSetCount(3), '3 مجموعات إحماء');
    expect(arabic.warmupSetCount(11), '11 مجموعة إحماء');
    expect(arabic.lastDaysCountedSetsPerMuscle(2),
        'آخر يومين · مجموعات محسوبة لكل عضلة');
    expect(arabic.restTime(2), 'راحة ثانيتين');
    expect(arabic.repetitionValue('30', '1'), '30 kg × تكرار واحد');
    expect(arabic.repetitionValue('30', '2'), '30 kg × تكراران');
    expect(arabic.repetitionValue('30', '3'), '30 kg × 3 تكرارات');
    expect(arabic.repetitionValue('30', '11'), '30 kg × 11 تكرارًا');
    expect(arabic.countedSetsMetric(1), 'مجموعة محسوبة واحدة لكل عضلة');
    expect(arabic.countedSetsMetric(2), 'مجموعتان محسوبتان لكل عضلة');
    expect(arabic.countedSetsMetric(3), '3 مجموعات محسوبة لكل عضلة');
    expect(arabic.countedSetsMetric(11), '11 مجموعة محسوبة لكل عضلة');
    expect(arabic.countedSetsMetric(0.5), '0.5 مجموعة محسوبة لكل عضلة');
    expect(const MayosCopy('en').countedSetsMetric(2), '2 weighted sets');
    expect(
      const MayosCopy('en').countedSetsMetric(1.04),
      '1.0 weighted sets',
    );
    expect(
      const MayosCopy('en').countedSetsMetric(1.04, roundNearInteger: true),
      '1 weighted sets',
    );
    expect(
      arabic.pendingWorkoutDrafts(1),
      'مسودة تدريبية واحدة بانتظار المزامنة',
    );
    expect(
      arabic.pendingWorkoutDrafts(2),
      'مسودتان تدريبيتان بانتظار المزامنة',
    );
    expect(
      arabic.pendingWorkoutDrafts(3),
      '3 مسودات تدريبية بانتظار المزامنة',
    );
    expect(
      arabic.pendingWorkoutDrafts(11),
      '11 مسودة تدريبية بانتظار المزامنة',
    );
    expect(
        const MayosCopy('ar').checkpointWorkout(10), 'حصتك التدريبية رقم 10');
    expect(const MayosCopy('en').checkpointWorkout(10), 'Your 10th workout');
    expect(
      const MayosCopy('ar').connectionFailure,
      'يتطلب هذا اتصالًا بالإنترنت. لم يتغير شيء.',
    );
    expect(
      arabic.deloadChangeSummary(
        applied: true,
        suggested: false,
        volumeMultiplier: 1,
        intensityCapRpe: null,
      ),
      'لم تُطبق تغييرات على المجموعات أو RIR.',
    );
    expect(
      arabic.deloadChangeSummary(
        applied: false,
        suggested: true,
        volumeMultiplier: 1,
        intensityCapRpe: null,
      ),
      'لم تُقترح تغييرات على المجموعات أو RIR. أُبلغ مدربك.',
    );
  });

  testWidgets('Arabic shared player chrome keeps badge digits Western',
      (WidgetTester tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: <Override>[
        displayLanguageProvider.overrideWith((ref) => _ArabicLanguage()),
      ],
      child: MaterialApp(
        theme: MayosTheme.light,
        home: const Directionality(
          textDirection: TextDirection.rtl,
          child: Scaffold(
            appBar: PreferredSize(
              preferredSize: Size.fromHeight(72),
              child: MayosAppHeader(showBack: true, title: 'اختبار'),
            ),
            body: SizedBox.shrink(),
            bottomNavigationBar: MayosBottomNavigation(
              items: <MayosNavItem>[
                MayosNavItem(
                    label: 'الرئيسية',
                    icon: Icons.home,
                    selectedIcon: Icons.home,
                    badge: 3),
                MayosNavItem(
                    label: 'البرنامج التدريبي',
                    icon: Icons.list,
                    selectedIcon: Icons.list),
              ],
              index: 0,
              onSelected: _noop,
            ),
          ),
        ),
      ),
    ));
    await tester.pump();
    final Icon backArrow = tester.widget<Icon>(find.byIcon(Icons.arrow_back));
    expect(backArrow.icon!.matchTextDirection, isTrue);
    expect(
      Directionality.of(tester.element(find.byIcon(Icons.arrow_back))),
      TextDirection.rtl,
    );
    expect(find.byTooltip('رجوع'), findsOneWidget);
    expect(find.text('الرئيسية'), findsOneWidget);
    expect(find.text('البرنامج التدريبي'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.text('٣'), findsNothing);
    expect(
      Directionality.of(tester.element(find.text('الرئيسية'))),
      TextDirection.rtl,
    );
  });
}

void _noop(int _) {}
