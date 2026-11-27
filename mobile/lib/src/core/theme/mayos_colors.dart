import 'package:flutter/material.dart';

/// Raw MAYOS brand palette. These are the only literal colors in the app; every
/// widget reads semantic tokens instead (see [MayosThemeExtension]).
///
/// Red on charcoal (#885). One brand red, the logo's #B3001B, is used for
/// everything red in both themes: fills, links, red text, outlines and danger.
/// Danger is told apart from the brand by shape (outlined or text buttons with
/// an icon, confirm sheets), not by a second red. Dark mode is a neutral
/// charcoal system, light mode a warm off-white system; neither is an
/// inversion of the other.
abstract final class MayosPalette {
  // Brand red (action / progression / selection / danger).
  static const Color red = Color(0xFFB3001B);
  static const Color redPressed = Color(0xFF8F0016);

  // Dark surfaces — layered neutral charcoal, matching the app icon (#141414).
  static const Color darkCanvas = Color(0xFF141414);
  static const Color darkSurface = Color(0xFF1C1C1E);
  static const Color darkSurfaceElevated = Color(0xFF252528);
  static const Color darkSurfaceSunken = Color(0xFF0D0D0E);
  static const Color darkSecondarySurface = Color(0xFF18181A);
  static const Color darkBorder = Color(0xFF2B2B30);
  static const Color darkBorderStrong = Color(0xFF3D3D44);
  static const Color darkSelectedSurface = Color(0xFF3A0E14);

  static const Color darkTextPrimary = Color(0xFFF5F5F4);
  static const Color darkTextSecondary = Color(0xFFB3B3BA);
  static const Color darkTextMuted = Color(0xFF85858E);

  // Light surfaces — warm off-white canvas, white elevated surfaces.
  static const Color lightCanvas = Color(0xFFF5F4F2);
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightSurfaceElevated = Color(0xFFFFFFFF);
  static const Color lightSurfaceSunken = Color(0xFFEDEBE8);
  static const Color lightSecondarySurface = Color(0xFFF1F0EE);
  static const Color lightBorder = Color(0xFFE3E1DD);
  static const Color lightBorderStrong = Color(0xFFCFCCC7);
  static const Color lightSelectedSurface = Color(0xFFFCE7EA);

  static const Color lightTextPrimary = Color(0xFF18181B);
  static const Color lightTextSecondary = Color(0xFF52525B);
  static const Color lightTextMuted = Color(0xFF71717A);

  // Semantic states. Success and warning keep their own hues; danger is the
  // brand red (see the class comment).
  static const Color successDark = Color(0xFF34D399);
  static const Color warningDark = Color(0xFFF5A524);
  static const Color dangerDark = red;
  static const Color successLight = Color(0xFF16A34A);
  static const Color warningLight = Color(0xFFD97706);
  static const Color dangerLight = red;

  static const Color white = Color(0xFFFFFFFF);
  static const Color black = Color(0xFF000000);

  // Wallpaper (#110, #886): text and borders drawn directly on the dark gym
  // photo (60% black overlay + blur). Neutral greys lightened from the dark
  // theme so body text, links and field edges clear WCAG AA against the
  // photo's bright spots. See `mobile/assets/ATTRIBUTION.md`.
  static const Color wallpaperTextSecondary = Color(0xFFD4D4D8);
  static const Color wallpaperTextMuted = Color(0xFFC4C4CA);
  static const Color wallpaperDanger = Color(0xFFFCA5A5);
  static const Color wallpaperBorder = Color(0xFF8A8A93);
  static const Color wallpaperBorderStrong = Color(0xFFA1A1AA);
  static const Color wallpaperLink = Color(0xFFF5F5F4);
}
