import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mayos_mobile/src/core/theme/mayos_theme.dart';
import 'package:mayos_mobile/src/core/theme/mayos_typography.dart';

List<TextStyle> _roles(MayosTypography typography) => <TextStyle>[
      typography.display,
      typography.pageHeading,
      typography.sectionHeading,
      typography.exerciseTitle,
      typography.body,
      typography.bodySecondary,
      typography.code,
      typography.label,
      typography.numeric,
      typography.numericSmall,
      typography.numericMedium,
      typography.avatarInitials,
      typography.modeBadge,
      typography.caption,
      typography.captionStrong,
      typography.serifMedium,
    ];

void main() {
  test('all roles select IBM Plex for Arabic and preserve English families', () {
    final MayosTypography arabic = MayosTypography.forLanguage('ar');
    final List<TextStyle> arabicRoles = _roles(arabic);
    expect(arabic.isArabic, isTrue);

    for (final TextStyle role in arabicRoles) {
      expect(role.fontFamily, MayosTypography.arabicFamily);
      expect(role.height, 1.5);
      expect(role.letterSpacing, 0);
    }

    expect(
      MayosTheme.lightForLanguage('ar').textTheme.bodyMedium?.fontFamily,
      MayosTypography.arabicFamily,
    );
    expect(
      MayosTheme.darkForLanguage('ar').textTheme.headlineLarge?.fontFamily,
      MayosTypography.arabicFamily,
    );

    final MayosTypography english = MayosTypography.forLanguage('en');
    expect(english.isArabic, isFalse);
    final List<TextStyle> englishDisplayRoles = <TextStyle>[
      english.display,
      english.pageHeading,
      english.serifMedium,
    ];
    for (final TextStyle role in englishDisplayRoles) {
      expect(role.fontFamily, MayosTypography.displayFamily);
    }
    final List<TextStyle> englishInterfaceRoles = <TextStyle>[
      english.sectionHeading,
      english.exerciseTitle,
      english.body,
      english.bodySecondary,
      english.label,
      english.numeric,
      english.numericSmall,
      english.numericMedium,
      english.avatarInitials,
      english.modeBadge,
      english.caption,
      english.captionStrong,
    ];
    for (final TextStyle role in englishInterfaceRoles) {
      expect(role.fontFamily, MayosTypography.uiFamily);
    }
    expect(english.code.fontFamily, 'monospace');
    expect(
      MayosTypography.brandWordmark.fontFamily,
      MayosTypography.uiFamily,
    );
    expect(
      MayosTheme.lightForLanguage('en').textTheme.bodyMedium?.fontFamily,
      MayosTypography.uiFamily,
    );
  });

  testWidgets('context typography follows the active app locale',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: MayosTheme.lightForLanguage('ar'),
        home: Builder(
          builder: (BuildContext context) => Text(
            '27.5',
            style: MayosTypography.of(context).numeric,
          ),
        ),
      ),
    );
    expect(
      tester.widget<Text>(find.text('27.5')).style!.fontFamily,
      MayosTypography.arabicFamily,
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        supportedLocales: const <Locale>[Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: MayosTheme.lightForLanguage('en'),
        home: Builder(
          builder: (BuildContext context) => Text(
            'Workout',
            style: MayosTypography.of(context).display,
          ),
        ),
      ),
    );
    expect(
      tester.widget<Text>(find.text('Workout')).style!.fontFamily,
      MayosTypography.displayFamily,
    );
  });

  testWidgets('Arabic font assets load from the bundle',
      (WidgetTester tester) async {
    final FontLoader loader = FontLoader(MayosTypography.arabicFamily)
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
