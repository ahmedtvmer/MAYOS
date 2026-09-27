import 'package:flutter/material.dart';

import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_logo.dart';
import '../../core/ui/mayos_progress.dart';

/// Startup surface.
///
/// The composition is centred horizontally and sits slightly above the
/// vertical centre, like the reference splash. Dark uses the coloured
/// (`mayos-logo-blue`) lockup as the hero on deep navy; light keeps the black
/// lockup. Size follows the smaller of width/height so it stays inside safe
/// margins on small phones. Intentionally no fabricated imagery or metrics.
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
            final double byWidth = constraints.maxWidth * 0.46;
            final double byHeight = constraints.maxHeight * 0.26;
            final double logoHeight =
                (byWidth < byHeight ? byWidth : byHeight).clamp(88.0, 200.0);
            return Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xl, vertical: MayosSpacing.md),
              child: SizedBox(
                width: double.infinity,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: <Widget>[
                    const Spacer(flex: 42),
                    MayosBrandLockup(height: logoHeight),
                    const SizedBox(height: MayosSpacing.lg),
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
                    const SizedBox(height: MayosSpacing.xxxl),
                    SizedBox(
                      width: 120,
                      child: MayosProgressIndicator(
                        value: null,
                        height: 3,
                        color: c.accent,
                      ),
                    ),
                    const Spacer(flex: 58),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
