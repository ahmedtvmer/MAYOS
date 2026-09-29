import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../router.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_scaffold.dart';

/// Unknown location (issue #127): a small branded page instead of a blank
/// screen, with one way out — the account's home. `context.go(homePath)` asks
/// nothing of the rules; the router's redirect then places the user as it
/// would any other navigation (recovery gate, onboarding, mode).
class NotFoundScreen extends StatelessWidget {
  const NotFoundScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosScaffold(
      showLogo: true,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                'Page not found',
                textAlign: TextAlign.center,
                style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
              ),
              const SizedBox(height: MayosSpacing.sm),
              Text(
                'The page you are looking for does not exist or has moved.',
                textAlign: TextAlign.center,
                style: MayosTypography.body.copyWith(color: c.textSecondary),
              ),
              const SizedBox(height: MayosSpacing.xl),
              MayosButton(
                label: 'Go to home',
                expand: false,
                onPressed: () => context.go(homePath),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
