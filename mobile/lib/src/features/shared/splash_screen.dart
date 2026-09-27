import 'package:flutter/material.dart';

import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_logo.dart';
import '../../core/ui/mayos_progress.dart';

/// Startup surface.
///
/// The lockup is the hero and is centred both horizontally and vertically on
/// the screen. The monochrome lockup (`auto`) picks white on the dark canvas
/// and black on the light one. The tagline and progress indicator sit below the
/// centre without shifting the lockup off it. Size follows the smaller of
/// width/height, clamped so it stays inside safe margins on small phones and
/// never dominates a tall one. Intentionally no fabricated imagery or metrics.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Scaffold(
      backgroundColor: c.canvas,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final double byWidth = constraints.maxWidth * 0.42;
            final double byHeight = constraints.maxHeight * 0.22;
            final double logoHeight =
                (byWidth < byHeight ? byWidth : byHeight).clamp(72.0, 120.0);
            // The lockup is centred on the padded canvas; the taglines are
            // anchored just below its bottom edge so the composition stays
            // connected without shifting the lockup off centre.
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
                  Center(child: MayosBrandLockup(height: logoHeight)),
                  Positioned(
                    top: taglineTop,
                    left: 0,
                    right: 0,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Text(
                          'TRAIN BETTER',
                          textAlign: TextAlign.center,
                          style: MayosTypography.caption.copyWith(
                            color: c.textSecondary,
                            letterSpacing: 3.5,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: MayosSpacing.xxs),
                        Text(
                          'THINK DEEPER',
                          textAlign: TextAlign.center,
                          style: MayosTypography.caption.copyWith(
                            color: c.textMuted,
                            letterSpacing: 3.5,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(height: MayosSpacing.xxl),
                        SizedBox(
                          width: 120,
                          child: MayosProgressIndicator(
                            value: null,
                            height: 3,
                            color: c.accent,
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
    );
  }
}
