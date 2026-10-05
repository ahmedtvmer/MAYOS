import 'package:flutter/material.dart';

import 'mayos_theme_extension.dart';

/// MAYOS typography roles selected from the active Display language.
///
/// Widgets resolve the shared roles from their build context. This keeps
/// typography tied to the displayed app version, independently of assistant
/// reply language.
final class MayosTypography {
  const MayosTypography._({
    required this.interfaceFamily,
    required this.fallbackFamilies,
    required this.isArabic,
    required this.display,
    required this.pageHeading,
    required this.sectionHeading,
    required this.exerciseTitle,
    required this.body,
    required this.bodySecondary,
    required this.code,
    required this.label,
    required this.numeric,
    required this.numericSmall,
    required this.numericMedium,
    required this.avatarInitials,
    required this.modeBadge,
    required this.caption,
    required this.captionStrong,
    required this.serifMedium,
  });

  static const String displayFamily = 'PlayfairDisplay';
  static const String uiFamily = 'Inter';
  static const String arabicFamily = 'IBMPlexSansArabic';
  static const List<String> fontFamilyFallback = <String>[arabicFamily];

  static const List<FontVariation> _serifSemiBold = <FontVariation>[
    FontVariation('wght', 600),
  ];
  static const List<FontVariation> _serifMedium = <FontVariation>[
    FontVariation('wght', 500),
  ];
  static const List<FontVariation> _regular = <FontVariation>[
    FontVariation('wght', 400),
    FontVariation('opsz', 16),
  ];
  static const List<FontVariation> _medium = <FontVariation>[
    FontVariation('wght', 500),
    FontVariation('opsz', 16),
  ];
  static const List<FontVariation> _semibold = <FontVariation>[
    FontVariation('wght', 600),
    FontVariation('opsz', 16),
  ];
  static const List<FontVariation> _bold = <FontVariation>[
    FontVariation('wght', 700),
    FontVariation('opsz', 20),
  ];
  static const List<FontFeature> _tabular = <FontFeature>[
    FontFeature.tabularFigures(),
  ];
  static const TextStyle brandWordmark = TextStyle(
    fontFamily: uiFamily,
    fontFamilyFallback: fontFamilyFallback,
    fontSize: 14,
    height: 1.2,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
    letterSpacing: 0.1,
  );

  static const MayosTypography _english = MayosTypography._(
    interfaceFamily: uiFamily,
    fallbackFamilies: fontFamilyFallback,
    isArabic: false,
    display: TextStyle(
      fontFamily: displayFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 40,
      height: 1.08,
      fontWeight: FontWeight.w600,
      fontVariations: _serifSemiBold,
      letterSpacing: -0.5,
    ),
    pageHeading: TextStyle(
      fontFamily: displayFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 28,
      height: 1.15,
      fontWeight: FontWeight.w600,
      fontVariations: _serifSemiBold,
      letterSpacing: -0.3,
    ),
    sectionHeading: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 18,
      height: 1.3,
      fontWeight: FontWeight.w600,
      fontVariations: _semibold,
      letterSpacing: -0.1,
    ),
    exerciseTitle: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 16,
      height: 1.3,
      fontWeight: FontWeight.w600,
      fontVariations: _semibold,
    ),
    body: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 15,
      height: 1.5,
      fontWeight: FontWeight.w400,
      fontVariations: _regular,
    ),
    bodySecondary: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 14,
      height: 1.5,
      fontWeight: FontWeight.w400,
      fontVariations: _regular,
    ),
    code: TextStyle(
      fontFamily: 'monospace',
      fontFamilyFallback: <String>[
        'Roboto Mono',
        'Menlo',
        'Courier New',
        arabicFamily,
      ],
      fontSize: 14,
      height: 1.4,
      fontWeight: FontWeight.w400,
    ),
    label: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 14,
      height: 1.2,
      fontWeight: FontWeight.w600,
      fontVariations: _semibold,
      letterSpacing: 0.1,
    ),
    numeric: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 28,
      height: 1.05,
      fontWeight: FontWeight.w700,
      fontVariations: _bold,
      letterSpacing: -0.5,
      fontFeatures: _tabular,
    ),
    numericSmall: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 17,
      height: 1.1,
      fontWeight: FontWeight.w600,
      fontVariations: _semibold,
      fontFeatures: _tabular,
    ),
    numericMedium: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 22,
      height: 1.1,
      fontWeight: FontWeight.w700,
      fontVariations: _bold,
      fontFeatures: _tabular,
    ),
    avatarInitials: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 12,
      height: 1.1,
      fontWeight: FontWeight.w600,
      fontVariations: _semibold,
      letterSpacing: 0.1,
    ),
    modeBadge: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 9,
      height: 1.1,
      fontWeight: FontWeight.w700,
      fontVariations: _bold,
      letterSpacing: 0.1,
    ),
    caption: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 12,
      height: 1.35,
      fontWeight: FontWeight.w500,
      fontVariations: _medium,
      letterSpacing: 0.2,
    ),
    captionStrong: TextStyle(
      fontFamily: uiFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontSize: 12,
      height: 1.35,
      fontWeight: FontWeight.w700,
      fontVariations: _bold,
      letterSpacing: 0.2,
    ),
    serifMedium: TextStyle(
      fontFamily: displayFamily,
      fontFamilyFallback: fontFamilyFallback,
      fontWeight: FontWeight.w500,
      fontVariations: _serifMedium,
    ),
  );

  static final MayosTypography _arabic = _english._asArabic();

  final String interfaceFamily;
  final List<String> fallbackFamilies;
  final bool isArabic;
  final TextStyle display;
  final TextStyle pageHeading;
  final TextStyle sectionHeading;
  final TextStyle exerciseTitle;
  final TextStyle body;
  final TextStyle bodySecondary;
  final TextStyle code;
  final TextStyle label;
  final TextStyle numeric;
  final TextStyle numericSmall;
  final TextStyle numericMedium;
  final TextStyle avatarInitials;
  final TextStyle modeBadge;
  final TextStyle caption;
  final TextStyle captionStrong;
  final TextStyle serifMedium;

  MayosTypography _asArabic() => MayosTypography._(
        interfaceFamily: arabicFamily,
        fallbackFamilies: const <String>[],
        isArabic: true,
        display: _arabicStyle(display),
        pageHeading: _arabicStyle(pageHeading),
        sectionHeading: _arabicStyle(sectionHeading),
        exerciseTitle: _arabicStyle(exerciseTitle),
        body: _arabicStyle(body),
        bodySecondary: _arabicStyle(bodySecondary),
        code: _arabicStyle(code),
        label: _arabicStyle(label),
        numeric: _arabicStyle(numeric),
        numericSmall: _arabicStyle(numericSmall),
        numericMedium: _arabicStyle(numericMedium),
        avatarInitials: _arabicStyle(avatarInitials),
        modeBadge: _arabicStyle(modeBadge),
        caption: _arabicStyle(caption),
        captionStrong: _arabicStyle(captionStrong),
        serifMedium: _arabicStyle(serifMedium),
      );

  /// Resolves typography from the app's active locale, which is the account's
  /// selected Display language inside MAYOS.
  static MayosTypography of(BuildContext context) {
    final String language = Localizations.maybeLocaleOf(context)?.languageCode
            .toLowerCase() ??
        'en';
    return forLanguage(language);
  }

  static MayosTypography forLanguage(String language) =>
      language.toLowerCase() == 'ar' ? _arabic : _english;

  /// Builds the Material [TextTheme] from the same shared roles used by
  /// explicit screen styles.
  static TextTheme textTheme(
    MayosThemeExtension colors,
    MayosTypography type,
  ) {
    return TextTheme(
      displayLarge: type.display.copyWith(color: colors.textPrimary),
      displayMedium: type.pageHeading.copyWith(color: colors.textPrimary),
      displaySmall: type.pageHeading.copyWith(
        fontSize: 24,
        color: colors.textPrimary,
      ),
      headlineLarge: type.pageHeading.copyWith(
        fontSize: 26,
        color: colors.textPrimary,
      ),
      headlineMedium: type.sectionHeading.copyWith(
        fontSize: 20,
        color: colors.textPrimary,
      ),
      headlineSmall: type.sectionHeading.copyWith(color: colors.textPrimary),
      titleLarge: type.sectionHeading.copyWith(
        fontSize: 19,
        color: colors.textPrimary,
      ),
      titleMedium: type.exerciseTitle.copyWith(color: colors.textPrimary),
      titleSmall: type.exerciseTitle.copyWith(
        fontSize: 14,
        color: colors.textPrimary,
      ),
      bodyLarge: type.body.copyWith(fontSize: 16, color: colors.textPrimary),
      bodyMedium: type.body.copyWith(color: colors.textPrimary),
      bodySmall: type.bodySecondary.copyWith(
        fontSize: 13,
        color: colors.textSecondary,
      ),
      labelLarge: type.label.copyWith(color: colors.textPrimary),
      labelMedium: type.caption.copyWith(
        fontSize: 12,
        color: colors.textSecondary,
      ),
      labelSmall: type.caption.copyWith(color: colors.textMuted),
    );
  }

  static TextStyle _arabicStyle(TextStyle style) => style.copyWith(
        fontFamily: arabicFamily,
        fontFamilyFallback: const <String>[],
        height: 1.5,
        letterSpacing: 0,
        fontVariations: const <FontVariation>[],
      );
}
