import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/mayos_typography.dart';

void main() {
  test('every MAYOS typography role includes the Arabic glyph fallback', () {
    final List<TextStyle> roles = <TextStyle>[
      MayosTypography.display,
      MayosTypography.pageHeading,
      MayosTypography.sectionHeading,
      MayosTypography.exerciseTitle,
      MayosTypography.body,
      MayosTypography.bodySecondary,
      MayosTypography.code,
      MayosTypography.label,
      MayosTypography.numeric,
      MayosTypography.numericSmall,
      MayosTypography.numericMedium,
      MayosTypography.avatarInitials,
      MayosTypography.modeBadge,
      MayosTypography.caption,
      MayosTypography.captionStrong,
      MayosTypography.serifMedium,
    ];

    for (final TextStyle role in roles) {
      expect(
        role.fontFamilyFallback,
        contains(MayosTypography.arabicFallbackFamily),
        reason: 'Missing Arabic fallback for $role',
      );
    }

    expect(
      MayosTheme.light.textTheme.bodyMedium?.fontFamilyFallback,
      contains(MayosTypography.arabicFallbackFamily),
    );
  });

  testWidgets('Arabic fallback font assets load from the bundle',
      (WidgetTester tester) async {
    final FontLoader loader = FontLoader(MayosTypography.arabicFallbackFamily)
      ..addFont(
          rootBundle.load('assets/fonts/arabic/IBMPlexSansArabic-Regular.ttf'))
      ..addFont(
          rootBundle.load('assets/fonts/arabic/IBMPlexSansArabic-Medium.ttf'))
      ..addFont(
          rootBundle.load('assets/fonts/arabic/IBMPlexSansArabic-SemiBold.ttf'))
      ..addFont(
          rootBundle.load('assets/fonts/arabic/IBMPlexSansArabic-Bold.ttf'));
    await loader.load();
  });
}
