import 'package:flutter/material.dart';

import 'myos_colors.dart';

/// MYOS-specific semantics that do not belong in Material's [ColorScheme]:
/// layered surface roles, borders, muted text, selection, semantic states and
/// chart series. Read through `MyosTheme.of(context)`.
@immutable
class MyosThemeExtension extends ThemeExtension<MyosThemeExtension> {
  const MyosThemeExtension({
    required this.brightness,
    required this.canvas,
    required this.surface,
    required this.surfaceElevated,
    required this.surfaceSunken,
    required this.secondarySurface,
    required this.tableHeader,
    required this.border,
    required this.borderStrong,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.textDisabled,
    required this.accent,
    required this.accentPressed,
    required this.onAccent,
    required this.accentSubtle,
    required this.accentWash,
    required this.selectedSurface,
    required this.selectedBorder,
    required this.focusRing,
    required this.success,
    required this.successTint,
    required this.warning,
    required this.danger,
    required this.onSuccess,
    required this.onWarning,
    required this.onDanger,
    required this.chartPrimary,
    required this.chartSecondary,
    required this.chartTertiary,
    required this.pressedOverlay,
    required this.shadows,
  });

  final Brightness brightness;

  /// Page background.
  final Color canvas;
  final Color surface;
  final Color surfaceElevated;
  final Color surfaceSunken;
  final Color secondarySurface;
  final Color tableHeader;

  final Color border;
  final Color borderStrong;

  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Color textDisabled;

  final Color accent;
  final Color accentPressed;
  final Color onAccent;

  /// Faint blue wash for highlighted rows/chips (accent at low opacity).
  final Color accentSubtle;

  /// The accent as a 14% wash: fills drawn *behind* accent content (the rest
  /// bar's draining track, #125), lighter than [accentSubtle] so the accent
  /// piece on top of it keeps its contrast.
  final Color accentWash;

  final Color selectedSurface;
  final Color selectedBorder;
  final Color focusRing;

  final Color success;

  /// The success colour as a faint row wash (a ticked logger row).
  final Color successTint;

  final Color warning;
  final Color danger;
  final Color onSuccess;
  final Color onWarning;
  final Color onDanger;

  final Color chartPrimary;
  final Color chartSecondary;
  final Color chartTertiary;

  /// Ink overlay for pressed/hover states on neutral surfaces.
  final Color pressedOverlay;

  final List<BoxShadow> shadows;

  static const MyosThemeExtension dark = MyosThemeExtension(
    brightness: Brightness.dark,
    canvas: MyosPalette.darkCanvas,
    surface: MyosPalette.darkSurface,
    surfaceElevated: MyosPalette.darkSurfaceElevated,
    surfaceSunken: MyosPalette.darkSurfaceSunken,
    secondarySurface: MyosPalette.darkSecondarySurface,
    tableHeader: MyosPalette.darkSurfaceElevated,
    border: MyosPalette.darkBorder,
    borderStrong: MyosPalette.darkBorderStrong,
    textPrimary: MyosPalette.darkTextPrimary,
    textSecondary: MyosPalette.darkTextSecondary,
    textMuted: MyosPalette.darkTextMuted,
    textDisabled: MyosPalette.darkTextMuted,
    accent: MyosPalette.blue,
    accentPressed: MyosPalette.bluePressed,
    onAccent: MyosPalette.white,
    accentSubtle: Color(0x1F2F6BFF),
    accentWash: Color(0x242F6BFF),
    selectedSurface: MyosPalette.darkSelectedSurface,
    selectedBorder: MyosPalette.blue,
    focusRing: Color(0xFF6EA0FF),
    success: MyosPalette.successDark,
    successTint: Color(0x2934D399),
    warning: MyosPalette.warningDark,
    danger: MyosPalette.dangerDark,
    onSuccess: Color(0xFF04160E),
    onWarning: Color(0xFF1C1200),
    onDanger: Color(0xFF2A0A0A),
    chartPrimary: Color(0xFF4C8DFF),
    chartSecondary: Color(0xFF34D399),
    chartTertiary: Color(0xFFF5A524),
    pressedOverlay: Color(0x1FFFFFFF),
    // Deep navy relies on layered surfaces and borders; shadows stay minimal.
    shadows: <BoxShadow>[],
  );

  static const MyosThemeExtension light = MyosThemeExtension(
    brightness: Brightness.light,
    canvas: MyosPalette.lightCanvas,
    surface: MyosPalette.lightSurface,
    surfaceElevated: MyosPalette.lightSurfaceElevated,
    surfaceSunken: MyosPalette.lightSurfaceSunken,
    secondarySurface: MyosPalette.lightSecondarySurface,
    tableHeader: MyosPalette.lightSecondarySurface,
    border: MyosPalette.lightBorder,
    borderStrong: MyosPalette.lightBorderStrong,
    textPrimary: MyosPalette.lightTextPrimary,
    textSecondary: MyosPalette.lightTextSecondary,
    textMuted: MyosPalette.lightTextMuted,
    textDisabled: MyosPalette.lightTextMuted,
    accent: MyosPalette.blueDeep,
    accentPressed: MyosPalette.bluePressedDeep,
    onAccent: MyosPalette.white,
    accentSubtle: Color(0x142563EB),
    accentWash: Color(0x242563EB),
    selectedSurface: MyosPalette.lightSelectedSurface,
    selectedBorder: MyosPalette.blueDeep,
    focusRing: MyosPalette.blueDeep,
    success: MyosPalette.successLight,
    successTint: Color(0x2916A34A),
    warning: MyosPalette.warningLight,
    danger: MyosPalette.dangerLight,
    onSuccess: MyosPalette.white,
    onWarning: MyosPalette.white,
    onDanger: MyosPalette.white,
    chartPrimary: Color(0xFF2563EB),
    chartSecondary: Color(0xFF16A34A),
    chartTertiary: Color(0xFFD97706),
    pressedOverlay: Color(0x0F000000),
    shadows: <BoxShadow>[
      BoxShadow(
        color: Color(0x140F1B2E),
        blurRadius: 18,
        offset: Offset(0, 6),
      ),
    ],
  );

  /// Dark tokens for the logged-out surfaces that sit on the gym photo (#110).
  ///
  /// Built from [dark] so components keep their dark chrome, with the few
  /// colours drawn on the photo itself lightened to clear WCAG AA against the
  /// blurred photo under the 60% black overlay. See `assets/ATTRIBUTION.md`.
  static final MyosThemeExtension wallpaper = dark.copyWith(
    textSecondary: MyosPalette.wallpaperTextSecondary,
    textMuted: MyosPalette.wallpaperTextMuted,
    danger: MyosPalette.wallpaperDanger,
    border: MyosPalette.wallpaperBorder,
    borderStrong: MyosPalette.wallpaperBorderStrong,
  );

  bool get isDark => brightness == Brightness.dark;

  @override
  MyosThemeExtension copyWith({
    Brightness? brightness,
    Color? canvas,
    Color? surface,
    Color? surfaceElevated,
    Color? surfaceSunken,
    Color? secondarySurface,
    Color? tableHeader,
    Color? border,
    Color? borderStrong,
    Color? textPrimary,
    Color? textSecondary,
    Color? textMuted,
    Color? textDisabled,
    Color? accent,
    Color? accentPressed,
    Color? onAccent,
    Color? accentSubtle,
    Color? accentWash,
    Color? selectedSurface,
    Color? selectedBorder,
    Color? focusRing,
    Color? success,
    Color? successTint,
    Color? warning,
    Color? danger,
    Color? onSuccess,
    Color? onWarning,
    Color? onDanger,
    Color? chartPrimary,
    Color? chartSecondary,
    Color? chartTertiary,
    Color? pressedOverlay,
    List<BoxShadow>? shadows,
  }) {
    return MyosThemeExtension(
      brightness: brightness ?? this.brightness,
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      surfaceSunken: surfaceSunken ?? this.surfaceSunken,
      secondarySurface: secondarySurface ?? this.secondarySurface,
      tableHeader: tableHeader ?? this.tableHeader,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textMuted: textMuted ?? this.textMuted,
      textDisabled: textDisabled ?? this.textDisabled,
      accent: accent ?? this.accent,
      accentPressed: accentPressed ?? this.accentPressed,
      onAccent: onAccent ?? this.onAccent,
      accentSubtle: accentSubtle ?? this.accentSubtle,
      accentWash: accentWash ?? this.accentWash,
      selectedSurface: selectedSurface ?? this.selectedSurface,
      selectedBorder: selectedBorder ?? this.selectedBorder,
      focusRing: focusRing ?? this.focusRing,
      success: success ?? this.success,
      successTint: successTint ?? this.successTint,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
      onSuccess: onSuccess ?? this.onSuccess,
      onWarning: onWarning ?? this.onWarning,
      onDanger: onDanger ?? this.onDanger,
      chartPrimary: chartPrimary ?? this.chartPrimary,
      chartSecondary: chartSecondary ?? this.chartSecondary,
      chartTertiary: chartTertiary ?? this.chartTertiary,
      pressedOverlay: pressedOverlay ?? this.pressedOverlay,
      shadows: shadows ?? this.shadows,
    );
  }

  @override
  MyosThemeExtension lerp(
      ThemeExtension<MyosThemeExtension>? other, double t) {
    if (other is! MyosThemeExtension) {
      return this;
    }
    return MyosThemeExtension(
      brightness: t < 0.5 ? brightness : other.brightness,
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceElevated: Color.lerp(surfaceElevated, other.surfaceElevated, t)!,
      surfaceSunken: Color.lerp(surfaceSunken, other.surfaceSunken, t)!,
      secondarySurface:
          Color.lerp(secondarySurface, other.secondarySurface, t)!,
      tableHeader: Color.lerp(tableHeader, other.tableHeader, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textMuted: Color.lerp(textMuted, other.textMuted, t)!,
      textDisabled: Color.lerp(textDisabled, other.textDisabled, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      accentPressed: Color.lerp(accentPressed, other.accentPressed, t)!,
      onAccent: Color.lerp(onAccent, other.onAccent, t)!,
      accentSubtle: Color.lerp(accentSubtle, other.accentSubtle, t)!,
      accentWash: Color.lerp(accentWash, other.accentWash, t)!,
      selectedSurface: Color.lerp(selectedSurface, other.selectedSurface, t)!,
      selectedBorder: Color.lerp(selectedBorder, other.selectedBorder, t)!,
      focusRing: Color.lerp(focusRing, other.focusRing, t)!,
      success: Color.lerp(success, other.success, t)!,
      successTint: Color.lerp(successTint, other.successTint, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      onSuccess: Color.lerp(onSuccess, other.onSuccess, t)!,
      onWarning: Color.lerp(onWarning, other.onWarning, t)!,
      onDanger: Color.lerp(onDanger, other.onDanger, t)!,
      chartPrimary: Color.lerp(chartPrimary, other.chartPrimary, t)!,
      chartSecondary: Color.lerp(chartSecondary, other.chartSecondary, t)!,
      chartTertiary: Color.lerp(chartTertiary, other.chartTertiary, t)!,
      pressedOverlay: Color.lerp(pressedOverlay, other.pressedOverlay, t)!,
      shadows: BoxShadow.lerpList(shadows, other.shadows, t)!,
    );
  }
}
