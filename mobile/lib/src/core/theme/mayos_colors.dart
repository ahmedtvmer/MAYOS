import 'package:flutter/material.dart';

/// Raw MAYOS brand palette. These are the only literal colors in the app; every
/// widget reads semantic tokens instead (see [MayosThemeExtension]).
///
/// Dark mode is a deliberately designed deep-navy system, light mode a refined
/// warm-neutral system. Neither is an inversion of the other.
abstract final class MayosPalette {
  // Brand blue (action / progression / selection).
  static const Color blue = Color(0xFF2F6BFF);
  static const Color bluePressed = Color(0xFF2257DE);
  static const Color blueDeep = Color(0xFF2563EB);
  static const Color bluePressedDeep = Color(0xFF1D4ED8);

  // Dark surfaces — layered deep navy / blue-black.
  static const Color darkCanvas = Color(0xFF0A1422);
  static const Color darkSurface = Color(0xFF101D2E);
  static const Color darkSurfaceElevated = Color(0xFF16263B);
  static const Color darkSurfaceSunken = Color(0xFF070F1A);
  static const Color darkSecondarySurface = Color(0xFF0D1826);
  static const Color darkBorder = Color(0xFF22344C);
  static const Color darkBorderStrong = Color(0xFF324A69);
  static const Color darkSelectedSurface = Color(0xFF13294A);

  static const Color darkTextPrimary = Color(0xFFF3F6FB);
  static const Color darkTextSecondary = Color(0xFFA7B6CB);
  static const Color darkTextMuted = Color(0xFF6F8199);

  // Light surfaces — refined off-white canvas, white elevated surfaces.
  static const Color lightCanvas = Color(0xFFF6F5F2);
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightSurfaceElevated = Color(0xFFFFFFFF);
  static const Color lightSurfaceSunken = Color(0xFFEFEDE8);
  static const Color lightSecondarySurface = Color(0xFFF1F3F7);
  static const Color lightBorder = Color(0xFFE2E4E9);
  static const Color lightBorderStrong = Color(0xFFCFD4DC);
  static const Color lightSelectedSurface = Color(0xFFE9F0FE);

  static const Color lightTextPrimary = Color(0xFF0E1B2E);
  static const Color lightTextSecondary = Color(0xFF4B5A70);
  static const Color lightTextMuted = Color(0xFF8593A6);

  // Semantic states (shared hues, tuned per theme).
  static const Color successDark = Color(0xFF34D399);
  static const Color warningDark = Color(0xFFF5A524);
  static const Color dangerDark = Color(0xFFF87171);
  static const Color successLight = Color(0xFF16A34A);
  static const Color warningLight = Color(0xFFD97706);
  static const Color dangerLight = Color(0xFFDC2626);

  static const Color white = Color(0xFFFFFFFF);
  static const Color black = Color(0xFF000000);
}
