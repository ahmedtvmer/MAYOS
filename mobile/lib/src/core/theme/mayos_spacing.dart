import 'package:flutter/widgets.dart';

/// MAYOS spacing scale. One coherent 4-based scale, used everywhere so screens
/// do not invent their own padding.
abstract final class MayosSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 20;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 40;

  /// Standard horizontal inset for full-width screen content.
  static const EdgeInsets screenHorizontal =
      EdgeInsets.symmetric(horizontal: lg);

  /// Standard page padding for scrollable content.
  static const EdgeInsets screen = EdgeInsets.fromLTRB(lg, md, lg, xxl);
}

/// A deliberately small radius set. Screens pick one of these rather than
/// arbitrary corner values.
abstract final class MayosRadii {
  static const double small = 8;
  static const double medium = 12;
  static const double large = 16;
  static const double xlarge = 24;
  static const double pill = 999;

  static const BorderRadius smallRadius =
      BorderRadius.all(Radius.circular(small));
  static const BorderRadius mediumRadius =
      BorderRadius.all(Radius.circular(medium));
  static const BorderRadius largeRadius =
      BorderRadius.all(Radius.circular(large));
  static const BorderRadius xlargeRadius =
      BorderRadius.all(Radius.circular(xlarge));
  static const BorderRadius pillRadius =
      BorderRadius.all(Radius.circular(pill));
}

/// Shared interaction motion. Subtle and quick; no cinematic delays.
abstract final class MayosMotion {
  static const Duration fast = Duration(milliseconds: 150);
  static const Duration base = Duration(milliseconds: 220);
  static const Duration slow = Duration(milliseconds: 320);

  static const Curve standard = Curves.easeOutCubic;
  static const Curve emphasized = Curves.easeOutQuint;
}

/// Minimum interactive size. Material guidance: 48dp touch targets.
const double kMayosMinTapTarget = 48;

/// Named icon sizes, so screens pick one of these instead of a magic pixel
/// value (DESIGN.md: sizes are named like every other visual token).
abstract final class MayosIconSizes {
  /// Small inline icon that sits inside caption-height chrome (a chip/pill).
  static const double small = 14;

  /// Standard inline icon: trailing chevrons, row actions, sheet checks.
  static const double medium = 20;
}
