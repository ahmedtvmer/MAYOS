import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../router.dart';
import '../../core/display_language/copy_context.dart';
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
    final copy = displayCopyOf(context);
    return MayosScaffold(
      showLogo: true,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                copy.pageNotFound,
                textAlign: TextAlign.center,
                style:
                    MayosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
              ),
              const SizedBox(height: MayosSpacing.sm),
              Text(
                copy.pageMissingLead,
                textAlign: TextAlign.center,
                style: MayosTypography.of(context).body.copyWith(color: c.textSecondary),
              ),
              const SizedBox(height: MayosSpacing.xl),
              MayosButton(
                label: copy.goToHome,
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
