import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/features/player/tour/feature_list.dart';
import 'package:mayos_mobile/src/features/player/tour/tour_targets.dart';

Set<String> _registeredTargetIds() {
  final Directory lib = Directory('lib');
  final RegExp registrations = RegExp(
    r'TourTarget\s*\([\s\S]*?\bid\s*:\s*([\s\S]*?)\bchild\s*:',
  );
  final RegExp literals = RegExp("['\"]([^'\"]+)['\"]");
  final Set<String> ids = <String>{};
  for (final FileSystemEntity entity in lib.listSync(recursive: true)) {
    if (entity is! File || !entity.path.endsWith('.dart')) continue;
    final String source = entity.readAsStringSync();
    for (final RegExpMatch registration in registrations.allMatches(source)) {
      for (final RegExpMatch literal in
          literals.allMatches(registration.group(1)!)) {
        ids.add(literal.group(1)!);
      }
    }
  }
  return ids;
}

void main() {
  test('Feature list check reports entries missing Arabic copy', () {
    final List<String> errors = validateFeatureEntries(
      <FeatureEntry>[
        FeatureEntry(
          id: 'missing_arabic',
          titleEn: 'Feature',
          sentenceEn: 'A feature sentence.',
          titleAr: '   ',
          sentenceAr: 'جملة الميزة.',
          target: 'home',
          location: const TourShellTabLocation(tabIndex: 0),
          release: 0,
          audience: 'lifter',
        ),
      ],
      validTargetIds: <String>{'home'},
    );

    expect(errors, contains(contains('titleAr')));
  });

  test('MAYOS brand announcement remains in the previous release', () {
    final FeatureEntry entry = featureList.singleWhere(
      (FeatureEntry entry) => entry.id == 'brand-mayos',
    );
    expect(entry.titleEn, 'MYOS is now MAYOS');
    expect(entry.sentenceEn, "Same app, same training — we're now called MAYOS.");
    expect(entry.titleAr, 'MYOS أصبح MAYOS');
    expect(entry.sentenceAr, 'نفس التطبيق ونفس التدريب، أصبح اسمنا الآن MAYOS.');
    expect(entry.target, 'brand_mayos');
    expect(entry.release, 2);
    expect(entry.audience, 'lifter');
  });

  test('workout share card remains in release 3', () {
    expect(kReleaseShareCard, 3);
    final FeatureEntry entry = featureList.singleWhere(
      (FeatureEntry entry) => entry.id == 'workout_share_card',
    );
    expect(entry.titleEn, isNotEmpty);
    expect(entry.titleAr, isNotEmpty);
    expect(entry.sentenceEn,
        'Preview your dated workout card, then share or save it.');
    expect(entry.sentenceAr,
        'عاين بطاقة تمرينك بتاريخها، ثم شاركها أو احفظها.');
    expect(entry.target, 'home');
    expect(entry.release, kReleaseShareCard);
    expect(entry.audience, 'lifter');
  });

  test('duration check is a Home lifter entry in release 4', () {
    expect(kReleaseDurationCheck, 4);
    final FeatureEntry entry = featureList.singleWhere(
      (FeatureEntry entry) => entry.id == 'duration_check',
    );
    expect(entry.release, kReleaseDurationCheck);
    expect(currentFeatureRelease, greaterThanOrEqualTo(kReleaseDurationCheck));
    expect(entry.audience, 'lifter');
    expect(entry.target, 'home');
  });

  test('Food log has bilingual copy and a Nutrition target in the current release', () {
    final FeatureEntry entry = featureList.singleWhere((FeatureEntry entry) => entry.id == 'food_log');
    expect(entry.release, currentFeatureRelease);
    expect(entry.titleEn, 'Food log');
    expect(entry.titleAr, 'سجل الطعام');
    expect(entry.sentenceEn, isNotEmpty);
    expect(entry.sentenceAr, isNotEmpty);
    expect(entry.target, 'food_log');
    expect(entry.location, const TourShellTabLocation(tabIndex: 2));
    expect(entry.audience, 'lifter');
  });

  test('Feature list copy, targets, and Tour stop ids are valid', () {
    final Set<String> targetIds = _registeredTargetIds();
    final Set<String> ids = featureList.map((FeatureEntry entry) => entry.id).toSet();

    expect(ids.length, featureList.length);
    expect(
      validateFeatureEntries(featureList, validTargetIds: targetIds),
      isEmpty,
    );
    expect(tourV1StopIds, <String>['home', 'program', 'assistant', 'nutrition', 'progress', 'profile', 'feature_guide']);
    expect(featureList.every((FeatureEntry entry) => entry.release <= currentFeatureRelease), isTrue);
    for (final String stopId in tourV1StopIds) {
      expect(ids, contains(stopId));
    }
  });
}
