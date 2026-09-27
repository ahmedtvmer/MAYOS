import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/mayos_colors.dart';
import '../theme/mayos_theme.dart';

/// The shared dark gym photo backdrop for the logged-out surfaces (#110):
/// splash, log in, register, forgot password and reset password.
///
/// It is a full-bleed [Stack]: a solid dark fallback, the bundled photo under a
/// fixed Gaussian blur and a fixed black scrim, then the screen content. The
/// photo is cover-fit so it never distorts. The blur and scrim are **design
/// constants**, not user settings. The lockup and form are drawn in the
/// wallpaper theme so everything stays readable (see `assets/ATTRIBUTION.md`).
///
/// Signed-in screens never use this. Only the listed logged-out surfaces do.
class MayosWallpaper extends StatelessWidget {
  const MayosWallpaper({super.key, required this.child});

  /// The bundled photo. Free licence; provenance in `assets/ATTRIBUTION.md`.
  static const String imageAsset = 'assets/images/gym-wallpaper.jpg';

  /// Stable key on the photo layer so tests can prove its presence.
  static const Key photoKey = Key('mayos.wallpaper.photo');

  /// Black scrim over the photo. Fixed; within the 55–65% design band.
  static const double overlayOpacity = 0.6;

  /// Gaussian blur sigma applied to the photo. Fixed; within the 4–8 band.
  static const double blurSigma = 6;

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      // The photo is always dark, so the status bar stays light on these
      // screens regardless of the app theme.
      value: MayosTheme.overlayStyle(MayosThemeExtension.dark),
      child: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          // Solid dark fallback shown until the photo decodes.
          const ColoredBox(color: MayosPalette.darkCanvas),
          // ClipRect keeps the blurred edges from bleeding outside the frame.
          ClipRect(
            child: ImageFiltered(
              imageFilter: ImageFilter.blur(
                sigmaX: blurSigma,
                sigmaY: blurSigma,
              ),
              child: Image.asset(
                imageAsset,
                key: photoKey,
                fit: BoxFit.cover,
                gaplessPlayback: true,
                filterQuality: FilterQuality.low,
                excludeFromSemantics: true,
              ),
            ),
          ),
          ColoredBox(color: Colors.black.withValues(alpha: overlayOpacity)),
          child,
        ],
      ),
    );
  }
}
