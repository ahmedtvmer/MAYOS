import 'package:flutter/material.dart';

import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_logo.dart';
import '../../core/ui/mayos_progress.dart';
import '../../core/ui/mayos_wallpaper.dart';

/// Startup surface.
///
/// The lockup is the hero and is centred both horizontally and vertically on
/// the screen. The gym photo sits behind it (issue #110), darkened by the fixed
/// scrim and blur, so the **white** lockup reads whatever the app theme is. The
/// tagline and progress indicator sit below the centre without shifting the
/// lockup off it. Size follows the smaller of width/height, clamped so it stays
/// inside safe margins on small phones and never dominates a tall one.
/// Intentionally no fabricated imagery or metrics.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: MayosTheme.wallpaper,
      child: Builder(
        builder: (BuildContext context) {
          final MayosThemeExtension c = MayosTheme.of(context);
          return MayosWallpaper(
            child: Scaffold(
              backgroundColor: Colors.transparent,
              body: SafeArea(
                child: LayoutBuilder(
                  builder:
                      (BuildContext context, BoxConstraints constraints) {
                    final double byWidth = constraints.maxWidth * 0.42;
                    final double byHeight = constraints.maxHeight * 0.22;
                    final double logoHeight =
                        (byWidth < byHeight ? byWidth : byHeight)
                            .clamp(72.0, 120.0);
                    // The lockup is centred on the padded canvas; the tagline
                    // is anchored just below its bottom edge so the composition
                    // stays connected without shifting the lockup off centre.
                    const double verticalPadding = MayosSpacing.md;
                    final double stackHeight =
                        constraints.maxHeight - verticalPadding * 2;
                    final double taglineTop =
                        stackHeight / 2 + logoHeight / 2 + MayosSpacing.lg;
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: MayosSpacing.xl, vertical: verticalPadding),
                      child: Stack(
                        fit: StackFit.expand,
                        children: <Widget>[
                          Center(
                            child: MayosBrandLockup(
                              height: logoHeight,
                              variant: MayosBrandVariant.white,
                            ),
                          ),
                          Positioned(
                            top: taglineTop,
                            left: 0,
                            right: 0,
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                Text(
                                  'Progress, Engineered.',
                                  textAlign: TextAlign.center,
                                  style: MayosTypography.serifMedium.copyWith(
                                    fontSize: 20,
                                    height: 1.2,
                                    color: c.textSecondary,
                                  ),
                                ),
                                const SizedBox(height: MayosSpacing.xxl),
                                const SizedBox(
                                  width: 120,
                                  child: MayosProgressIndicator(
                                    value: null,
                                    height: 3,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
