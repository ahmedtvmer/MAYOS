Map<String, dynamic> focusExerciseFixture({String kind = 'weekly_session'}) =>
    <String, dynamic>{
      'exercise_id': 'cable_fly',
      'exercise_name': 'Cable Fly',
      'target_sets': 2,
      'target_reps_min': 10,
      'target_reps_max': 15,
      'target_rpe': 9,
      'focus_extra': <String, dynamic>{
        'muscle': 'chest',
        'kind': kind,
        'reason': <String, String>{
          'en': kind == 'weekly_session'
              ? 'Added to Pull to train chest on 3 days this week.'
              : 'Added to Push, the lightest eligible day already training chest, for extra sets.',
          'ar': kind == 'weekly_session'
              ? 'أُضيف إلى Pull لتدريب الصدر في 3 أيام هذا الأسبوع.'
              : 'أُضيف إلى Push، أخف يوم مؤهل يدرب الصدر بالفعل، لإضافة مجموعات.',
        },
      },
    };
