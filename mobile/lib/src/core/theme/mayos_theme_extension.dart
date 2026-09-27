import 'package:flutter/material.dart';

import 'mayos_colors.dart';

/// MAYOS-specific semantics that do not belong in Material's [ColorScheme]:
/// layered surface roles, borders, muted text, selection, semantic states and
/// chart series. Read through `MayosTheme.of(context)`.
@immutable
class MayosThemeExtension extends ThemeExtension<MayosThemeExtension> {
  const MayosThemeExtension({
    required this.brightness,
    required this.canvas,
    required this.surface,
    required this.surfaceElevated,
    required this.surfaceSunken,
    required this.secondarySurface,
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
    required this.selectedSurface,
    required this.selectedBorder,
    required this.focusRing,
    required this.success,
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

  final Color selectedSurface;
  final Color selectedBorder;
  final Color focusRing;

  final Color success;
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

  static const MayosThemeExtension dark = MayosThemeExtension(
    brightness: Brightness.dark,
    canvas: MayosPalette.darkCanvas,
    surface: MayosPalette.darkSurface,
    surfaceElevated: MayosPalette.darkSurfaceElevated,
    surfaceSunken: MayosPalette.darkSurfaceSunken,
    secondarySurface: MayosPalette.darkSecondarySurface,
    border: MayosPalette.darkBorder,
    borderStrong: MayosPalette.darkBorderStrong,
    textPrimary: MayosPalette.darkTextPrimary,
    textSecondary: MayosPalette.darkTextSecondary,
    textMuted: MayosPalette.darkTextMuted,
    textDisabled: MayosPalette.darkTextMuted,
    accent: MayosPalette.blue,
    accentPressed: MayosPalette.bluePressed,
    onAccent: MayosPalette.white,
    accentSubtle: Color(0x1F2F6BFF),
    selectedSurface: MayosPalette.darkSelectedSurface,
    selectedBorder: MayosPalette.blue,
    focusRing: Color(0xFF6EA0FF),
    success: MayosPalette.successDark,
    warning: MayosPalette.warningDark,
    danger: MayosPalette.dangerDark,
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

  static const MayosThemeExtension light = MayosThemeExtension(
    brightness: Brightness.light,
    canvas: MayosPalette.lightCanvas,
    surface: MayosPalette.lightSurface,
    surfaceElevated: MayosPalette.lightSurfaceElevated,
    surfaceSunken: MayosPalette.lightSurfaceSunken,
    secondarySurface: MayosPalette.lightSecondarySurface,
    border: MayosPalette.lightBorder,
    borderStrong: MayosPalette.lightBorderStrong,
    textPrimary: MayosPalette.lightTextPrimary,
    textSecondary: MayosPalette.lightTextSecondary,
    textMuted: MayosPalette.lightTextMuted,
    textDisabled: MayosPalette.lightTextMuted,
    accent: MayosPalette.blueDeep,
    accentPressed: MayosPalette.bluePressedDeep,
    onAccent: MayosPalette.white,
    accentSubtle: Color(0x142563EB),
    selectedSurface: MayosPalette.lightSelectedSurface,
    selectedBorder: MayosPalette.blueDeep,
    focusRing: MayosPalette.blueDeep,
    success: MayosPalette.successLight,
    warning: MayosPalette.warningLight,
    danger: MayosPalette.dangerLight,
    onSuccess: MayosPalette.white,
    onWarning: MayosPalette.white,
    onDanger: MayosPalette.white,
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

  bool get isDark => brightness == Brightness.dark;

  @override
  MayosThemeExtension copyWith({
    Brightness? brightness,
    Color? canvas,
    Color? surface,
    Color? surfaceElevated,
    Color? surfaceSunken,
    Color? secondarySurface,
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
    Color? selectedSurface,
    Color? selectedBorder,
    Color? focusRing,
    Color? success,
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
    return MayosThemeExtension(
      brightness: brightness ?? this.brightness,
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceElevated: surfaceElevated ?? this.surfaceElevated,
      surfaceSunken: surfaceSunken ?? this.surfaceSunken,
      secondarySurface: secondarySurface ?? this.secondarySurface,
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
      selectedSurface: selectedSurface ?? this.selectedSurface,
      selectedBorder: selectedBorder ?? this.selectedBorder,
      focusRing: focusRing ?? this.focusRing,
      success: success ?? this.success,
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
  MayosThemeExtension lerp(
      ThemeExtension<MayosThemeExtension>? other, double t) {
    if (other is! MayosThemeExtension) {
      return this;
    }
    return MayosThemeExtension(
      brightness: t < 0.5 ? brightness : other.brightness,
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceElevated: Color.lerp(surfaceElevated, other.surfaceElevated, t)!,
      surfaceSunken: Color.lerp(surfaceSunken, other.surfaceSunken, t)!,
      secondarySurface:
          Color.lerp(secondarySurface, other.secondarySurface, t)!,
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
      selectedSurface: Color.lerp(selectedSurface, other.selectedSurface, t)!,
      selectedBorder: Color.lerp(selectedBorder, other.selectedBorder, t)!,
      focusRing: Color.lerp(focusRing, other.focusRing, t)!,
      success: Color.lerp(success, other.success, t)!,
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
