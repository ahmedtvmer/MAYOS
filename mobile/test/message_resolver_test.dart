import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/message_resolver.dart';

String _resolve(String code, Map<String, dynamic> params) =>
    resolveStructuredMessage(
      messageCode: code,
      messageParams: params,
      englishFallback: 'Safe English fallback.',
      displayLanguage: 'ar',
    ).replaceAll('\u2066', '').replaceAll('\u2069', '');

void main() {
  test('supported coach alert codes render their typed evidence in Arabic', () {
    expect(
      _resolve('coach_alert.missed_expected_days.v1', <String, dynamic>{
        'count': 2,
        'start_date': '2026-09-20',
        'end_date': '2026-09-21',
      }),
      'فات اللاعب يومان من أيام التدريب المتوقعة '
      '(2026-09-20 إلى 2026-09-21)',
    );
    expect(
      _resolve('coach_alert.follow_up_due.v1', <String, dynamic>{
        'due_on': '2026-10-01',
      }),
      'حان موعد المتابعة منذ 2026-10-01',
    );
    expect(
      _resolve('coach_alert.stall.v1', <String, dynamic>{
        'count': 8,
        'window_start_date': '2026-09-15',
      }),
      'توقف التقدم: 8 حصص تدريبية دون رقم قياسي شخصي (منذ 2026-09-15)',
    );
    expect(
      _resolve('coach_alert.deload_recommended.v1', <String, dynamic>{
        'reason_code': 'rolling_readiness_crash',
        'recent_readiness_avg': 1.7,
        'choice': 'apply',
      }),
      'يوصى بتخفيف التدريب بسبب انخفاض الاستعداد في آخر 3 حصص تدريبية '
      '(المتوسط 1.7/5) · اختار اللاعب تطبيقه في الحصة التدريبية التالية فقط',
    );
    expect(
      _resolve('coach_alert.deload_recommended.v1', <String, dynamic>{
        'reason_code': 'high_exertion_density',
        'recent_readiness_avg': 2.5,
        'choice': null,
      }),
      'يوصى بتخفيف التدريب بسبب ارتفاع نسبة مجموعات التدريب عند '
      'RIR 0.5 أو أقل مع انخفاض الاستعداد',
    );
    expect(
      _resolve('coach_alert.deload_recommended.v1', <String, dynamic>{
        'reason_code': 'acute_readiness_floor',
        'recent_readiness_avg': 1.0,
        'choice': 'undo',
      }),
      'يوصى بتخفيف التدريب بعد تسجيل الاستعداد بدرجة 1/5 · اختار اللاعب '
      'التراجع عنه للحصة التدريبية التالية فقط',
    );
    expect(
      _resolve('coach_alert.performance_regression.v1', <String, dynamic>{
        'exercise_name': 'Bench Press',
        'e1rm_delta': -6.2,
        'status_badge': 'OVERSHOOT',
      }),
      'تراجع الأداء — Bench Press: e1RM −6.2 kg (OVERSHOOT)',
    );
    expect(
      _resolve('coach_alert.profile_change.v1', <String, dynamic>{
        'changed_fields': <String>[
          'injuries_or_limitations',
          'equipment_access',
        ],
      }),
      'تغير الملف التدريبي: الإصابات أو القيود، المعدات المتاحة',
    );
  });

  test('unknown and invalid metadata uses fallback or localized generic copy',
      () {
    expect(
      resolveStructuredMessage(
        messageCode: 'future.raw.code',
        messageParams: const <String, dynamic>{},
        englishFallback: 'Original safe fallback.',
        displayLanguage: 'ar',
      ),
      'Original safe fallback.',
    );
    expect(
      resolveStructuredMessage(
        messageCode: 'coach_alert.missed_expected_days.v1',
        messageParams: const <String, dynamic>{'count': '2'},
        englishFallback: 'Original safe fallback.',
        displayLanguage: 'ar',
      ),
      'Original safe fallback.',
    );
    expect(
      resolveStructuredMessage(
        messageCode: 'future.raw.code',
        messageParams: null,
        englishFallback: null,
        displayLanguage: 'ar',
      ),
      'تعذر عرض الرسالة.',
    );
  });

  test('known messages switch language from the same structured values', () {
    const Map<String, dynamic> params = <String, dynamic>{
      'due_on': '2026-10-01',
    };
    expect(
      resolveStructuredMessage(
        messageCode: 'coach_alert.follow_up_due.v1',
        messageParams: params,
        englishFallback: 'Follow-up due since 2026-10-01',
        displayLanguage: 'en',
      ),
      'Follow-up due since 2026-10-01',
    );
    expect(
      resolveStructuredMessage(
        messageCode: 'coach_alert.follow_up_due.v1',
        messageParams: params,
        englishFallback: 'Follow-up due since 2026-10-01',
        displayLanguage: 'ar',
      ),
      contains('حان موعد المتابعة'),
    );
  });
}
