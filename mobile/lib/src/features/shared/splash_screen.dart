import 'package:flutter/material.dart';

import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/ui/myos_logo.dart';
import '../../core/ui/myos_progress.dart';
import '../../core/ui/myos_wallpaper.dart';

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
      data: MyosTheme.wallpaperForLanguage(
        Localizations.localeOf(context).languageCode,
      ),
      child: Builder(
        builder: (BuildContext context) {
          final MyosThemeExtension c = MyosTheme.of(context);
          return MyosWallpaper(
            child: Scaffold(
              backgroundColor: Colors.transparent,
              body: SafeArea(
                child: LayoutBuilder(
                  builder: (BuildContext context, BoxConstraints constraints) {
                    final double byWidth = constraints.maxWidth * 0.42;
                    final double byHeight = constraints.maxHeight * 0.22;
                    final double logoHeight =
                        (byWidth < byHeight ? byWidth : byHeight)
                            .clamp(72.0, 120.0);
                    // The lockup is centred on the padded canvas; the tagline
                    // is anchored just below its bottom edge so the composition
                    // stays connected without shifting the lockup off centre.
                    const double verticalPadding = MyosSpacing.md;
                    final double stackHeight =
                        constraints.maxHeight - verticalPadding * 2;
                    final double taglineTop =
                        stackHeight / 2 + logoHeight / 2 + MyosSpacing.lg;
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: MyosSpacing.xl,
                          vertical: verticalPadding),
                      child: Stack(
                        fit: StackFit.expand,
                        children: <Widget>[
                          Center(
                            child: MyosBrandLockup(
                              height: logoHeight,
                              variant: MyosBrandVariant.white,
                            ),
                          ),
                          PositionedDirectional(
                            top: taglineTop,
                            start: 0,
                            end: 0,
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                Text(
                                  displayCopyOf(context).brandTagline,
                                  textAlign: TextAlign.center,
                                  style: MyosTypography.of(context).serifMedium.copyWith(
                                    fontSize: 20,
                                    height: 1.2,
                                    color: c.textSecondary,
                                  ),
                                ),
                                const SizedBox(height: MyosSpacing.xxl),
                                const SizedBox(
                                  width: 120,
                                  child: MyosProgressIndicator(
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
