import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/display_language/message_copy.dart';
import 'package:mayos_mobile/src/core/display_language/message_resolver.dart';
import 'package:mayos_mobile/src/core/models.dart';

String _resolve(String code, Map<String, dynamic> params) =>
    resolveStructuredMessage(
      messageCode: code,
      messageParams: params,
      englishFallback: 'Safe English fallback.',
      displayLanguage: 'ar',
    )
        .replaceAll('\u2066', '')
        .replaceAll('\u2068', '')
        .replaceAll('\u2069', '');

String _resolveProgramImport(
  String code,
  String language, {
  Map<String, dynamic> params = const <String, dynamic>{},
  int? maxCells,
}) =>
    resolveStructuredMessage(
      messageCode: code,
      messageParams: params,
      englishFallback: const MessageCopy('en')
          .programImportMessage(code, maxCells: maxCells),
      displayLanguage: language,
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
    expect(
      _resolve('http.input_too_long.v1', <String, dynamic>{
        'limit': 400,
        'rejected_input': 'private text',
      }),
      'Safe English fallback.',
    );
  });

  test('assignment notice templates keep request outcomes distinct and preserve human text', () {
    expect(
      _resolve('assignment_notice.assignment_redeemed.v1', <String, dynamic>{
        'player_name': 'alice',
      }),
      'قبل alice دعوتك للتدريب، وبدأت علاقة التدريب.',
    );
    expect(
      _resolve('assignment_notice.program_request_received.v1',
          <String, dynamic>{'player_name': 'alice'}),
      'أرسل alice طلبًا لتغيير البرنامج التدريبي. راجعه في قائمة اللاعبين.',
    );
    expect(
      _resolve('assignment_notice.program_request_applied.v1',
          <String, dynamic>{'version': 2, 'in_published_program': true}),
      'تم تنفيذ طلبك في البرنامج التدريبي الجديد (الإصدار 2).',
    );
    expect(
      _resolve('assignment_notice.program_request_applied.v1',
          <String, dynamic>{'version': 2, 'in_published_program': false}),
      'طبّق مدربك التغيير على البرنامج التدريبي (الإصدار 2).',
    );
    expect(
      _resolve('assignment_notice.program_request_applied.v1',
          <String, dynamic>{'version': null, 'in_published_program': false}),
      'طبّق مدربك التغيير على البرنامج التدريبي.',
    );
    expect(
      _resolve('assignment_notice.program_request_declined.v1',
          <String, dynamic>{'reason': '<b>Keep the squat</b>.'}),
      'رفض مدربك طلب تغيير البرنامج التدريبي: <b>Keep the squat</b>.',
    );
    expect(
      _resolve('assignment_notice.performance_regression.v1',
          <String, dynamic>{'player_name': 'alice', 'exercise_name': null}),
      'تراجع الأداء لدى alice في تمرين. راجع التنبيه في قائمة اللاعبين.',
    );
  });

  test('attendance, progression, profile, and publication notices resolve in Arabic', () {
    final List<(String, Map<String, dynamic>, String)> cases =
        <(String, Map<String, dynamic>, String)>[
      (
        'assignment_notice.training_pause_scheduled.v1',
        <String, dynamic>{
          'player_name': 'alice',
          'start_date': '2026-10-01',
          'end_date': '2026-10-03',
        },
        'حدّد alice فترة توقف عن التدريب من 2026-10-01 إلى 2026-10-03.',
      ),
      (
        'assignment_notice.missed_expected_days.v1',
        <String, dynamic>{
          'player_name': 'alice',
          'count': 2,
          'start_date': '2026-10-01',
          'end_date': '2026-10-02',
        },
        'لم يتدرب alice في يومين من أيام التدريب المتوقعة '
            '(2026-10-01 إلى 2026-10-02). راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.follow_up_due.v1',
        <String, dynamic>{'player_name': 'alice', 'due_on': '2026-10-01'},
        'حان موعد المتابعة مع alice منذ 2026-10-01. '
            'راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.stall.v1',
        <String, dynamic>{'player_name': 'alice'},
        'يحتاج alice إلى الانتباه بسبب ثبات الأداء. '
            'راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.deload_recommended.v1',
        <String, dynamic>{'player_name': 'alice'},
        'يوصى بتخفيف التدريب للاعب alice. راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.performance_regression.v1',
        <String, dynamic>{'player_name': 'alice', 'exercise_name': 'Bench Press'},
        'تراجع الأداء لدى alice في Bench Press. راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.profile_change.v1',
        <String, dynamic>{'player_name': 'alice'},
        'غيّر alice الملف التدريبي. راجع التنبيه في قائمة اللاعبين.',
      ),
      (
        'assignment_notice.program_published.v1',
        <String, dynamic>{'version': 3},
        'نشر مدربك البرنامج التدريبي، الإصدار 3.',
      ),
    ];

    for (final (String code, Map<String, dynamic> params, String expected)
        in cases) {
      expect(_resolve(code, params), expected, reason: code);
    }
  });

  test('invalid or unknown assignment notice metadata keeps its safe fallback', () {
    expect(
      resolveStructuredMessage(
        messageCode: 'assignment_notice.follow_up_due.v1',
        messageParams: const <String, dynamic>{'player_name': 'alice'},
        englishFallback: 'Follow-up due since 2026-10-01',
        displayLanguage: 'ar',
      ),
      'Follow-up due since 2026-10-01',
    );
    expect(
      resolveStructuredMessage(
        messageCode: 'assignment_notice.future.v1',
        messageParams: const <String, dynamic>{},
        englishFallback: 'Future notice fallback.',
        displayLanguage: 'ar',
      ),
      'Future notice fallback.',
    );
  });

  test('HTTP and stream error messages use safe typed Arabic values', () {
    expect(
      _resolve('http.input_too_long.v1', <String, dynamic>{'limit': 400}),
      'يجب ألا يتجاوز هذا الحقل 400 حرف',
    );
    expect(
      _resolve('ai_limit.daily_usage.v1', const <String, dynamic>{}),
      'وصلت إلى حد استخدام المساعد اليوم. أعد المحاولة غدًا.',
    );
    expect(
      _resolve('google.account_already_linked.v1', const <String, dynamic>{}),
      'حساب Google هذا مرتبط بالفعل بحساب MAYOS.',
    );
    expect(
      _resolve('chat.failed.v1', const <String, dynamic>{}),
      'تعذر على المساعد إكمال الرد. يُرجى إعادة المحاولة.',
    );
    expect(
      _resolve('google.invalid_token.v1', const <String, dynamic>{}),
      'تعذر التحقق من بيانات Google.',
    );
    expect(
      _resolve('recovery.invalid_or_expired_code.v1', const <String, dynamic>{}),
      'رمز التحقق غير صالح أو انتهت صلاحيته.',
    );
    expect(
      _resolve('recovery.code_send_limit.v1', const <String, dynamic>{}),
      'تعذر إرسال رمز التحقق الآن. حاول مجددًا لاحقًا.',
    );
    expect(
      _resolve('coach_invite.invalid_code.v1', const <String, dynamic>{}),
      'رمز دعوة تفعيل دور المدرب غير صالح أو انتهت صلاحيته.',
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

  test('Program import messages resolve from the shared English and Arabic copy', () {
    expect(
      _resolveProgramImport('program_import.invalid_reps.v1', 'en'),
      'Enter repetitions from 4 to 30.',
    );
    expect(
      _resolveProgramImport('program_import.invalid_reps.v1', 'ar'),
      'أدخل تكرارات من 4 إلى 30.',
    );
    expect(
      _resolveProgramImport('program_import.too_many_tabs.v1', 'ar'),
      'يحتوي الملف على أوراق كثيرة. قلّل عدد الأوراق ثم أعد المحاولة.',
    );
    expect(
      _resolveProgramImport(
        'program_import.too_many_cells.v1',
        'en',
        params: const <String, dynamic>{'max_cells': 2000},
        maxCells: 2000,
      ),
      'The selected sheet is too large to interpret. Trim it to 2,000 non-empty cells or fewer.',
    );
    expect(
      _resolveProgramImport(
        'program_import.too_many_cells.v1',
        'ar',
        params: const <String, dynamic>{'max_cells': 2000},
        maxCells: 2000,
      ),
      'الورقة المحددة كبيرة جدًا لفهمها. قلّلها إلى 2,000 خلية غير فارغة أو أقل.',
    );
  });

  test('weight trend coach alert renders localized text and dated evidence', () {
    final CoachAlert alert = CoachAlert.fromJson(<String, dynamic>{
      'alert_id': 'alert-1',
      'assignment_id': 'assignment-1',
      'player_username': 'player',
      'kind': CoachAlert.weightOffTargetTrendKind,
      'state': 'new',
      'created_at': '2026-10-05T12:00:00+00:00',
      'message_code': 'coach_alert.weight_off_target_trend.v1',
      'message_params': <String, dynamic>{
        'distance_change_kg': 2.0,
        'target_weight_kg': 70.0,
        'window_days': 14,
        'threshold_kg': 1.0,
      },
      'message_fallback': 'Weight moved away from the target by 2 kg.',
      'distance_change_kg': 2.0,
      'target_weight_kg': 70.0,
      'window_days': 14,
      'threshold_kg': 1.0,
      'weight_points': <Map<String, dynamic>>[
        <String, dynamic>{'date': '2026-09-21', 'weight_kg': 72.0},
        <String, dynamic>{'date': '2026-10-05', 'weight_kg': 74.0},
      ],
    });

    final String rawDescription = resolveCoachAlertDescription(alert, 'ar');
    final String isolateStart = String.fromCharCode(0x2066);
    final String isolateEnd = String.fromCharCode(0x2069);
    expect(rawDescription, contains('${isolateStart}2 kg$isolateEnd'));
    final String description = rawDescription
        .replaceAll('\u2066', '')
        .replaceAll('\u2069', '');
    expect(description, contains('ابتعد الوزن عن الهدف بمقدار 2 kg'));
    expect(description, contains('2026-09-21: 72 kg'));
    expect(description, contains('2026-10-05: 74 kg'));
    expect(description, contains('الوزن المستهدف: 70 kg'));
  });
}
