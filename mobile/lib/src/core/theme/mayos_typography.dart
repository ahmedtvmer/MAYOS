import 'package:flutter/material.dart';

import 'mayos_theme_extension.dart';

/// MAYOS typography roles.
///
/// A licensed editorial serif ([displayFamily]) carries display and page
/// headings; a clean sans ([uiFamily]) carries all interface text and numerics.
/// These are an acknowledged approximation of the reference (see DESIGN.md).
///
/// Both families are variable fonts. We select weights with explicit
/// `fontVariations` so the look does not depend on engine weight mapping.
abstract final class MayosTypography {
  static const String displayFamily = 'PlayfairDisplay';
  static const String uiFamily = 'Inter';

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

  /// Hero / display heading.
  static const TextStyle display = TextStyle(
    fontFamily: displayFamily,
    fontSize: 40,
    height: 1.08,
    fontWeight: FontWeight.w600,
    fontVariations: _serifSemiBold,
    letterSpacing: -0.5,
  );

  /// Page heading (e.g. a section's editorial title).
  static const TextStyle pageHeading = TextStyle(
    fontFamily: displayFamily,
    fontSize: 28,
    height: 1.15,
    fontWeight: FontWeight.w600,
    fontVariations: _serifSemiBold,
    letterSpacing: -0.3,
  );

  /// Section heading inside a page (sans, confident but quiet).
  static const TextStyle sectionHeading = TextStyle(
    fontFamily: uiFamily,
    fontSize: 18,
    height: 1.3,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
    letterSpacing: -0.1,
  );

  /// Exercise / card title.
  static const TextStyle exerciseTitle = TextStyle(
    fontFamily: uiFamily,
    fontSize: 16,
    height: 1.3,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
  );

  /// Primary body copy.
  static const TextStyle body = TextStyle(
    fontFamily: uiFamily,
    fontSize: 15,
    height: 1.5,
    fontWeight: FontWeight.w400,
    fontVariations: _regular,
  );

  /// Secondary / supporting body copy.
  static const TextStyle bodySecondary = TextStyle(
    fontFamily: uiFamily,
    fontSize: 14,
    height: 1.5,
    fontWeight: FontWeight.w400,
    fontVariations: _regular,
  );

  /// Selectable code; generic monospace resolves to Android/iOS system fonts.
  static const TextStyle code = TextStyle(
    fontFamily: 'monospace',
    fontFamilyFallback: <String>['Roboto Mono', 'Menlo', 'Courier New'],
    fontSize: 14,
    height: 1.4,
    fontWeight: FontWeight.w400,
  );

  /// UI label / button text.
  static const TextStyle label = TextStyle(
    fontFamily: uiFamily,
    fontSize: 14,
    height: 1.2,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
    letterSpacing: 0.1,
  );

  /// Numeric / stat figures. Tabular so values align.
  static const TextStyle numeric = TextStyle(
    fontFamily: uiFamily,
    fontSize: 28,
    height: 1.05,
    fontWeight: FontWeight.w700,
    fontVariations: _bold,
    letterSpacing: -0.5,
    fontFeatures: _tabular,
  );

  /// Small numeric / metric label.
  static const TextStyle numericSmall = TextStyle(
    fontFamily: uiFamily,
    fontSize: 17,
    height: 1.1,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
    fontFeatures: _tabular,
  );

  /// Numeric for the in-app keypad keys: between [numericSmall] and [numeric].
  static const TextStyle numericMedium = TextStyle(
    fontFamily: uiFamily,
    fontSize: 22,
    height: 1.1,
    fontWeight: FontWeight.w700,
    fontVariations: _bold,
    fontFeatures: _tabular,
  );

  /// Header-avatar initials, set on the accent-subtle disc.
  static const TextStyle avatarInitials = TextStyle(
    fontFamily: uiFamily,
    fontSize: 12,
    height: 1.1,
    fontWeight: FontWeight.w600,
    fontVariations: _semibold,
    letterSpacing: 0.1,
  );

  /// The single-letter Player/Coach badge chip on the header avatar.
  static const TextStyle modeBadge = TextStyle(
    fontFamily: uiFamily,
    fontSize: 9,
    height: 1.1,
    fontWeight: FontWeight.w700,
    fontVariations: _bold,
    letterSpacing: 0.1,
  );

  /// Caption / metadata.
  static const TextStyle caption = TextStyle(
    fontFamily: uiFamily,
    fontSize: 12,
    height: 1.35,
    fontWeight: FontWeight.w500,
    fontVariations: _medium,
    letterSpacing: 0.2,
  );

  /// Caption weight for dense labels that must hold their own in a row of
  /// neighbours (table headers).
  static const TextStyle captionStrong = TextStyle(
    fontFamily: uiFamily,
    fontSize: 12,
    height: 1.35,
    fontWeight: FontWeight.w700,
    fontVariations: _bold,
    letterSpacing: 0.2,
  );

  static const TextStyle _displaySerifMedium = TextStyle(
    fontFamily: displayFamily,
    fontWeight: FontWeight.w500,
    fontVariations: _serifMedium,
  );

  /// Builds the Material [TextTheme] for a theme, mapping MAYOS roles onto
  /// Material slots so components and existing screens inherit the system.
  static TextTheme textTheme(MayosThemeExtension c) {
    return TextTheme(
      displayLarge: display.copyWith(color: c.textPrimary),
      displayMedium: pageHeading.copyWith(color: c.textPrimary),
      displaySmall: pageHeading.copyWith(fontSize: 24, color: c.textPrimary),
      headlineLarge: pageHeading.copyWith(fontSize: 26, color: c.textPrimary),
      headlineMedium:
          sectionHeading.copyWith(fontSize: 20, color: c.textPrimary),
      headlineSmall: sectionHeading.copyWith(color: c.textPrimary),
      titleLarge: sectionHeading.copyWith(fontSize: 19, color: c.textPrimary),
      titleMedium: exerciseTitle.copyWith(color: c.textPrimary),
      titleSmall: exerciseTitle.copyWith(fontSize: 14, color: c.textPrimary),
      bodyLarge: body.copyWith(fontSize: 16, color: c.textPrimary),
      bodyMedium: body.copyWith(color: c.textPrimary),
      bodySmall: bodySecondary.copyWith(fontSize: 13, color: c.textSecondary),
      labelLarge: label.copyWith(color: c.textPrimary),
      labelMedium: caption.copyWith(fontSize: 12, color: c.textSecondary),
      labelSmall: caption.copyWith(color: c.textMuted),
    );
  }

  /// A soft serif used for the few numeric display moments that want editorial
  /// character (e.g. splash tagline). Kept for completeness/consumers.
  static const TextStyle serifMedium = _displaySerifMedium;
}
